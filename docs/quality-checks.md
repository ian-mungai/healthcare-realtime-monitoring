# Quality Checks

Every commit runs the hooks in `.pre-commit-config.yaml` through `.githooks/`, and CI runs the same hooks on every push and pull request. A finding names the file and line, the policy below and how to fix it. There are no bypasses: do not use `SKIP=` or `git commit --no-verify`. If a policy blocks a valid change, fix the check or raise the policy with the repository owner before committing.

## Setup

```zsh
.venv/bin/python -m pip install -r requirements_dev.txt
.venv/bin/python -m tools.install_tools
git config core.hooksPath .githooks
```

`tools/install_tools.py` installs pinned gitleaks and tflint binaries after verifying their SHA-256 checksums, and pinned checkov and SQLFluff releases in their own virtual environments under the ignored `.tools/` folder. SQLFluff's environment also holds dbt-core and dbt-athena at the versions the dbt image uses; they stay out of `.venv` because dbt-athena's `pyathena` range conflicts with the project pin.

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

Ruff keeps line length 160 and at least the rule families `E`, `F`, `I`, `B`, `UP`, `SIM`, `T20` (no `print`: command-line scripts write to `sys.stdout`, services log through `logging`) and `S` (security), with no ignore or exclude settings. Athena cannot bind table names as query parameters, so queries that name tables check every name against an identifier pattern and fill a `string.Template`, never an f-string. MyPy settings may only get stricter, and its exclude list may not grow. Suppression comments are blocked except the one approved exception below; fix the code instead. Tests check results with `testkit.expect` (`equal`, `is_in`, `identical`, `fail` and related helpers) instead of `assert`, which Python removes under `-O`; write a condition that narrows a type as an `if` that calls `expect.fail`.

| Rule | Allowed only in | Condition |
| --- | --- | --- |
| Ruff `S603` | `tools/process.py` | Full executable path, list arguments, no shell, stdin closed and a timeout, with the reason on the line |

## SQL

SQLFluff lints every dbt model and singular test with the dbt templater and the Athena dialect, using the settings in `.sqlfluff`: lowercase keywords, functions, literals and types, four-space indentation, trailing commas and line length 160. `tools/lint_sql.py` runs it with fixed placeholder deployment names, so the result never depends on a local `.env`. The dbt templater normally lists the Glue catalog before compiling; `tools/sqlfluff_offline.py` turns that off, and the runner removes any AWS profile and supplies placeholder credentials, so linting never reaches AWS and any attempt fails instead of using a real login. Run SQLFluff only through this runner. The lint-settings check keeps the templater, dialect and line length and blocks any setting that narrows the rules; SQL `noqa` comments are blocked like Python suppressions.

```zsh
.venv/bin/python -m tools.lint_sql          # report
.venv/bin/python -m tools.lint_sql --fix    # apply SQLFluff's layout fixes, then review the diff
```

## Process Launcher

All Python code starts programs through `run_command` in `tools/process.py`, including the dbt and Soda container wrappers, whose images copy the launcher. The subprocess-imports check blocks any other `subprocess` import.

## Terraform

`terraform fmt`, tflint and checkov run on every Terraform change and in CI, and block on any finding; every module declares its Terraform and provider versions. checkov reads `.checkov.yaml`, which skips only the rules below. The repository owner accepted them on Sep 28 2026 for this synthetic-data portfolio stack, and the lint-settings check blocks any addition to the list. The IAM wildcard rules now cover only the KMS key policy.

