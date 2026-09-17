# Externally Managed Prerequisites

These prerequisites are intentionally outside the main application Terraform state. Record their owners and recovery procedures privately; never commit their real identifiers or values.

| Prerequisite | Why it is external | Required for recreation | Teardown behavior |
| --- | --- | --- | --- |
| Bootstrap AWS identity | Terraform cannot create the identity whose credentials create the first resources | Grant the documented project-policy actions to a temporary administrator or deployment group | Remove or disable separately after verifying no other workload uses it |
| Customer-managed deployment policies | Existing account policies are shared by the local deployment identity and GitHub role | Render the tracked templates under `infra/iam/policies/`, create/update the policies and attach them through the account's approved group model | Not removed by application Terraform |
| Persistent Terraform state bucket | The main stack cannot safely manage the bucket containing its own state | Create once with `infra/bootstrap`; run the guarded bootstrap-state backup | Survives application teardown by design |
| FHIR webhook secret | Secret values must not enter Terraform plans or tracked configuration | Create `healthcare-realtime/fhir-webhook` with JSON key `FHIR_WEBHOOK_SECRET` | Delete separately only after HAPI subscriptions and the application are gone |
| GitHub repository environment | Repository approvals and encrypted settings belong to GitHub | Configure `AWS_REGION` as non-sensitive configuration and store `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET` and `TF_STATE_PREFIX` as protected secrets | Remove separately if the repository is retired |
| Private deployment configuration | Account-specific Terraform inputs must remain outside public GitHub configuration | Enter them once in `.env`, render the ignored Terraform JSON and synchronize it to the encrypted, versioned `<project-name>/terraform/config/` state-bucket prefix | Remove with the persistent state bucket only after all environments are retired |
| GitHub OIDC provider | One provider may be shared by several repositories in an AWS account | Import an existing provider or allow the initial local deployment to create it | Do not delete while another repository uses it |
| Alert-email confirmation | AWS cannot confirm the recipient's mailbox | Confirm the SNS subscription from the target mailbox | Subscription disappears with the application topic; mailbox confirmation is not reproducible by code |
| Local build toolchain | Containers, Synthea, packages and Terraform run outside AWS | Install Python 3.12, Terraform 1.11+, AWS CLI, Docker, Java 17, Git, GitHub CLI and jq | No AWS teardown action |
| External datasets and tools | PhysioNet source access, Postman and optional Power BI are not provisioned by Terraform | Confirm network access and install only the tools needed for the selected workflow | No AWS teardown action |
| AWS quotas and service availability | Account quotas and regional availability cannot be guaranteed by this repository | Check VPC, Elastic IP, Fargate, RDS, MWAA Serverless and managed-policy quotas before deployment | Quota increases remain on the account |

The policy JSON files are reproducible policy definitions, not Terraform-managed IAM identities. Plan all templates without changing AWS:

```zsh
.venv/bin/python infra/iam/scripts/manage_policies.py plan \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

Apply the reviewed create and update actions only from an approved bootstrap identity:

```zsh
CONFIRM_IAM_POLICIES=apply-healthcare-realtime-policies \
  .venv/bin/python infra/iam/scripts/manage_policies.py apply \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

The command obtains the account ID from STS, uses `TF_STATE_BUCKET` from `.env`, creates missing policies and publishes a new default version only when an existing document changed. It never creates users or groups and never attaches policies to an identity. Removing a template does not delete its deployed customer-managed policy; review and delete obsolete policies separately after confirming that no identity still uses them.

The policy command reads project inputs from `.env` and the generated Terraform JSON. Explicit `--profile` and `--region` arguments select the authenticated AWS session without changing generated project configuration.

Copy `.env.example` to the ignored `.env`, complete its placeholders and run `./scripts/infrastructure/render_project_config.sh`. Infrastructure and demo scripts treat `.env` as authoritative. The renderer creates both ignored Terraform JSON files, so the same value is never entered twice. Verify every automatable prerequisite without displaying secret values:

```zsh
./scripts/infrastructure/check_prerequisites.sh pre-deploy
```

After the full application deployment and GitHub environment setup, run `./scripts/infrastructure/check_prerequisites.sh post-deploy`. GitHub does not permit reading encrypted secret values back through its API, so this local check confirms their names only. The Deploy workflow validates the role, state bucket and state prefix by using them after OIDC authentication without printing them. Mailbox confirmation, account quota increases, PhysioNet availability, Postman installation and optional Power BI installation require human or account-owner action.
