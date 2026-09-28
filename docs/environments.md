# Environments

The project has two deployment environments, each in its own AWS account:

| Environment | `DEPLOYMENT_ENVIRONMENT` | Environment file | Purpose |
| --- | --- | --- | --- |
| Development | `development` (default when unset) | `.env` | Demos, E2E runs and changes under test; torn down after each demo |
| Production | `production` | `.env.production` | The reviewed release deployment |

Separate accounts keep the environments apart without renaming resources: the Terraform resource names are fixed per project, so two environments in one account would collide. Each account has its own Terraform state bucket, bootstrap state, webhook secret, IAM policies and GitHub environment.

## Select an environment

Every script reads the environment file named by `PROJECT_ENV_FILE`, or `.env` when it is unset. Both files are ignored by Git. Select production for a whole shell session:

```zsh
export PROJECT_ENV_FILE=.env.production
set -a
source "$PROJECT_ENV_FILE"
set +a
```

The production file holds the production account's `AWS_PROFILE`, `AWS_ACCOUNT_ID`, `TF_STATE_BUCKET`, `DATA_BUCKET_NAME` and alert address, plus:

```dotenv
DEPLOYMENT_ENVIRONMENT=production
FHIR_RESOURCE_MAP_FILE=scripts/synthea_loader/state/production/fhir_resource_map.json
```

`FHIR_RESOURCE_MAP_FILE` keeps each environment's HAPI patient IDs apart, because every HAPI server assigns its own IDs.

## Safeguards

- `render_project_config.sh` renders the ignored Terraform inputs from the selected file only.
- `infra/bootstrap` keeps each environment's local state in its own Terraform workspace: `default` for development and `production` for production.
- Every plan names the rendered variable file explicitly with `-var-file=deployment.auto.tfvars.json`, in the scripts, the Deploy workflow and the documented commands.
- Saved plans carry the environment in their names, for example `tfplan-bootstrap-application-production`, so a plan from one environment is never applied in another.
- Before any main-stack plan, apply, teardown or demo command, the scripts stop if `infra/` is initialized for a different state bucket than the selected file names. Run `./scripts/infrastructure/bootstrap.sh main-init` after switching environments.
- `check_prerequisites.sh` fails when the signed-in AWS account differs from `AWS_ACCOUNT_ID` in the selected file.
- Teardown asks for `CONFIRM_TEARDOWN=delete-healthcare-realtime-<environment>`, so deleting production needs its own confirmation.

## Create production

Follow the [first-deployment quickstart](quickstart.md) in the production account with `PROJECT_ENV_FILE=.env.production` exported for the whole session. Then configure a protected GitHub environment named by `GITHUB_DEPLOYMENT_ENVIRONMENT` in the production file, with its own `AWS_REGION` variable and `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET` and `TF_STATE_PREFIX` secrets, as described in the [deployment guide](deployment.md). The Deploy workflow's environment input selects the account through those secrets.

Resources named with the environment, such as queues, alarms and dashboards, use `production` in the production account; other names are identical in both accounts.
