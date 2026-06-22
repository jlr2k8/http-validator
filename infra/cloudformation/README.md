# http-validator — AWS deployment

Same pattern as `chess-jrog-io` and `chat-jrog-io`:

| Stack | File | Purpose |
|-------|------|---------|
| App | `template.yaml` | ECR, App Runner, Secrets Manager (Mongo/ES URIs), Route53 |
| Pipeline | `pipeline.yaml` | GitHub → CodeBuild → ECR → App Runner auto-deploy |

## One-time bootstrap

```bash
export AWS_REGION=us-west-2
export STACK_NAME=http-validator
export DOMAIN_NAME=validator.jrog.io
export HOSTED_ZONE_ID=Z3FQ1J6D2XJRDT
export ECR_REPOSITORY_NAME=http-validator

./scripts/deploy.sh
# Set mongoUri + elasticsearchUrl in Secrets Manager (see deploy.sh output)
./scripts/ensure-custom-domain.sh
export GITHUB_TOKEN=...
./scripts/deploy-pipeline.sh
```

## Day-to-day

Push to `main` → CodePipeline builds Docker image → App Runner redeploys.

## Local dev

`docker-compose up -d` runs MongoDB + Elasticsearch locally. Crawl with `python3 link_validator.py …`. UI via `./scripts/dev.sh` (Vite dev server + API).