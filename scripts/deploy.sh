#!/usr/bin/env bash
# Bootstrap deploy: CloudFormation stack + Docker push + App Runner.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${AWS_REGION:-us-west-2}"
STACK="${STACK_NAME:?Set STACK_NAME}"
DOMAIN="${DOMAIN_NAME:?Set DOMAIN_NAME}"
ZONE_ID="${HOSTED_ZONE_ID:?Set HOSTED_ZONE_ID}"
ECR_REPO="${ECR_REPOSITORY_NAME:?Set ECR_REPOSITORY_NAME}"
TEMPLATE="$ROOT/infra/cloudformation/template.yaml"
IMAGE_TAG="${IMAGE_TAG:-latest}"

BASE_PARAMS=(
  "HostedZoneId=$ZONE_ID"
  "DomainName=$DOMAIN"
  "EcrRepositoryName=$ECR_REPO"
  "ImageTag=$IMAGE_TAG"
)

cd "$ROOT"

stack_output() {
  aws cloudformation describe-stacks \
    --region "$REGION" \
    --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" \
    --output text 2>/dev/null || true
}

stack_param() {
  aws cloudformation describe-stacks \
    --region "$REGION" \
    --stack-name "$STACK" \
    --query "Stacks[0].Parameters[?ParameterKey=='$1'].ParameterValue | [0]" \
    --output text 2>/dev/null || true
}

if [[ "${PUSH_ONLY:-}" == "1" ]]; then
  REPO_URI="$(stack_output EcrRepositoryUri)"
  if [[ -z "$REPO_URI" || "$REPO_URI" == "None" ]]; then
    echo "ERROR: stack $STACK not found — run full deploy first"
    exit 1
  fi
else
  SERVICE_ARN="$(stack_output AppRunnerServiceArn)"
  DNS_TARGET="$(stack_param AppRunnerCustomDomainDnsTarget)"

  if [[ -z "$SERVICE_ARN" || "$SERVICE_ARN" == "None" ]]; then
    echo "==> Phase 1: stack (ECR, IAM, secrets) — DeployAppRunner=false"
    aws cloudformation deploy \
      --region "$REGION" \
      --stack-name "$STACK" \
      --template-file "$TEMPLATE" \
      --parameter-overrides "${BASE_PARAMS[@]}" "DeployAppRunner=false" \
      --capabilities CAPABILITY_NAMED_IAM \
      --no-fail-on-empty-changeset
  else
    echo "==> App Runner already deployed — keeping service on stack update"
    EXTRA=()
    if [[ -n "$DNS_TARGET" && "$DNS_TARGET" != "None" ]]; then
      EXTRA+=("AppRunnerCustomDomainDnsTarget=$DNS_TARGET")
    fi
    aws cloudformation deploy \
      --region "$REGION" \
      --stack-name "$STACK" \
      --template-file "$TEMPLATE" \
      --parameter-overrides "${BASE_PARAMS[@]}" "DeployAppRunner=true" "${EXTRA[@]}" \
      --capabilities CAPABILITY_NAMED_IAM \
      --no-fail-on-empty-changeset
  fi

  REPO_URI="$(stack_output EcrRepositoryUri)"
  SECRET_ARN="$(stack_output DataConnectionSecretArn)"
  if [[ -n "$SECRET_ARN" && "$SECRET_ARN" != "None" ]]; then
    echo ""
    echo "Set MongoDB + Elasticsearch in Secrets Manager before going live:"
    echo "  aws secretsmanager put-secret-value --secret-id $SECRET_ARN --secret-string '{\"mongoUri\":\"...\",\"elasticsearchUrl\":\"...\",\"mongoDb\":\"http_validator\"}'"
    echo ""
  fi
fi

echo "==> ECR login"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${REPO_URI%%/*}"

echo "==> Docker build & push ($REPO_URI:$IMAGE_TAG)"
docker build -t "$REPO_URI:$IMAGE_TAG" .
docker push "$REPO_URI:$IMAGE_TAG"

if [[ "${PUSH_ONLY:-}" == "1" ]]; then
  echo "==> Push only — App Runner auto-deploys :latest"
  exit 0
fi

SERVICE_ARN="$(stack_output AppRunnerServiceArn)"
if [[ -n "$SERVICE_ARN" && "$SERVICE_ARN" != "None" ]]; then
  echo "==> App Runner already enabled"
else
  echo "==> Phase 2: enable App Runner"
  EXTRA_PARAMS=()
  if [[ -n "${APP_RUNNER_DNS_TARGET:-}" ]]; then
    EXTRA_PARAMS+=("AppRunnerCustomDomainDnsTarget=$APP_RUNNER_DNS_TARGET")
  fi

  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK" \
    --template-file "$TEMPLATE" \
    --parameter-overrides "${BASE_PARAMS[@]}" "DeployAppRunner=true" "${EXTRA_PARAMS[@]}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset
fi

echo ""
echo "==> Stack outputs"
aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs" \
  --output table

SERVICE_URL="$(stack_output AppRunnerServiceUrl)"
if [[ -n "$SERVICE_URL" && "$SERVICE_URL" != "None" ]]; then
  echo ""
  echo "App Runner URL: $SERVICE_URL"
  echo "Next: ./scripts/ensure-custom-domain.sh"
fi