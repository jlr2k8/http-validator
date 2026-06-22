#!/usr/bin/env bash
# Deploy CodePipeline + CodeBuild for http-validator (GitHub main → ECR → App Runner auto-deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${AWS_REGION:-us-west-2}"
PIPELINE_STACK="${PIPELINE_STACK_NAME:-http-validator-pipeline}"
APP_STACK="${APP_STACK_NAME:-http-validator}"
TEMPLATE="$ROOT/infra/cloudformation/pipeline.yaml"

GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
SECRET_NAME="${GITHUB_TOKEN_SECRET:-chat-jrog-io/github-token}"

cd "$ROOT"

GITHUB_OWNER="${GITHUB_OWNER:-jlr2k8}"
GITHUB_REPO="${GITHUB_REPO:-http-validator}"
echo "==> GitHub repo: $GITHUB_OWNER/$GITHUB_REPO"

ECR_REPO="$(aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$APP_STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='EcrRepositoryName'].ParameterValue | [0]" \
  --output text 2>/dev/null || true)"

if [[ -z "$ECR_REPO" || "$ECR_REPO" == "None" ]]; then
  ECR_REPO="${ECR_REPOSITORY_NAME:-http-validator}"
fi
echo "    EcrRepositoryName=$ECR_REPO"

DOMAIN="${DOMAIN_NAME:-validator.jrog.io}"
ZONE_ID="${HOSTED_ZONE_ID:-Z3FQ1J6D2XJRDT}"
echo "    DomainName=$DOMAIN"
echo "    HostedZoneId=$ZONE_ID"

echo "==> GitHub token"
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  echo "    from GITHUB_TOKEN"
elif aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" &>/dev/null; then
  GITHUB_TOKEN="$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --region "$REGION" \
    --query SecretString \
    --output text 2>/dev/null || true)"
  if [[ -n "$GITHUB_TOKEN" ]]; then
    echo "    from Secrets Manager: $SECRET_NAME"
  fi
fi

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "Error: no GitHub token. Export GITHUB_TOKEN or create Secrets Manager secret: $SECRET_NAME"
  exit 1
fi

PARAMS=(
  "GitHubOwner=$GITHUB_OWNER"
  "GitHubRepo=$GITHUB_REPO"
  "GitHubBranch=$GITHUB_BRANCH"
  "GitHubToken=$GITHUB_TOKEN"
  "EcrRepositoryName=$ECR_REPO"
  "AppStackName=$APP_STACK"
  "DomainName=$DOMAIN"
  "HostedZoneId=$ZONE_ID"
)

echo ""
echo "Pipeline stack: $PIPELINE_STACK"
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$PIPELINE_STACK" \
  --template-file "$TEMPLATE" \
  --parameter-overrides "${PARAMS[@]}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset

echo ""
aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$PIPELINE_STACK" \
  --query "Stacks[0].Outputs" \
  --output table

echo ""
echo "Push to main on https://github.com/$GITHUB_OWNER/$GITHUB_REPO to deploy."