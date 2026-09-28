# Quality Checks

Every commit runs the hooks in `.pre-commit-config.yaml` through `.githooks/`, and CI runs the same hooks on every push and pull request. A finding names the file and line, the policy below and how to fix it. There are no bypasses: do not use `SKIP=` or `git commit --no-verify`. If a policy blocks a valid change, fix the check or raise the policy with the repository owner before committing.

## Setup

```zsh
.venv/bin/python -m pip install -r requirements_dev.txt
.venv/bin/python -m tools.install_tools
git config core.hooksPath .githooks
```

`tools/install_tools.py` installs pinned gitleaks and tflint binaries after verifying their SHA-256 checksums, and a pinned checkov release in its own virtual environment under the ignored `.tools/` folder.

Run every hook across the repository:

```zsh
.venv/bin/pre-commit run --all-files
```

The checks live in the `tools/` package. They are verified end to end by `tools/test_checks.py`, which runs each hook through `pre-commit` in a scratch repository, rather than by the pytest suite. Prove that each check blocks a bad sample and passes a good one:

```zsh
.venv/bin/python -m tools.test_checks
```

## Secrets and Credential Files

gitleaks scans staged changes on commit and the full Git history in CI. Environment files other than `.env.example`, Terraform state and state backups, private keys and cloud credential files are blocked by name. Store secrets in AWS Secrets Manager and keep private deployment values in the ignored `.env`.

## Data Files

Data files (`.csv`, `.tsv`, `.parquet`, `.xlsx`, `.xls`, `.jsonl`, `.ndjson`, `.avro`, `.db`, `.sqlite`) are allowed only in the declared folders `dbt/seeds/` and `tests/fixtures/`, which hold synthetic data only. Any file over 5 MB is blocked unless Git LFS stores it. Never commit real personal data.

## Commit Messages

Subjects follow Conventional Commits: `<type>(<scope>): <description>` with the types `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `style` and `revert`. Messages carry no AI credit, generated-with line or agent-session trailer. Human co-authors and factual mentions of tools are allowed. The commit-msg hook checks each new message; CI checks every stored message in the pushed range.

## Documentation Matches the Code

Every environment variable the Python code reads is listed in `.env.example`, either as a local input or as a commented reference line. When a script, command-line flag or environment variable is removed, the documentation that names it must change in the same commit.

## Lint and Type Settings

Ruff keeps line length 160 and at least the rule families `E`, `F`, `I`, `B`, `UP` and `SIM`, with no ignore or exclude settings. MyPy settings may only get stricter, and its exclude list may not grow. Suppression comments are blocked except the one approved exception below; fix the code instead.

| Rule | Allowed only in | Condition |
| --- | --- | --- |
| Ruff `S603` | `tools/process.py` | Full executable path, list arguments, no shell, stdin closed and a timeout, with the reason on the line |

## Process Launcher

Repository tooling starts programs through `run_command` in `tools/process.py`. The subprocess-imports check runs in warn mode: it reports the remaining direct `subprocess` imports without blocking until they are migrated.

## Terraform

`terraform fmt` runs on every Terraform change. tflint and checkov run in warn mode on Terraform changes and in CI: they report findings without blocking until the current findings are triaged.
