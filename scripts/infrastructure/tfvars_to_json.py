import argparse
import json
from pathlib import Path

import hcl2


def normalize(value: object) -> object:
    if isinstance(value, dict):
        return {str(normalize(key)): normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("terraform_var_file", type=Path)
    arguments = parser.parse_args()

    with arguments.terraform_var_file.open(encoding="utf-8") as stream:
        values = normalize(hcl2.load(stream))
    print(json.dumps(values, separators=(",", ":")))


if __name__ == "__main__":
    main()
