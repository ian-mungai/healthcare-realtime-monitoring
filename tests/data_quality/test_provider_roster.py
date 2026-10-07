"""The synthetic provider roster behind the dbt provider seed: production-like NPIs, names and taxonomy codes.

Failure modes of the generator (written before the generator):

1. An NPI fails the NPI check digit (Luhn over the 80840 prefix and the first nine digits): every roster NPI must pass.
2. Two providers share an NPI or a name: each is unique, even when two candidates collide.
3. The committed seed drifts from the generator (a hand edit, a changed list): the seed must equal the rebuild.
4. A generated NPI belongs to a real clinician anywhere in the US, or a generated name to a real Washington clinician:
   the provider moves to its next candidate and the attempt is recorded; other providers keep theirs.
5. The NPPES registry fails (HTTP error, timeout, unexpected body): stop before any file changes.
6. Collisions keep coming: stop after the attempt limit instead of looping.
7. A real clinician's details are kept: the check records counts only, never a matched name or number.
8. A taxonomy code is not in the NUCC code set: every roster code is on the verified list.

Overlapping versions and more than one current version per provider are owned by the dbt tests on dim_provider.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import httpx
import pytest
import respx

from scripts.nppes import provider_roster
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]
NPPES = "https://npiregistry.cms.hhs.gov/api/"


class FakeRegistry:
    """A registry where the listed NPIs and names belong to real clinicians."""

    def __init__(self, npis: frozenset[str] = frozenset(), names: frozenset[tuple[str, str]] = frozenset()) -> None:
        self.npis, self.names = set(npis), set(names)

    def npi_exists(self, npi: str) -> bool:
        return npi in self.npis

    def name_exists(self, first: str, last: str, state: str) -> bool:
        return (first, last) in self.names


def spec() -> dict:
    return json.loads((ROOT / "config" / "provider_roster.json").read_text(encoding="utf-8"))


def test_npi_check_digit() -> None:
    # CMS's published example NPI.
    expect.equal(provider_roster.is_valid_npi("1234567893"), True)
    expect.equal(provider_roster.is_valid_npi("1234567890"), False)
    expect.equal(provider_roster.is_valid_npi("123456789"), False)


def test_every_roster_npi_is_valid_and_unique() -> None:
    rows = provider_roster.build_history(spec())
    current = [row for row in rows if row["is_current"] == "true"]

    expect.equal([row["provider_npi"] for row in rows if not provider_roster.is_valid_npi(row["provider_npi"])], [])
    expect.equal(len({row["provider_npi"] for row in current}), len(current))
    expect.equal(len({row["provider_name"] for row in current}), len(current))
    expect.equal({row["taxonomy_code"] for row in rows} - set(provider_roster.NUCC_SPECIALTIES), set())


def test_the_committed_seed_equals_the_rebuild() -> None:
    with (ROOT / "dbt" / "seeds" / "provider_history.csv").open(newline="", encoding="utf-8") as handle:
        committed = list(csv.DictReader(handle))

    expect.equal(committed, provider_roster.build_history(spec()))


def test_a_real_npi_or_name_moves_only_that_provider_to_its_next_candidate() -> None:
    base = spec() | {"npi_attempts": {}, "name_attempts": {}}
    before = provider_roster.providers(base)
    registry = FakeRegistry(npis=frozenset({before[0].npi}), names=frozenset({(before[1].first_name, before[1].last_name)}))

    resolved, counts = provider_roster.resolve(base, registry)

    after = provider_roster.providers(resolved)
    expect.equal((resolved["npi_attempts"], resolved["name_attempts"]), ({"0": 1}, {"1": 1}))
    expect.not_equal(after[0].npi, before[0].npi)
    expect.not_equal((after[1].first_name, after[1].last_name), (before[1].first_name, before[1].last_name))
    expect.equal([provider.npi for provider in after[1:]], [provider.npi for provider in before[1:]])
    expect.equal(counts["npi_collisions"], 1)
    expect.equal(counts["name_collisions"], 1)
    # Counts only: nothing in the result names the real clinician.
    expect.equal(set(counts), {"providers", "npis_checked", "names_checked", "npi_collisions", "name_collisions"})


def test_duplicate_candidates_are_replaced_without_a_registry() -> None:
    # Three first names and twelve surnames give 36 names for 24 providers, so first candidates clash.
    small = spec() | {"npi_attempts": {}, "name_attempts": {}, "first_names": ["Ana", "Ben", "Cy"], "last_names": [f"Surname{n}" for n in range(12)]}

    resolved, _ = provider_roster.resolve(small, None)

    names = [(provider.first_name, provider.last_name) for provider in provider_roster.providers(resolved)]
    expect.equal(len(set(names)), len(names))
    expect.equal(len(names), 24)


def test_endless_collisions_stop_at_the_attempt_limit() -> None:
    class EveryoneIsReal(FakeRegistry):
        def npi_exists(self, npi: str) -> bool:
            return True

    with pytest.raises(provider_roster.RosterError, match="attempt limit"):
        provider_roster.resolve(spec(), EveryoneIsReal())


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, json={"Errors": [{"description": "bad"}]}), httpx.ConnectTimeout("timed out")])
def test_a_registry_failure_stops_before_any_file_changes(tmp_path: Path, response: httpx.Response | Exception) -> None:
    route = respx.get(NPPES)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    config, seed = tmp_path / "provider_roster.json", tmp_path / "provider_history.csv"
    config.write_text("{}", encoding="utf-8")
    seed.write_text("unchanged", encoding="utf-8")

    with pytest.raises(provider_roster.RosterError, match="NPPES"):
        provider_roster.run(spec(), config, seed, provider_roster.NppesRegistry(httpx.Client()))

    expect.equal((config.read_text(encoding="utf-8"), seed.read_text(encoding="utf-8")), ("{}", "unchanged"))
