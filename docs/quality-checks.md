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

## Documentation Review

Before every commit, every document in the repository is reviewed against the staged code, configuration and decisions, and the outcome is recorded in `.documentation_review.json`. The check discovers `README`, `LICENSE`, Markdown, HTML and other document formats and every file under `docs/`; requirements files and version pins are not documents. It blocks a commit when the record is missing, a document is unreviewed, any staged file changed after the review or new documentation is untracked. It checks the evidence, not the truth of the notes.

1. Stage the intended changes by name.
2. Draft the record: `.venv/bin/python -m tools.documentation_review prepare --reviewer "<name>" --reviewed-at <YYYY-MM-DDTHH:MM:SSZ> --refresh`.
3. Read every listed document against the staged change. Correct stale content, then set each `outcome` to `current`, `updated` or `historical` with a note on what was checked. Historical records such as release notes keep their original content.
4. Stage `.documentation_review.json` and commit. If you stage anything else afterwards, repeat from step 2.

## Lint and Type Settings

Ruff keeps line length 160 and at least the rule families `E`, `F`, `I`, `B`, `UP`, `SIM` and `T20` (no `print`: command-line scripts write to `sys.stdout`, services log through `logging`), with no ignore or exclude settings. MyPy settings may only get stricter, and its exclude list may not grow. Suppression comments are blocked except the one approved exception below; fix the code instead.

| Rule | Allowed only in | Condition |
| --- | --- | --- |
| Ruff `S603` | `tools/process.py` | Full executable path, list arguments, no shell, stdin closed and a timeout, with the reason on the line |

## Process Launcher

Repository tooling starts programs through `run_command` in `tools/process.py`. The subprocess-imports check runs in warn mode: it reports the remaining direct `subprocess` imports without blocking until they are migrated.

## Terraform

`terraform fmt` runs on every Terraform change. tflint and checkov run in warn mode on Terraform changes and in CI: they report findings without blocking until the current findings are triaged.
