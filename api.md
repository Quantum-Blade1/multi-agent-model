# API And Keys Reference

## Purpose

This file lists:

- external APIs and cloud services used by the project
- internal HTTP APIs exposed by the app
- credentials, API keys, and environment variables required to run the system

## External Services

| Service | Used For | Required | Key Or Credential |
|---|---|---|---|
| AWS Bedrock Runtime | LLM inference through Claude | Yes | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_MODEL_ID` or ECS task role |
| AWS Bedrock Control Plane | `/health` Bedrock availability check | Yes | Same AWS credentials as Bedrock Runtime |
| AWS DynamoDB | Audit records, rule engine, feedback, calibration report storage | Yes for full backend | Same AWS credentials as above |
| AWS S3 | Index watcher and index swap downloads | Optional unless hot-swap is enabled | Same AWS credentials as above |
| RBI public website | Circular scraping in ingestion pipeline | Optional, ingestion only | No API key required |
| Hugging Face model download | First-time download of sentence-transformer weights | Optional after model cache is warm | No API key required; `HF_TOKEN` is optional for higher rate limits |

## Internal HTTP APIs

| Method | Path Prefix | Purpose | Auth Requirement |
|---|---|---|---|
| `GET` | `/health` | Liveness and subsystem status | None |
| `GET` | `/ready` | Readiness gate | None |
| `POST` | `/ai/process` | Single compliance decision | None by default |
| `POST` | `/ai/process/batch` | Batch compliance decisions | None by default |
| `GET/POST` | `/audit/*` | Audit retrieval, override, chain verification | `REVIEWER_API_KEY` required for protected write paths |
| `GET/PUT/POST` | `/rules/*` | Rule read, update, reset | `REVIEWER_API_KEY` required for protected write paths |
| `GET/POST` | `/feedback/*` | Reviewer feedback and summary | `REVIEWER_API_KEY` required for protected write paths |
| `GET/POST` | `/calibration/*` | Calibration run, history, health | `REVIEWER_API_KEY` required for protected write paths |

## Minimum Credentials For Local Run

If you want to run the API with real model access, you need:

```env
AWS_REGION=ap-south-1
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
AWS_ACCESS_KEY_ID=your-local-access-key
AWS_SECRET_ACCESS_KEY=your-local-secret-key
```

If you run on ECS or another AWS-managed environment, use an IAM role instead of static keys.

## Backend Keys And Env Vars

| Variable | Required | What It Controls |
|---|---|---|
| `AWS_REGION` | Yes | Region for Bedrock, DynamoDB, and S3 clients |
| `BEDROCK_MODEL_ID` | Yes | Claude model used by the decision agent |
| `AWS_ACCESS_KEY_ID` | Local only | AWS authentication for local development |
| `AWS_SECRET_ACCESS_KEY` | Local only | AWS authentication for local development |
| `REVIEWER_API_KEY` | Recommended | Protects override, rule-update, feedback, and calibration admin endpoints |
| `COMPLIANCE_RULES_TABLE` | Optional | DynamoDB table for active rules |
| `COMPLIANCE_CHANGELOG_TABLE` | Optional | DynamoDB table for rule changelog |
| `FEEDBACK_TABLE` | Optional | DynamoDB table for reviewer feedback |
| `CALIBRATION_REPORTS_TABLE` | Optional | DynamoDB table for calibration reports |
| `AUDIT_RECORDS_TABLE` | Optional | DynamoDB table for audit records |
| `AUDIT_CHAIN_TABLE` | Optional | DynamoDB table for audit chain metadata |
| `AUDIT_SEQUENCE_TABLE` | Optional | DynamoDB table for audit sequencing |
| `INDEX_S3_BUCKET` | Optional | S3 bucket for index watcher and hot-swap downloads |
| `INDEX_WATCH_PREFIX` | Optional | S3 prefix for manifest polling |
| `INDEX_LOCAL_CACHE_DIR` | Optional | Local cache location for downloaded indexes |
| `INDEX_MASTER_PATH` | Optional | Local path to primary FAISS index |
| `INDEX_UPDATED_PATH` | Optional | Local path to updated FAISS index |
| `INDEX_DIR` | Optional | Base directory for FAISS artifacts used by ingestion |
| `MASTER_INDEX_NAME` | Optional | Primary index file base name |
| `UPDATED_INDEX_NAME` | Optional | Updated index file base name |
| `CORS_ORIGINS` | Optional | Allowed browser origins |
| `APP_VERSION` | Optional | Version returned by health endpoints |
| `ENV` | Optional | Controls docs exposure |
| `ENVIRONMENT` | Optional | Environment label for metrics and runtime behavior |
| `LOG_LEVEL` | Optional | Application logging level |

## Recommended `.env` For Local Development

```env
APP_VERSION=1.0.0
ENVIRONMENT=development
ENV=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000

AWS_REGION=ap-south-1
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
AWS_ACCESS_KEY_ID=replace-me
AWS_SECRET_ACCESS_KEY=replace-me

REVIEWER_API_KEY=replace-with-a-long-random-string

INDEX_DIR=ingestion/data/indexes/
MASTER_INDEX_NAME=master_index
UPDATED_INDEX_NAME=updated_index
INDEX_MASTER_PATH=ingestion/data/indexes/master_index
INDEX_UPDATED_PATH=ingestion/data/indexes/updated_index

COMPLIANCE_RULES_TABLE=nbfc-compliance-rules
COMPLIANCE_CHANGELOG_TABLE=nbfc-rule-changelog
FEEDBACK_TABLE=nbfc-feedback
CALIBRATION_REPORTS_TABLE=nbfc-calibration-reports
AUDIT_RECORDS_TABLE=nbfc-audit-records
AUDIT_CHAIN_TABLE=nbfc-audit-chain
AUDIT_SEQUENCE_TABLE=nbfc-audit-sequence

INDEX_S3_BUCKET=nbfc-compliance-indexes
INDEX_WATCH_PREFIX=indexes/
INDEX_LOCAL_CACHE_DIR=/tmp/faiss_cache/
```

## What Is Actually Required

For a minimal local API boot:

- AWS credentials or an attached IAM role
- `AWS_REGION`
- `BEDROCK_MODEL_ID`
- local FAISS index files at `INDEX_MASTER_PATH`

For full production behavior:

- all of the above
- DynamoDB tables for audit, rules, feedback, and calibration
- `REVIEWER_API_KEY`
- S3 bucket and manifest path if index hot-swap is enabled

## Notes

- The RBI scraper does not require an API key.
- Hugging Face access is optional. The embedding model can be downloaded anonymously, but `HF_TOKEN` may reduce rate-limit issues during first-time setup.
- If `REVIEWER_API_KEY` is unset, protected admin routes may be effectively unprotected depending on deployment behavior. Set it explicitly in every non-test environment.
