---
title: "Quality Checks"
description: "Configure repository hooks and understand their enforcement and verification limits."
last_updated: 2026-10-02
audience: [developer, operator]
---

# Quality Checks

For developers and operators: configure repository hooks and understand their enforcement and verification limits.

Every commit runs the hooks in `.pre-commit-config.yaml` through `.githooks/` and continuous integration (CI) runs the same hooks on every push and pull request in pre-commit's `manual` stage, where the only difference is the documentation review (see below). A finding names the file and line, the policy below and how to fix it. There are no bypasses: do not use `SKIP=` or `git commit --no-verify`. If a policy blocks a valid change, fix the check or raise the policy with the repository owner before committing.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Setup](#setup)
- [Secrets and Credential Files](#secrets-and-credential-files)
- [Personal Data and Environment Values](#personal-data-and-environment-values)
- [Data Files](#data-files)
- [Commit Messages](#commit-messages)
- [Documentation Matches the Code](#documentation-matches-the-code)
- [Documentation Review](#documentation-review)
- [Lint and Type Settings](#lint-and-type-settings)
- [SQL](#sql)
- [Process Launcher](#process-launcher)
- [Terraform](#terraform)
- [Writing Preferences](#writing-preferences)
- [Document Metadata](#document-metadata)
- [Markdown Syntax](#markdown-syntax)
- [Documentation Preparation](#documentation-preparation)

## Terminology

- **API**: application programming interface.
- **ARN**: Amazon Resource Name.
- **AWS**: Amazon Web Services.
- **CI**: continuous integration.
- **E2E**: end-to-end.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **HTML**: HyperText Markup Language.
- **HTTP**: HyperText Transfer Protocol.
- **HTTPS**: HyperText Transfer Protocol Secure.
- **IAM**: Identity and Access Management.
- **KMS**: Key Management Service.
- **NAT**: network address translation.
- **PNG**: Portable Network Graphics.
- **RDS**: Relational Database Service.
- **SHA**: Secure Hash Algorithm.
- **SQL**: Structured Query Language.
- **SQS**: Simple Queue Service.
- **TLS**: Transport Layer Security.
- **US**: United States.
- **VPC**: virtual private cloud.
- **WAF**: web application firewall.
- **YAML**: YAML Ain't Markup Language.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<NAME>`: name for the selected environment or example.
- `<REASON>`: reason for the selected environment or example.
- `<REVIEWED_AT>`: review time in ISO 8601 UTC timestamp format, such as `2026-10-02T16:00:00Z`.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Setup

1. Run the following command block:

   ```zsh
   .venv/bin/python -m pip install -r requirements_dev.txt
   ```

2. Install the isolated pinned tools after owner approval:

   ```zsh
   .venv/bin/python -m tools.install_tools
   ```

3. Select the repository hooks:

   ```zsh
   git config core.hooksPath .githooks
   ```

   `tools/install_tools.py` installs pinned gitleaks and tflint binaries after verifying their Secure Hash Algorithm (SHA)-256 checksums and pinned checkov and SQLFluff releases in their own virtual environments under the ignored `.tools/` folder. It also installs the locked Markdown checker in its isolated npm folder, without lifecycle scripts. SQLFluff's environment also holds dbt-core and dbt-athena at the versions the dbt image uses; they stay out of `.venv` because dbt-athena's `pyathena` range conflicts with the project pin.

   Run every hook across the repository:

4. Run the following command block:

   ```zsh
   .venv/bin/pre-commit run --all-files
   ```

   The checks live in the `tools/` package. They are verified end to end by `tools/test_checks.py`, which runs each hook through `pre-commit` in a scratch repository, rather than by the pytest suite. A bad sample counts as blocked only when the output cites the reason declared for it, so a check that fails for an unrelated cause cannot pass. Prove that each check blocks a bad sample and passes a good one:

5. Run the following command block:

   ```zsh
   .venv/bin/python -m tools.test_checks
   ```

## Secrets and Credential Files

### QLT-1. Secrets and Credential Files

Secrets and credential files MUST stay outside Git.

Why: Credential exposure can compromise the account and its data.

- Do: store the webhook value in Secrets Manager.
- Don't: stage an environment file containing a credential.

gitleaks scans staged changes on commit and the full Git history in CI. Environment files other than `.env.example`, Terraform state and state backups, private keys and cloud credential files are blocked by name. Store secrets in AWS Secrets Manager and keep private deployment values in the ignored `.env`.

## Personal Data and Environment Values

### QLT-2. Personal Data and Environment Values

Shareable files MUST pass the privacy scan and binary review.

Why: The text scanner cannot certify unreadable artifacts or public deployment identifiers.

- Do: review scanner findings and unreadable images before sharing.
- Don't: treat a clean text scan as review of a binary.

The privacy scan reads every tracked and untracked, non-ignored file on each commit and the tracked tree in CI, for home-directory paths with a user name, machine temporary paths, email addresses outside reserved example domains (`example.com`, `.invalid` and similar), phone numbers, AWS account IDs and ARNs and any value that the local `.env` declares for a profile, bucket, account, Amazon Resource Name (ARN), endpoint, host, email or user. The project's own name is public: a `.env` value equal to `PROJECT_NAME` or to its leading name segments with `-` or `_`, is not reported, because resource names and the AWS profile follow that naming standard. Longer values such as a bucket named after the project are still checked. Findings name the file, line and type, never the value. Files it cannot read as text, such as the architecture Portable Network Graphics (PNG), are listed as unreviewed and need a person's check before publishing.

Replace a finding with a placeholder or read it from configuration. A value that is meant to be public gets an entry in `.privacy_allowlist`: `<type> <path glob> -- <REASON>`, matched by type and path, never by value. Before publishing, also scan ignored and hidden files:

1. Run the following command block:

   ```zsh
   .venv/bin/python -m tools.repo_checks privacy-scan --all
   ```

## Data Files

### QLT-3. Data Files

Data files MUST use the declared folders and size limits.

Why: Repository checks preserve the declared storage boundary.

- Do: keep local run evidence under the ignored artifact path.
- Don't: add a data file outside the declared folders.

Data files (`.csv`, `.tsv`, `.parquet`, `.xlsx`, `.xls`, `.jsonl`, `.ndjson`, `.avro`, `.db`, `.sqlite`) are allowed only in the declared folders `dbt/seeds/` and `tests/fixtures/`, which hold synthetic data only. Any file over 5 MB is blocked unless Git LFS stores it. Never commit real personal data.

## Commit Messages

### QLT-4. Commit Messages

Commit messages MUST follow Conventional Commits and contain no agent attribution.

Why: Stored messages form the public project history.

- Do: use `docs(readme): clarify setup`.
- Don't: add an agent credit trailer.

Subjects follow Conventional Commits: `<type>(<scope>): <description>` with the types `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `style` and `revert`. Messages carry no AI credit, generated-with line or agent-session trailer. Human co-authors and factual mentions of tools are allowed. The commit-msg hook checks each new message; CI checks every stored message in the pushed range.

## Documentation Matches the Code

### QLT-5. Documentation Matches the Code

Documentation MUST match the tracked commands, flags and configuration.

Why: Stale instructions can fail or affect an unintended environment.

- Do: update a command when its supported flag changes.
- Don't: retain a removed flag in an operator example.

Every environment variable the Python code reads is listed in `.env.example`, either as a local input or as a commented reference line. When a script, command-line flag or environment variable is removed, the documentation that names it must change in the same commit.

## Documentation Review

### QLT-6. Documentation Review

Every commit MUST have a complete fresh local review of every document against the staged snapshot.

Why: A passing syntax check does not establish factual accuracy.

- Do: review the exact staged snapshot and keep its record local.
- Don't: reuse a record after changing the staged files.

Before every commit, every document in the repository is reviewed against the staged code, configuration and decisions and the outcome is recorded in the local, ignored `.documentation_review.json`, which is never committed. The check discovers `README`, `LICENSE`, Markdown, HyperText Markup Language (HTML) and other document formats and every file under `docs/`; requirements files and version pins are not documents. It blocks a commit when the record is missing, tracked or not ignored, a document is unreviewed, any staged file changed after the review or new documentation is untracked. It reads the record from the working tree and the documents from the Git index and checks the evidence, not the truth of the notes. CI has no local record: its `documentation-review-untracked` hook verifies only that the record stays out of Git and does not claim the review was done.

1. Stage the intended changes by name.
2. Draft the local record with the declared reviewer and review time:

   ```zsh
   .venv/bin/python -m tools.documentation_review prepare --reviewer "<NAME>" --reviewed-at "<REVIEWED_AT>" --refresh
   ```

3. Read every listed document against the staged change. Correct stale content, then set each `outcome` to `current`, `updated` or `historical` with a note on what was checked. Historical records such as release notes keep their original content.
4. Commit without staging the record. If you stage anything else afterwards, repeat from step 2.

## Lint and Type Settings

### QLT-7. Lint and Type Settings

Lint and type settings MUST retain the enforced baseline; suppression comments MUST satisfy the approved exception.

Why: Reducing checks can hide defects without fixing them.

- Do: fix the finding at its source.
- Don't: add a blanket suppression.

Ruff keeps line length 160 and at least the rule families `E`, `F`, `I`, `B`, `UP`, `SIM`, `T20` (no `print`: command-line scripts write to `sys.stdout`, services log through `logging`) and `S` (security), with no ignore or exclude settings. Athena cannot bind table names as query parameters, so queries that name tables check every name against an identifier pattern and fill a `string.Template`, never an f-string. MyPy settings may only get stricter and its exclude list may not grow. Suppression comments are blocked except the one approved exception below; fix the code instead. Tests check results with `testkit.expect` (`equal`, `is_in`, `identical`, `fail` and related helpers) instead of `assert`, which Python removes under `-O`; write a condition that narrows a type as an `if` that calls `expect.fail`.

| Rule | Allowed only in | Condition |
| --- | --- | --- |
| Ruff `S603` | `tools/process.py` | Full executable path, list arguments, no shell, stdin closed and a timeout, with the reason on the line |

## SQL

### QLT-8. SQL

SQL lint MUST run through the offline project runner with the declared dialect and templater.

Why: The runner prevents lint from using a real cloud identity.

- Do: use `tools.lint_sql` with its offline configuration.
- Don't: run lint with a real AWS profile.

SQLFluff lints every dbt model and singular test with the dbt templater and the Athena dialect, using the settings in `.sqlfluff`: lowercase keywords, functions, literals and types, four-space indentation, trailing commas and line length 160. `tools/lint_sql.py` runs it with fixed placeholder deployment names, so the result never depends on a local `.env`. The dbt templater normally lists the Glue catalog before compiling; `tools/sqlfluff_offline.py` turns that off and the runner removes any AWS profile and supplies placeholder credentials, so linting never reaches AWS and any attempt fails instead of using a real login. Run SQLFluff only through this runner. The lint-settings check keeps the templater, dialect and line length and blocks any setting that narrows the rules; SQL `noqa` comments are blocked like Python suppressions.

1. Run the following command block:

   ```zsh
   .venv/bin/python -m tools.lint_sql          # report
   .venv/bin/python -m tools.lint_sql --fix    # apply SQLFluff's layout fixes, then review the diff
   ```

## Process Launcher

### QLT-9. Process Launcher

Python subprocess calls MUST use the project launcher.

Why: The launcher controls executable paths, arguments and timeouts.

- Do: call `run_command` with a full executable path.
- Don't: import `subprocess` in a service.

All Python code starts programs through `run_command` in `tools/process.py`, including the dbt and Soda container wrappers, whose images copy the launcher. The subprocess-imports check blocks any other `subprocess` import.

## Terraform

### QLT-10. Terraform

Terraform changes MUST pass formatting, lint and security checks with only the approved exceptions.

Why: Unreviewed infrastructure settings can broaden access or leave billable resources.

- Do: retain the approved checkov exception list.
- Don't: add an unreviewed skip.

`terraform fmt`, tflint and checkov run on every Terraform change and in CI and block on any finding; every module declares its Terraform and provider versions. checkov reads `.checkov.yaml`, which skips only the rules below. The repository owner accepted them on Sep 28 2026 for this synthetic-data portfolio stack and the lint-settings check blocks any addition to the list. The Identity and Access Management (IAM) wildcard rules now cover only the Key Management Service (KMS) key policy.

| Rule | Reason accepted |
| --- | --- |
| `CKV2_AWS_11` | virtual private cloud (VPC) flow logs are not kept for the short-lived demo network; cost. |
| `CKV2_AWS_20` | No HyperText Transfer Protocol Secure (HTTPS) listener to redirect to (see CKV_AWS_2). |
| `CKV2_AWS_28` | web application firewall (WAF) is not used for the allow-listed synthetic-data HAPI endpoint; cost outweighs benefit. |
| `CKV2_AWS_30` | PostgreSQL query logging is not kept for the demo databases. |
| `CKV2_AWS_5` | Task security groups are attached at run time by Elastic Container Service (ECS) RunTask, which the scan cannot see. |
| `CKV2_AWS_51` | application programming interface (API) Gateway uses IAM and shared-secret authentication instead of client certificates. |
| `CKV2_AWS_60` | Snapshot tag copying is not needed; final snapshots are skipped in demo teardown. |
| `CKV2_AWS_61` | The data bucket keeps objects until teardown; a lifecycle policy is a documented follow-up in the data governance guide. |
| `CKV2_AWS_62` | S3 event notifications are not used by the pipeline. |
| `CKV_AWS_103` | Same load balancers have no HTTPS listener to set a Transport Layer Security (TLS) policy on (see CKV_AWS_2). |
| `CKV_AWS_109` | Same KMS key policy as CKV_AWS_356: the account root statement is the standard key-administration grant. |
| `CKV_AWS_111` | Same KMS key policy as CKV_AWS_356. |
| `CKV_AWS_115` | Reserved concurrency is not set so the demo can scale with the stream. |
| `CKV_AWS_116` | Failures use the Kinesis and Simple Queue Service (SQS) failure destinations and replay queue instead of Lambda DLQs. |
| `CKV_AWS_117` | Lambdas call only AWS APIs and need no VPC placement. |
| `CKV_AWS_118` | Enhanced monitoring is not needed for the demo databases. |
| `CKV_AWS_119` | DynamoDB uses AWS-owned encryption; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_129` | Relational Database Service (RDS) log exports are not kept for the demo databases; cost. |
| `CKV_AWS_131` | Header-dropping is not needed for the allow-listed HAPI and internal Marquez load balancers. |
| `CKV_AWS_136` | Elastic Container Registry (ECR) uses AES-256 encryption; customer-managed keys add cost without benefit. |
| `CKV_AWS_144` | Cross-region replication is not needed for the rebuildable demo data. |
| `CKV_AWS_145` | S3 buckets use SSE-S3; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_150` | Load balancer deletion protection would block the guarded demo teardown. |
| `CKV_AWS_157` | Single-AZ RDS is enough for the short-lived demo; Multi-AZ doubles cost. |
| `CKV_AWS_158` | Log groups use AWS-managed encryption; customer-managed keys add cost without benefit for synthetic data. |
| `CKV_AWS_161` | HAPI and Marquez authenticate with RDS-managed secrets, not IAM database authentication. |
| `CKV_AWS_173` | Lambda environment variables hold names only, no secrets; the webhook secret stays in Secrets Manager. |
| `CKV_AWS_18` | S3 server access logging is not kept for the demo; CloudTrail covers API access. |
| `CKV_AWS_195` | The Glue job writes to an SSE-S3 encrypted bucket; a separate Glue security configuration is not used. |
| `CKV_AWS_2` | HAPI load balancer serves HyperText Transfer Protocol (HTTP); access is limited to the network address translation (NAT) gateway and there is no project domain for a certificate. |
| `CKV_AWS_272` | Lambda code signing is not used; packages are built reproducibly in CI. |
| `CKV_AWS_293` | Deletion protection is driven by allow_destructive_teardown so the guarded teardown can remove databases. |
| `CKV_AWS_309` | Webhook routes authenticate with the shared-secret header and WebSocket $disconnect cannot carry authorization. |
| `CKV_AWS_336` | The simulator writes working files at run time; a read-only root file system is a follow-up. |
| `CKV_AWS_338` | Logs are kept 14 days to control cost for the synthetic demo. |
| `CKV_AWS_353` | Performance Insights is not needed for the demo databases. |
| `CKV_AWS_356` | Only the alerts KMS key policy is flagged: in a key policy, Resource "*" means the key itself. After the IAM review of Sep 29 2026, workload role statements name their resources except `ecr:GetAuthorizationToken`, which AWS allows only on "*" and `cloudwatch:PutMetricData`, limited by a namespace condition. The Glue job role has its own scoped permissions instead of the AWS managed `AWSGlueServiceRole` policy. |
| `CKV_AWS_378` | Same HTTP listener decision as CKV_AWS_2; the Marquez listener is internal and reached only through IAM-authorized API Gateway. |
| `CKV_AWS_382` | Private tasks need outbound access through the NAT gateway to AWS APIs, ECR, PhysioNet and HAPI. |
| `CKV_AWS_394` | Availability zones are chosen by index; the demo does not need pinned zone IDs. |
| `CKV_AWS_50` | X-Ray tracing is not enabled for the demo Lambdas; CloudWatch metrics and logs cover them. |
| `CKV_AWS_91` | Load balancer access logs are not kept for the synthetic demo; cost. |

## Writing Preferences

### QLT-11. Writing Preferences

Markdown prose MUST follow the writing policy; allowlist exceptions MUST state their reason.

Why: Consistent prose makes instructions easier to review and use.

- Do: state a version-specific fact with its source.
- Don't: use a time-bound word without a version.

Markdown prose omits commas before the final conjunction, uses United States (US) English and APA Title Case headings and states facts without time-bound words. Code, metadata and historical evidence keep their required syntax. The writing hook blocks findings; `--warn` is reserved for explicit preparation diagnostics. Exceptions in `.writing_allowlist` require a type, path glob and reason.

## Document Metadata

### QLT-12. Document Metadata

In-scope guides MUST have valid metadata matching their title and last meaningful change.

Why: Metadata identifies a document and the scope of its review.

- Do: match `title` to the H1 and use a real calendar date.
- Don't: use a timestamp for `last_updated`.

Markdown guides carry YAML Ain't Markup Language (YAML) metadata with a title equal to the H1, a one-sentence description of at most 120 characters and a valid `last_updated` calendar date. Update that date when meaning changes. README files, conventional governance files and GitHub templates retain their tool conventions. Metadata validation blocks malformed documents.

## Markdown Syntax

### QLT-13. Markdown Syntax

Markdown MUST pass the pinned syntax checker.

Why: Predictable syntax keeps repository renderings readable.

- Do: run the locked checker from `.tools/markdownlint-cli2/`.
- Don't: treat syntax lint as proof of factual accuracy.

The Markdown hook uses markdownlint-cli2 0.23.3, pinned with integrity hashes in `tools/markdownlint/package-lock.json`. Node.js 22 or later runs it; the isolated installer uses `npm ci --ignore-scripts` under `.tools/markdownlint-cli2/`. The hook runs in both local pre-commit and CI's manual stage. end-to-end (E2E) evidence under `artifacts/e2e/` remains local and ignored. Syntax checks do not prove factual accuracy or complete document compliance.

## Documentation Preparation

The documentation migration is preparation for review, not a claim of adoption. Preserve established filenames and use no hard wrapping. Diagram assets remain in `docs/architecture/`; the index records authoritative documents. Complete manual review of procedures, terminology, decisions, links and example behavior before adopting the document format. The real hooks require the pinned Markdown tool; install it only with owner approval. The metadata and prose checks complement syntax lint. Preparation records separate automated results, factual review and remaining adoption gates.