| Rule | Reason accepted |
| --- | --- |
| `CKV2_AWS_11` | VPC flow logs are not kept for the short-lived demo network; cost. |
| `CKV2_AWS_20` | No HTTPS listener to redirect to (see CKV_AWS_2). |
| `CKV2_AWS_28` | WAF is not used for the allow-listed synthetic-data HAPI endpoint; cost outweighs benefit. |
| `CKV2_AWS_30` | PostgreSQL query logging is not kept for the demo databases. |
| `CKV2_AWS_5` | Task security groups are attached at run time by ECS RunTask, which the scan cannot see. |
| `CKV2_AWS_51` | API Gateway uses IAM and shared-secret authentication instead of client certificates. |
| `CKV2_AWS_60` | Snapshot tag copying is not needed; final snapshots are skipped in demo teardown. |
| `CKV2_AWS_61` | The data bucket keeps objects until teardown; a lifecycle policy is a documented follow-up in the data governance guide. |
| `CKV2_AWS_62` | S3 event notifications are not used by the pipeline. |
| `CKV_AWS_103` | Same load balancers have no HTTPS listener to set a TLS policy on (see CKV_AWS_2). |
| `CKV_AWS_109` | Same KMS key policy as CKV_AWS_356: the account root statement is the standard key-administration grant. |
| `CKV_AWS_111` | Same KMS key policy as CKV_AWS_356. |
| `CKV_AWS_115` | Reserved concurrency is not set so the demo can scale with the stream. |
| `CKV_AWS_116` | Failures use the Kinesis and SQS failure destinations and replay queue instead of Lambda DLQs. |
| `CKV_AWS_117` | Lambdas call only AWS APIs and need no VPC placement. |
| `CKV_AWS_118` | Enhanced monitoring is not needed for the demo databases. |
| `CKV_AWS_119` | DynamoDB uses AWS-owned encryption; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_129` | RDS log exports are not kept for the demo databases; cost. |
| `CKV_AWS_131` | Header-dropping is not needed for the allow-listed HAPI and internal Marquez load balancers. |
| `CKV_AWS_136` | ECR uses AES-256 encryption; customer-managed keys add cost without benefit. |
| `CKV_AWS_144` | Cross-region replication is not needed for the rebuildable demo data. |
| `CKV_AWS_145` | S3 buckets use SSE-S3; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_150` | Load balancer deletion protection would block the guarded demo teardown. |
| `CKV_AWS_157` | Single-AZ RDS is enough for the short-lived demo; Multi-AZ doubles cost. |
| `CKV_AWS_158` | Log groups use AWS-managed encryption; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_161` | HAPI and Marquez authenticate with RDS-managed secrets, not IAM database authentication. |
| `CKV_AWS_173` | Lambda environment variables hold names only, no secrets; the webhook secret stays in Secrets Manager. |
| `CKV_AWS_18` | S3 server access logging is not kept for the demo; CloudTrail covers API access. |
| `CKV_AWS_195` | The Glue job writes to an SSE-S3 encrypted bucket; a separate Glue security configuration is not used. |
| `CKV_AWS_2` | HAPI load balancer serves HTTP; access is limited to the NAT gateway and operator addresses, and there is no project domain for a certificate. |
| `CKV_AWS_272` | Lambda code signing is not used; packages are built reproducibly in CI. |
| `CKV_AWS_293` | Deletion protection is driven by allow_destructive_teardown so the guarded teardown can remove databases. |
| `CKV_AWS_309` | Webhook routes authenticate with the shared-secret header and WebSocket $disconnect cannot carry authorization. |
| `CKV_AWS_336` | The simulator writes working files at run time; a read-only root file system is a follow-up. |
| `CKV_AWS_338` | Logs are kept 14 days to control cost for the synthetic demo. |
| `CKV_AWS_353` | Performance Insights is not needed for the demo databases. |
| `CKV_AWS_356` | Only the alerts KMS key policy is flagged: in a key policy, Resource "*" means the key itself. After the IAM review of Sep 29 2026, workload role statements name their resources except `ecr:GetAuthorizationToken`, which AWS allows only on "*", and `cloudwatch:PutMetricData`, limited by a namespace condition. The Glue role also keeps the AWS managed `AWSGlueServiceRole` policy, which is broader; replacing it is a follow-up. |
| `CKV_AWS_378` | Same HTTP listener decision as CKV_AWS_2; the Marquez listener is internal and reached only through IAM-authorized API Gateway. |
| `CKV_AWS_382` | Private tasks need outbound access through the NAT gateway to AWS APIs, ECR, PhysioNet and HAPI. |
| `CKV_AWS_394` | Availability zones are chosen by index; the demo does not need pinned zone IDs. |
| `CKV_AWS_50` | X-Ray tracing is not enabled for the demo Lambdas; CloudWatch metrics and logs cover them. |
| `CKV_AWS_91` | Load balancer access logs are not kept for the synthetic demo; cost. |
