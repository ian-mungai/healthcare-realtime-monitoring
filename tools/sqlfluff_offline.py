"""Start the SQLFluff command line with dbt's relation cache disabled, so the dbt templater never queries AWS.

Run only by ``tools/lint_sql.py`` with the Python in ``.tools/sqlfluff``; it imports nothing from this repository. The
dbt templater fills the adapter's relation cache before compiling, and dbt-athena fills it by listing the Glue catalog.
Linting only needs compiled SQL, so the cache stays empty and dbt compiles the models from the manifest alone.
"""

from __future__ import annotations

import sys

from dbt.adapters.base.impl import BaseAdapter
from sqlfluff.cli.commands import cli


def skip_relations_cache(*_args: object, **_kwargs: object) -> None:
    """Leave the relation cache empty instead of listing the warehouse's relations."""


if __name__ == "__main__":
    BaseAdapter.set_relations_cache = skip_relations_cache
    sys.exit(cli())
