---
title: "Deployment Guide"
description: "Deploy from one local checkout and verify managed services."
last_updated: 2026-10-08
audience: [developer, operator]
---

# Deployment Guide

For developers and operators: deploy from one local checkout and verify managed services.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Where Deployments Run](#where-deployments-run)
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
- **RDS**: Relational Database Service.
- **URL**: uniform resource locator.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<HTTPS_BASE_URL>`: https base url for the selected environment or example.
- `{namespace}`: URL-encoded namespace name returned by Marquez, preserving the API specification's route notation.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Where Deployments Run

Every deployment runs from one local checkout with the [quickstart](quickstart.md) and the selected `${PROJECT_ENV_FILE:-.env}` file. Terraform keeps the state in that checkout only. Teardown removes it ([local Terraform state](infrastructure-lifecycle.md#local-terraform-state)). There is no GitHub deployment workflow or GitHub deployment role: a workflow run would need state shared outside the checkout. Deployments are short-lived demos, torn down after each demo.

## Shared OpenLineage Collector

The managed collector runs Marquez on private Elastic Container Service (ECS) and PostgreSQL Relational Database Service (RDS) resources. An internal load balancer is reachable only through an Identity and Access Management (IAM)-authorized application programming interface (API) Gateway endpoint, so no custom domain or public Marquez port is required. S3 remains the fallback when the collector is disabled.

The Marquez repository and image are part of the standard deployment: `bootstrap.sh repositories-plan` creates the Marquez Elastic Container Registry (ECR) repository with the other four and `push_images.sh` builds and pushes the pinned Marquez image with the same immutable tag, recording it as `OPENLINEAGE_COLLECTOR_IMAGE_TAG` in the selected `${PROJECT_ENV_FILE:-.env}` file ([quickstart](quickstart.md) step 3). No separate build is needed. The Grafana image is built the same way: `push_images.sh` renders the dashboards for Athena and records `GRAFANA_IMAGE_TAG`. Grafana runs only when `ENABLE_GRAFANA=true`; it has no public endpoint and is reached through an AWS Systems Manager (SSM) port forward ([Grafana on AWS](operations-runbook.md#grafana-on-aws)), checked by `e2e.aws_grafana`.

Prerequisites:

- The standard immutable Marquez image and the selected environment's deployed application stack.
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

3. Create and inspect a full saved collector plan:

   ```zsh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-collector
   terraform -chdir=infra show -no-color tfplan-collector
   ```

   The plan creates Marquez ECS, encrypted RDS, an internal load balancer and the IAM-authorized API route. It also updates Glue, Managed Workflows for Apache Airflow (MWAA), dbt and Soda with the collector URL and route-specific `execute-api:Invoke` permission. Obtain approval for the exact changes and stop on unexpected deletion, replacement or permission changes.

4. Apply only the reviewed and approved plan:

   ```zsh
   terraform -chdir=infra apply tfplan-collector
   ```

5. Run the analytical workflow and query the collector with the project's SigV4 session:

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

6. Confirm the namespace query succeeds. Inspect each expected namespace's jobs through the same authorized session at `/api/v1/namespaces/{namespace}/jobs` and verify the workflow jobs appear. The [Marquez API specification](https://github.com/MarquezProject/marquez/blob/main/spec/openapi.yml) defines that read route.

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

3. Follow the reviewed plan/apply procedure in the [quickstart](quickstart.md). Confirm the analytical workflow delivers events to the approved collector.

`.env.example` lists this override as a commented reference because a standard deployment creates the managed collector or uses the durable S3 fallback. Every non-local remote collector request is SigV4-signed for `execute-api`. Unsigned development transport is supported only for a local endpoint.
