# Externally Managed Prerequisites

These prerequisites are intentionally outside the main application Terraform state. Record their owners and recovery procedures privately; never commit their real identifiers or values.

| Prerequisite | Why it is external | Required for recreation | Teardown behavior |
| --- | --- | --- | --- |
| Bootstrap AWS identity | Terraform cannot create the identity whose credentials create the first resources | Grant the documented project-policy actions to a temporary administrator or deployment group | Remove or disable separately after verifying no other workload uses it |
| Customer-managed deployment policies | Existing account policies are shared by the local deployment identity and GitHub role | Render the tracked templates under `infra/iam/policies/`, create/update the policies, and attach them through the account's approved group model | Not removed by application Terraform |
| Persistent Terraform state bucket | The main stack cannot safely manage the bucket containing its own state | Create once with `infra/bootstrap`; run the guarded bootstrap-state backup | Survives application teardown by design |
| FHIR webhook secret | Secret values must not enter Terraform plans or tracked configuration | Create `healthcare-realtime/fhir-webhook` with JSON key `FHIR_WEBHOOK_SECRET` | Delete separately only after HAPI subscriptions and the application are gone |
| GitHub repository environment | Repository approvals and encrypted settings belong to GitHub | Configure `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `TF_STATE_BUCKET`, and `TERRAFORM_VARIABLES_JSON` | Remove separately if the repository is retired |
| GitHub OIDC provider | One provider may be shared by several repositories in an AWS account | Import an existing provider or allow the initial local deployment to create it | Do not delete while another repository uses it |
| Alert-email confirmation | AWS cannot confirm the recipient's mailbox | Confirm the SNS subscription from the target mailbox | Subscription disappears with the application topic; mailbox confirmation is not reproducible by code |
| Local build toolchain | Containers, Synthea, packages, and Terraform run outside AWS | Install Python 3.12, Terraform 1.11+, AWS CLI, Docker, Java 17, Git, GitHub CLI, and jq | No AWS teardown action |
| External datasets and tools | PhysioNet source access, Postman, and optional Power BI are not provisioned by Terraform | Confirm network access and install only the tools needed for the selected workflow | No AWS teardown action |
| AWS quotas and service availability | Account quotas and regional availability cannot be guaranteed by this repository | Check VPC, Elastic IP, Fargate, RDS, MWAA Serverless, and managed-policy quotas before deployment | Quota increases remain on the account |

The policy JSON files are reproducible policy definitions, not Terraform-managed IAM identities. Supply the ignored Terraform variable file so resource identifiers come from the same configuration used by the stack; only account and state-bucket identifiers remain external:

```zsh
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
.venv/bin/python infra/iam/scripts/render_policy.py \
  infra/iam/policies/<policy-name>.json \
  --terraform-var-file infra/development.tfvars \
  --output /tmp/<policy-name>.json
```

Set `TF_STATE_BUCKET` only when rendering the S3 policy, then review the rendered JSON before updating an existing policy version.

Copy `.env.example` to the ignored `.env` and complete its placeholders. Infrastructure and demo scripts load missing values from that file while preserving explicit shell overrides. Verify every automatable prerequisite without displaying secret values:

```zsh
./scripts/infrastructure/check_prerequisites.sh
```

Mailbox confirmation, account quota increases, PhysioNet availability, Postman installation, and optional Power BI installation require human or account-owner action. The preflight verifies the deployed SNS confirmation and service access that can be checked safely.
