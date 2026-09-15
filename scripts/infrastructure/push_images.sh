#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$REPO_ROOT/infra"
IMAGE_TAG="${IMAGE_TAG:-sha-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

if [[ -z "$AWS_REGION" ]]; then
  echo "Set AWS_REGION before publishing images." >&2
  exit 2
fi

if [[ ! "$IMAGE_TAG" =~ ^sha-[a-zA-Z0-9._-]+$ ]]; then
  echo "IMAGE_TAG must start with sha-." >&2
  exit 2
fi

simulator_url="$(terraform -chdir="$INFRA_DIR" output -raw vitals_simulator_ecr_repository_url)"
dbt_url="$(terraform -chdir="$INFRA_DIR" output -raw dbt_ecr_repository_url)"
soda_url="$(terraform -chdir="$INFRA_DIR" output -raw soda_ecr_repository_url)"
marquez_url="$(terraform -chdir="$INFRA_DIR" output -raw openlineage_collector_ecr_repository_url)"
registry="${simulator_url%%/*}"

for repository in "$simulator_url" "$dbt_url" "$soda_url" "$marquez_url"; do
  if image_check="$(aws ecr describe-images --region "$AWS_REGION" --repository-name "${repository##*/}" --image-ids imageTag="$IMAGE_TAG" 2>&1)"; then
    echo "Refusing to overwrite existing image ${repository##*/}:$IMAGE_TAG." >&2
    exit 2
  fi

  if [[ "$image_check" != *"ImageNotFoundException"* ]]; then
    echo "Unable to verify image tag availability for ${repository##*/}: $image_check" >&2
    exit 2
  fi
done

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry"

docker buildx build --platform linux/amd64 --file "$REPO_ROOT/services/vitals_simulator/Dockerfile" --tag "$simulator_url:$IMAGE_TAG" --push "$REPO_ROOT"
docker buildx build --platform linux/amd64 --file "$REPO_ROOT/deploy/dbt/Dockerfile" --tag "$dbt_url:$IMAGE_TAG" --push "$REPO_ROOT"
docker buildx build --platform linux/amd64 --file "$REPO_ROOT/deploy/soda/Dockerfile" --tag "$soda_url:$IMAGE_TAG" --push "$REPO_ROOT"
docker buildx build --platform linux/amd64 --file "$REPO_ROOT/deploy/marquez/Dockerfile" --tag "$marquez_url:$IMAGE_TAG" --push "$REPO_ROOT/deploy/marquez"

printf '\nSet these ignored Terraform inputs:\n'
printf 'vitals_simulator_image_tag = "%s"\n' "$IMAGE_TAG"
printf 'dbt_image_tag              = "%s"\n' "$IMAGE_TAG"
printf 'soda_image_tag             = "%s"\n' "$IMAGE_TAG"
printf 'openlineage_collector_image_tag = "%s"\n' "$IMAGE_TAG"
