"""Build the synthetic provider roster behind the dbt provider seed: production-like NPIs, names and taxonomy codes.

Usage: python -m scripts.nppes.provider_roster [--check-nppes]

config/provider_roster.json holds the roster's design: the seed, the specialties and how many providers each has, the
name lists and the providers' changes over time (a new specialty, a move between states), which make the seed a real
type 2 slowly changing dimension. Each provider's NPI and name come from seeded candidates; the build writes
dbt/seeds/provider_history.csv from the config alone, so a clean checkout rebuilds the same file without a network.

--check-nppes asks the NPPES NPI Registry whether any NPI belongs to a real clinician anywhere in the US or any name
to a real Washington clinician. A provider with a match moves to its next candidate and the config records the attempt
number. The config keeps counts only: no matched number or name of a real clinician is ever written.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "provider_roster.json"
SEED_PATH = ROOT / "dbt" / "seeds" / "provider_history.csv"
HISTORY_FIELDS = (
    "provider_npi",
    "provider_name",
    "taxonomy_code",
    "taxonomy_description",
    "provider_state",
    "valid_from",
    "valid_to",
    "is_current",
    "data_source",
)
DATA_SOURCE = "synthetic_roster"
# Checked against the NUCC Health Care Provider Taxonomy code set 26.1 (nucc_taxonomy_261.csv).
NUCC_SPECIALTIES = {
    "208M00000X": "Hospitalist",
    "207R00000X": "Internal Medicine",
    "207RC0200X": "Critical Care Medicine",
    "207RP1001X": "Pulmonary Disease",
    "207RC0000X": "Cardiovascular Disease",
    "207RI0200X": "Infectious Disease",
    "207RN0300X": "Nephrology",
    "208600000X": "Surgery",
}
# NPIs of individual providers start with 1; the check digit is Luhn over the card issuer prefix 80840 and nine digits.
NPI_PREFIX = "80840"
MAX_ATTEMPTS = 20
NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"


class RosterError(RuntimeError):
    """The roster cannot be built; the message never names a real clinician."""


class Registry(Protocol):
    def npi_exists(self, npi: str) -> bool: ...

    def name_exists(self, first: str, last: str, state: str) -> bool: ...


@dataclass(frozen=True)
class Provider:
    index: int
    npi: str
    first_name: str
    last_name: str
    taxonomy_code: str


def check_digit(first_nine: str) -> int:
    """The Luhn check digit of the 80840 prefix and the NPI's first nine digits."""
    total = 0
    for position, digit in enumerate(reversed(NPI_PREFIX + first_nine)):
        value = int(digit)
        if position % 2 == 0:
            value *= 2
            value -= 9 if value > 9 else 0
        total += value
    return (10 - total % 10) % 10


def is_valid_npi(npi: str) -> bool:
    return len(npi) == 10 and npi.isdigit() and check_digit(npi[:9]) == int(npi[9])


