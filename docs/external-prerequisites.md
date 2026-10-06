---
title: "Externally Managed Prerequisites"
description: "Identify account resources maintained outside application Terraform."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Externally Managed Prerequisites

For developers and operators: identify account resources maintained outside application Terraform.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Prerequisite Inventory](#prerequisite-inventory)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **CLI**: command-line interface.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **ID**: identifier.
- **IP**: Internet Protocol.
- **JSON**: JavaScript Object Notation.
- **KMS**: Key Management Service.
- **MWAA**: Managed Workflows for Apache Airflow.
- **OIDC**: OpenID Connect.
- **RDS**: Relational Database Service.
- **SNS**: Simple Notification Service.
- **STS**: Security Token Service.
- **VPC**: virtual private cloud.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<PROJECT_NAME>`: project name for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Prerequisite Inventory

These prerequisites are intentionally outside the main application Terraform state. Record their owners and recovery procedures privately; never commit their real identifiers or values.

| Prerequisite | Why it is external | Required for recreation | Teardown behavior |
| --- | --- | --- | --- |
| Bootstrap AWS identity | Terraform cannot create the identity whose credentials create the first resources | Grant the documented project-policy actions to a temporary administrator or deployment group | Remove or disable separately after verifying no other workload uses it |
| Customer-managed deployment policies | Existing account policies are shared by the local deployment identity and GitHub role | Render the tracked templates under `infra/iam/policies/`, create/update the policies and attach them through the account's approved group model | Not removed by application Terraform |
| Persistent Terraform state bucket | The main stack cannot safely manage the bucket containing its own state | Create once with `infra/bootstrap`; run the guarded bootstrap-state backup | Survives routine application teardown. Retirement requires all environments to be destroyed and the reviewed archive to be retained or explicitly declined; follow the [state-retirement scope](infrastructure-lifecycle.md#full-account-retirement). |
| Fast Healthcare Interoperability Resources (FHIR) webhook secret | Secret values must not enter Terraform plans or tracked configuration | Create the secret named by `FHIR_WEBHOOK_SECRET_ID` with the JavaScript Object Notation (JSON) key named by `FHIR_WEBHOOK_SECRET_KEY` | Delete separately only after HAPI subscriptions and the application are gone |
| GitHub repository environment | Repository approvals and encrypted settings belong to GitHub | Configure `AWS_REGION` as non-sensitive configuration and store `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET` and `TF_STATE_PREFIX` as protected secrets | Remove separately if the repository is retired |
| Private deployment configuration | Account-specific Terraform inputs must remain outside public GitHub configuration | Enter them once in the selected `${PROJECT_ENV_FILE:-.env}` file, render the ignored Terraform JSON and synchronize it to the encrypted, versioned `<PROJECT_NAME>/terraform/config/` state-bucket prefix | Remove with the persistent state bucket only after all environments are retired |
| GitHub OpenID Connect (OIDC) provider | One provider may be shared by several repositories in an AWS account | Import an existing provider or allow the initial local deployment to create it | Do not delete while another repository uses it |
| Alert-email confirmation | AWS cannot confirm the recipient's mailbox | Confirm the Simple Notification Service (SNS) subscription from the target mailbox | Subscription disappears with the application topic; mailbox confirmation is not reproducible by code |
| Local build toolchain | Containers, Synthea, packages and Terraform run outside AWS | Install Python 3.12, Terraform 1.11+, AWS command-line interface (CLI), Docker, Java 17, Git, GitHub CLI and jq | No AWS teardown action |
| External datasets and tools | PhysioNet source access, Postman and optional Power BI are not provisioned by Terraform | Confirm network access and install only the tools needed for the selected workflow | No AWS teardown action |
| AWS quotas and service availability | Account quotas and regional availability cannot be guaranteed by this repository | Check virtual private cloud (VPC), Elastic Internet Protocol (IP), Fargate, Relational Database Service (RDS), Managed Workflows for Apache Airflow (MWAA) Serverless and managed-policy quotas before deployment | Quota increases remain on the account |

The policy JSON files are reproducible policy definitions, not Terraform-managed Identity and Access Management (IAM) identities. Plan all templates without changing AWS:

1. Run the following command block:

   ```zsh
   .venv/bin/python infra/iam/scripts/manage_policies.py plan \
     --profile "$AWS_PROFILE" \
     --region "$AWS_REGION"
   ```

2. Review the policy plan and obtain approval for its exact create and update actions. Use only an approved bootstrap identity. Stop on unexpected deletion, replacement or permission changes.

3. Apply only the reviewed and approved action:

   ```zsh
   CONFIRM_IAM_POLICIES=apply-healthcare-realtime-policies \
     .venv/bin/python infra/iam/scripts/manage_policies.py apply \
     --profile "$AWS_PROFILE" \
     --region "$AWS_REGION"
   ```

   The command obtains the account identifier (ID) from Security Token Service (STS), uses `TF_STATE_BUCKET` from the selected `${PROJECT_ENV_FILE:-.env}` file, creates missing policies and publishes a new default version only when an existing document changed. It never creates users or groups and never attaches policies to an identity. Confirm attachment separately for the bootstrap user, group or role before Terraform deployment. Removing a template does not delete its deployed customer-managed policy; review and delete obsolete policies separately after confirming that no identity still uses them.

   The policy command reads project inputs from the selected `${PROJECT_ENV_FILE:-.env}` file and the generated Terraform JSON. Explicit `--profile` and `--region` arguments select the authenticated AWS session without changing generated project configuration. Tag-scoped permissions, including Key Management Service (KMS) key creation and management, use the rendered `PROJECT_NAME`; publish a new policy version whenever that project name changes.

   Every create, change and delete action names project resources: project name prefixes, the configured databases, streams and Athena workgroup or a project tag condition. `Resource: "*"` remains only for account-wide list and describe calls, actions AWS allows only on `*` (such as `ecr:GetAuthorizationToken` and `kms:CreateKey`), actions limited by a condition instead (Elastic Container Service (ECS) task listing by cluster, event source mappings by project function) and the EC2 network and interface statements. Those EC2 statements still need tag conditions that can only be proven on a real deployment. A scope that is too narrow shows up as an `AccessDenied` in the Terraform plan or apply; widen only the named resource, never back to `*`.

   Create the ignored file selected by `${PROJECT_ENV_FILE:-.env}` from `.env.example` only if it does not exist. Complete its placeholders and run `./scripts/infrastructure/render_project_config.sh`. Infrastructure and demo scripts treat the selected file as authoritative. The renderer creates both ignored Terraform JSON files, so the same value is never entered twice. Verify every automatable prerequisite without displaying secret values:

4. Run the following command block:

   ```zsh
   ./scripts/infrastructure/check_prerequisites.sh pre-deploy
   ```

   After the full application deployment and GitHub environment setup, run `./scripts/infrastructure/check_prerequisites.sh post-deploy`. GitHub does not permit reading encrypted secret values back through its application programming interface (API), so this local check confirms their names only. The Deploy workflow validates the role, state bucket and state prefix by using them after OIDC authentication without printing them. Mailbox confirmation, account quota increases, PhysioNet availability, Postman installation and optional Power BI installation require human or account-owner action.
