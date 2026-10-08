---
title: "Deployment Guide"
description: "Configure accounts, publish deployment inputs and verify managed services."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Deployment Guide

For developers and operators: configure accounts, publish deployment inputs and verify managed services.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [GitHub OIDC Bootstrap](#github-oidc-bootstrap)
- [Protected GitHub Environment](#protected-github-environment)
- [Shared OpenLineage Collector](#shared-openlineage-collector)
- [Pause and Restore the Managed Collector](#pause-and-restore-the-managed-collector)
- [Configure an External Collector](#configure-an-external-collector)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **IAM**: Identity and Access Management.
- **MWAA**: Managed Workflows for Apache Airflow.
- **OIDC**: OpenID Connect.
- **RDS**: Relational Database Service.
- **URL**: uniform resource locator.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<GITHUB_OWNER>`: github owner for the selected environment or example.
- `<HTTPS_BASE_URL>`: https base url for the selected environment or example.
- `<OWNER_ID>`: owner id for the selected environment or example.
- `<PROJECT_NAME>`: project name for the selected environment or example.
- `<REPOSITORY>`: repository for the selected environment or example.
- `<REPOSITORY_ID>`: repository id for the selected environment or example.
- `{namespace}`: URL-encoded namespace name returned by Marquez, preserving the API specification's route notation.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## GitHub OIDC Bootstrap

GitHub deployment uses short-lived AWS credentials. It does not store AWS access keys in GitHub.

Prerequisites:

- A completed first local deployment and authenticated GitHub and AWS sessions.
- Repository administration access and a protected deployment environment.
- A selected private environment file and approval for the exact bootstrap plan.

1. Read the repository's OIDC subject configuration:

   ```zsh
   gh api repos/<GITHUB_OWNER>/<REPOSITORY>/actions/oidc/customization/sub
   ```

   Copy `sub_claim_prefix` into `GITHUB_OIDC_SUBJECT_PREFIX` in the next step. When `use_immutable_subject` is enabled, the prefix contains numeric owner and repository IDs. Using it prevents a renamed or recreated repository from inheriting deployment access. Leave the variable empty only when GitHub reports the default mutable subject without a custom prefix.

2. Configure these settings in the selected private environment file:

   ```dotenv
   ENABLE_GITHUB_OIDC=true
   GITHUB_REPOSITORY=<GITHUB_OWNER>/<REPOSITORY>
   GITHUB_OIDC_SUBJECT_PREFIX=repo:<GITHUB_OWNER>@<OWNER_ID>/<REPOSITORY>@<REPOSITORY_ID>
   GITHUB_DEPLOYMENT_ENVIRONMENT=development
   ```

3. Render the inputs and create a saved bootstrap plan:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   ./scripts/infrastructure/render_project_config.sh --check
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-oidc
   terraform -chdir=infra show -no-color tfplan-oidc
   ```

   Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

   The renderer supplies the project's existing service-policy names to Terraform. The deployment role attaches those policies directly, stays within the default quota of 20 managed policies per role and does not create a duplicate deployment policy. If the AWS account already contains the GitHub OIDC provider, import it into this state before applying rather than creating a duplicate.

4. Apply only the reviewed and approved action:

   ```zsh
   terraform -chdir=infra apply tfplan-oidc
   terraform -chdir=infra output -raw github_deployment_role_arn
   ```

5. Verify that the deployment role exists and its trust policy accepts only the configured repository and protected GitHub deployment environment. Keep the returned role identifier private.

## Protected GitHub Environment

Prerequisites:

- A bootstrapped deployment role and immutable images from the project build process.
- Repository administration access and approval to configure environment protections and secrets.
- One protected environment per deployment environment, each pointing at its own AWS account; see the [environments guide](environments.md).

1. Create the GitHub environment named by `github_deployment_environment`. Restrict it to `main` and require approval for deployment.
2. Configure this non-sensitive environment variable:

   | Name | Value |
   | --- | --- |
   | `AWS_REGION` | Target AWS region |

3. Add these environment secrets:

   | Name | Value |
   | --- | --- |
   | `AWS_DEPLOY_ROLE_ARN` | Terraform `github_deployment_role_arn` output |
   | `TF_STATE_BUCKET` | Dedicated persistent state bucket created by `infra/bootstrap` |
   | `TF_STATE_PREFIX` | `<PROJECT_NAME>/terraform` |

4. Synchronize the generated private configuration from the selected `${PROJECT_ENV_FILE:-.env}` file into encrypted, versioned AWS storage:

   ```zsh
   ./scripts/infrastructure/sync_deployment_config.sh
   ```

   The object is stored under `$TF_STATE_PREFIX/config/` in the persistent state bucket. `TF_STATE_PREFIX` must equal `<PROJECT_NAME>/terraform`; the synchronization and prerequisite scripts enforce that relationship. The Deploy workflow authenticates through GitHub OIDC before retrieving it and uses the single `AWS_REGION` environment variable for both Terraform state and application resources. The bucket and prefix remain protected secrets because this public portfolio treats deployment identifiers as private; redacted plan diagnostics preserve useful errors without exposing those identifiers. Do not create a bulk `TERRAFORM_VARIABLES_JSON` GitHub secret and do not expose account-specific identifiers as GitHub variables.

5. Create and inspect a full local plan without publishing private identifiers:

   ```zsh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-deploy-review
   terraform -chdir=infra show -no-color tfplan-deploy-review
   ```

6. Run the **Deploy** workflow manually with the protected environment and `action=plan`. Review its resource-address/action summary and redacted diagnostics.
7. Obtain approval for the exact deployment changes before running the workflow with `action=apply`. The apply run creates a fresh saved plan, applies that plan and verifies convergence.
8. Confirm both workflow runs succeeded and the apply convergence check reports no remaining changes. Remote deployment is ready only when the protected environment and role restrictions also match the intended account.

## Shared OpenLineage Collector

The managed collector runs Marquez on private Elastic Container Service (ECS) and PostgreSQL Relational Database Service (RDS) resources. An internal load balancer is reachable only through an Identity and Access Management (IAM)-authorized application programming interface (API) Gateway endpoint, so no custom domain or public Marquez port is required. S3 remains the fallback when the collector is disabled.

The Marquez repository and image are part of the standard deployment: `bootstrap.sh repositories-plan` creates the Marquez Elastic Container Registry (ECR) repository with the other four and `push_images.sh` builds and pushes the pinned Marquez image with the same immutable tag, recording it as `OPENLINEAGE_COLLECTOR_IMAGE_TAG` in the selected `${PROJECT_ENV_FILE:-.env}` file ([quickstart](quickstart.md) step 3). No separate build is needed. The Grafana image is built the same way: `push_images.sh` renders the dashboards for Athena and records `GRAFANA_IMAGE_TAG`. Grafana runs only when `ENABLE_GRAFANA=true`; it has no public endpoint and is reached through an AWS Systems Manager (SSM) port forward, checked by `e2e.aws_grafana`.

Prerequisites:

- The standard immutable Marquez image and the selected environment's deployed backend.
- Approval for the exact collector plan before applying it.
- An analytical workflow ready to produce lineage events.

1. Set these values in the selected `${PROJECT_ENV_FILE:-.env}` file:

   ```dotenv
   ENABLE_OPENLINEAGE_COLLECTOR=true
   OPENLINEAGE_COLLECTOR_DESIRED_COUNT=1
   ```

2. Render the ignored Terraform inputs. Do not edit generated files directly:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   ```

3. Synchronize the configuration when using the GitHub Deploy workflow:

   ```zsh
   ./scripts/infrastructure/sync_deployment_config.sh
   ```

4. Create and inspect a full saved collector plan:

   ```zsh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-collector
   terraform -chdir=infra show -no-color tfplan-collector
   ```

   The plan creates Marquez ECS, encrypted RDS, an internal load balancer and the IAM-authorized API route. It also updates Glue, Managed Workflows for Apache Airflow (MWAA), dbt and Soda with the collector URL and route-specific `execute-api:Invoke` permission. Obtain approval for the exact changes and stop on unexpected deletion, replacement or permission changes.

5. Apply only the reviewed and approved plan:

   ```zsh
   terraform -chdir=infra apply tfplan-collector
   ```

6. Run the analytical workflow and query the collector with the project's SigV4 session:

   ```zsh
   export OPENLINEAGE_URL="$(terraform -chdir=infra output -raw openlineage_collector_url)"

   .venv/bin/python - <<'PY'
   import os
   import sys

   import boto3
   from botocore.auth import SigV4Auth
   from botocore.awsrequest import AWSRequest
   from botocore.httpsession import URLLib3Session

   url = f'{os.environ["OPENLINEAGE_URL"].rstrip("/")}/api/v1/namespaces'
   region = os.environ["AWS_REGION"]
   credentials = boto3.Session().get_credentials()
   if credentials is None:
       raise SystemExit("AWS credentials are required")
   request = AWSRequest(method="GET", url=url)
   SigV4Auth(credentials.get_frozen_credentials(), "execute-api", region).add_auth(request)
   response = URLLib3Session().send(request.prepare())
   if response.status_code >= 400:
       raise SystemExit(f"Collector returned HTTP {response.status_code}")
   sys.stdout.write(response.content.decode() + "\n")
   PY
   ```

7. Confirm the namespace query succeeds. Inspect each expected namespace's jobs through the same authorized session at `/api/v1/namespaces/{namespace}/jobs` and verify the workflow jobs appear. The [Marquez API specification](https://github.com/MarquezProject/marquez/blob/main/spec/openapi.yml) defines that read route.

## Pause and Restore the Managed Collector

Prerequisites:

- An inactive analytical workflow and approval for the exact pause or restore changes.
- Access to the selected environment's Marquez RDS instance.

1. Set `OPENLINEAGE_COLLECTOR_DESIRED_COUNT=0` in the selected private environment file.
2. Render and inspect a saved pause plan:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-collector-pause
   terraform -chdir=infra show -no-color tfplan-collector-pause
   ```

3. Obtain approval for its exact changes and apply that plan:

   ```zsh
   terraform -chdir=infra apply tfplan-collector-pause
   ```

4. Stop the selected Marquez RDS instance through AWS after approval for that operation. Verify the instance is stopped and Marquez has zero running tasks. AWS automatically restarts a stopped RDS instance after seven days; see [RDS stop behavior](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html).
5. Restore the database before the next pipeline run. Set the desired count to `1` and repeat the reviewed collector activation procedure. Confirm the database and collector are available before sending lineage events.

## Configure an External Collector

Prerequisites:

- An approved externally managed collector URL and access policy.
- Approval for the exact deployment changes.

1. Set these values in the selected private environment file:

   ```dotenv
   ENABLE_OPENLINEAGE_COLLECTOR=false
   EXTERNAL_OPENLINEAGE_COLLECTOR_URL=<HTTPS_BASE_URL>
   ```

2. Render the ignored inputs:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   ```

3. Follow the reviewed plan/apply procedure in [Protected GitHub Environment](#protected-github-environment) or the [quickstart](quickstart.md) for a local deployment. Confirm the analytical workflow delivers events to the approved collector.

`.env.example` lists this override as a commented reference because a standard deployment creates the managed collector or uses the durable S3 fallback. Every non-local remote collector request is SigV4-signed for `execute-api`. Unsigned development transport is supported only for a local endpoint.