def _number(seed: str, kind: str, index: int, attempt: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{kind}:{index}:{attempt}".encode()).digest()[:8], "big")


def candidate_npi(seed: str, index: int, attempt: int) -> str:
    first_nine = f"1{_number(seed, 'npi', index, attempt) % 10**8:08d}"
    return f"{first_nine}{check_digit(first_nine)}"


def candidate_name(spec: dict[str, Any], index: int, attempt: int) -> tuple[str, str]:
    number = _number(spec["seed"], "name", index, attempt)
    first_names, last_names = spec["first_names"], spec["last_names"]
    return first_names[number % len(first_names)], last_names[(number // len(first_names)) % len(last_names)]


def specialty_slots(spec: dict[str, Any]) -> list[str]:
    """Each provider's first specialty, in roster order, before any initial override."""
    unknown = [item["code"] for item in spec["specialties"] if item["code"] not in NUCC_SPECIALTIES]
    if unknown:
        raise RosterError(f"taxonomy codes not on the verified NUCC list: {', '.join(unknown)}")
    return [item["code"] for item in spec["specialties"] for _ in range(item["providers"])]


def providers(spec: dict[str, Any]) -> list[Provider]:
    """The roster's providers with the NPI and name of their recorded candidate attempt."""
    initial = spec.get("initial", {})
    result = []
    for index, taxonomy_code in enumerate(specialty_slots(spec)):
        first, last = candidate_name(spec, index, int(spec["name_attempts"].get(str(index), 0)))
        result.append(
            Provider(
                index=index,
                npi=candidate_npi(spec["seed"], index, int(spec["npi_attempts"].get(str(index), 0))),
                first_name=first,
                last_name=last,
                taxonomy_code=initial.get(str(index), {}).get("taxonomy_code", taxonomy_code),
            )
        )
    return result


def resolve(spec: dict[str, Any], registry: Registry | None) -> tuple[dict[str, Any], dict[str, int]]:
    """The spec with every provider on an unused, unregistered NPI and name, and counts of what the check found."""
    resolved = copy.deepcopy(spec)
    counts = {"providers": 0, "npis_checked": 0, "names_checked": 0, "npi_collisions": 0, "name_collisions": 0}
    used: dict[str, set[Any]] = {"npi": set(), "name": set()}
    for index in range(len(specialty_slots(spec))):
        key = str(index)
        for kind in ("npi", "name"):
            attempts = resolved[f"{kind}_attempts"]
            while True:
                attempt = int(attempts.get(key, 0))
                if attempt >= MAX_ATTEMPTS:
                    raise RosterError(f"provider {index} reached the attempt limit of {MAX_ATTEMPTS} for its {kind}")
                value = candidate_npi(spec["seed"], index, attempt) if kind == "npi" else candidate_name(resolved, index, attempt)
                clash = value in used[kind]
                real = not clash and registry is not None and _registered(registry, kind, value, spec["state"], counts)
                if not (clash or real):
                    used[kind].add(value)
                    break
                counts[f"{kind}_collisions"] += int(real)
                attempts[key] = attempt + 1
        counts["providers"] += 1
    return resolved, counts


def _registered(registry: Registry, kind: str, value: Any, state: str, counts: dict[str, int]) -> bool:
    counts[f"{kind}s_checked"] += 1
    if kind == "npi":
        return registry.npi_exists(value)
    first, last = value
    return registry.name_exists(first, last, state)


def build_history(spec: dict[str, Any]) -> list[dict[str, str]]:
    """One row per provider version, ordered by NPI and start date like scripts/nppes/update_provider_history.py."""
    roster = providers(spec)
    if len({provider.npi for provider in roster}) != len(roster) or len({(p.first_name, p.last_name) for p in roster}) != len(roster):
        raise RosterError("two providers share an NPI or a name; run python -m scripts.nppes.provider_roster to resolve them")
    initial = spec.get("initial", {})
    rows = []
    for provider in roster:
        fields = {"taxonomy_code": provider.taxonomy_code, "provider_state": initial.get(str(provider.index), {}).get("state", spec["state"])}
        starts = [spec["start"]]
        states = [dict(fields)]
        for change in sorted((item for item in spec.get("changes", []) if item["provider"] == provider.index), key=lambda item: item["on"]):
            if "taxonomy_code" in change:
                fields["taxonomy_code"] = change["taxonomy_code"]
            if "state" in change:
                fields["provider_state"] = change["state"]
            starts.append(change["on"])
            states.append(dict(fields))
        for number, (start, state) in enumerate(zip(starts, states, strict=True)):
            if state["taxonomy_code"] not in NUCC_SPECIALTIES:
                raise RosterError(f"taxonomy code {state['taxonomy_code']} is not on the verified NUCC list")
            last = number == len(starts) - 1
            rows.append(
                {
                    "provider_npi": provider.npi,
                    "provider_name": f"{provider.first_name} {provider.last_name}",
                    "taxonomy_code": state["taxonomy_code"],
                    "taxonomy_description": NUCC_SPECIALTIES[state["taxonomy_code"]],
                    "provider_state": state["provider_state"],
                    "valid_from": start,
                    "valid_to": "" if last else starts[number + 1],
                    "is_current": "true" if last else "false",
                    "data_source": DATA_SOURCE,
                }
            )
    return sorted(rows, key=lambda row: (row["provider_npi"], row["valid_from"]))


class NppesRegistry:
    """The NPPES NPI Registry API, version 2.1; any match counts, its details are never read."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def _matches(self, params: dict[str, str]) -> bool:
        try:
            response = self.client.get(NPPES_URL, params={"version": "2.1", **params}, timeout=30)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RosterError(f"NPPES registry request failed: {type(error).__name__}") from None
        count = body.get("result_count") if isinstance(body, dict) else None
        if not isinstance(count, int):
            raise RosterError("NPPES registry returned a body without result_count")
        return count > 0

    def npi_exists(self, npi: str) -> bool:
        return self._matches({"number": npi})

    def name_exists(self, first: str, last: str, state: str) -> bool:
        return self._matches({"first_name": first, "last_name": last, "state": state, "enumeration_type": "NPI-1", "limit": "1"})


def _replace(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(text)
    os.replace(handle.name, path)


def run(spec: dict[str, Any], config_path: Path, seed_path: Path, registry: Registry | None) -> dict[str, int]:
    """Resolve, build and write the config and the seed; nothing is written unless every step succeeds."""
    resolved, counts = resolve(spec, registry)
    rows = build_history(resolved)
    if registry is not None:
        resolved["nppes_check"] = {"checked_on": datetime.now(UTC).date().isoformat(), "registry": "NPPES NPI Registry API 2.1", "counts": counts}
    seed = io.StringIO()
    writer = csv.DictWriter(seed, fieldnames=HISTORY_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _replace(config_path, json.dumps(resolved, indent=2) + "\n")
    _replace(seed_path, seed.getvalue())
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-nppes", action="store_true", help="check every NPI and name against the NPPES NPI Registry")
    args = parser.parse_args()
    spec = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.check_nppes:
        with httpx.Client(headers={"Accept": "application/json"}) as client:
            counts = run(spec, CONFIG_PATH, SEED_PATH, NppesRegistry(client))
    else:
        counts = run(spec, CONFIG_PATH, SEED_PATH, None)
    sys.stdout.write(json.dumps(counts, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
