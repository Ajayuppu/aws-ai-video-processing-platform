#!/usr/bin/env bash
# Optional CLI cleanup for the AI video processing platform.
# Deletes everything the guide created, in dependency-safe order.
# Usage:  bash scripts/cleanup.sh config.env        (run in CloudShell, us-east-1)
# Every step ignores "not found" errors, so it is safe to re-run.
set -uo pipefail

CONFIG="${1:-config.env}"
# shellcheck disable=SC1090
source "$CONFIG"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""

SFN_ARN="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:video-ai-pipeline"
LAMBDAS=(video-start-job video-update-status video-caption-frame video-summarize)
ROLES=(video-start-job-role video-update-status-role video-caption-frame-role video-summarize-role
       video-pipeline-sfn-role video-processor-execution-role video-processor-task-role video-appsync-jobs-role)

echo "This will DELETE the AI video platform in account ${ACCOUNT_ID} (${REGION}) and bucket ${BUCKET}."
read -r -p "Type 'delete' to continue: " answer
[ "$answer" = "delete" ] || { echo "Aborted."; exit 1; }

step() { echo; echo "== $*"; }

step "1. Stop new uploads from starting jobs (EventBridge rule)"
TARGET_IDS=$(aws events list-targets-by-rule --rule video-uploaded-rule --query 'Targets[].Id' --output text 2>/dev/null)
# shellcheck disable=SC2086
[ -n "$TARGET_IDS" ] && aws events remove-targets --rule video-uploaded-rule --ids $TARGET_IDS >/dev/null
aws events delete-rule --name video-uploaded-rule 2>/dev/null

step "2. Remove the SQS -> Lambda trigger"
for uuid in $(aws lambda list-event-source-mappings --function-name video-start-job --query 'EventSourceMappings[].UUID' --output text 2>/dev/null); do
  aws lambda delete-event-source-mapping --uuid "$uuid" >/dev/null
done

step "3. Stop running executions and delete the state machine"
for exec_arn in $(aws stepfunctions list-executions --state-machine-arn "$SFN_ARN" --status-filter RUNNING --query 'executions[].executionArn' --output text 2>/dev/null); do
  aws stepfunctions stop-execution --execution-arn "$exec_arn" >/dev/null
done
aws stepfunctions delete-state-machine --state-machine-arn "$SFN_ARN" 2>/dev/null
# Fargate tasks started by a stopped execution may still be running; stop them.
for task in $(aws ecs list-tasks --cluster video-ai-cluster --query 'taskArns[]' --output text 2>/dev/null); do
  aws ecs stop-task --cluster video-ai-cluster --task "$task" >/dev/null
done

step "4. Delete the Lambda functions and their log groups"
for fn in "${LAMBDAS[@]}"; do
  aws lambda delete-function --function-name "$fn" 2>/dev/null
  aws logs delete-log-group --log-group-name "/aws/lambda/${fn}" 2>/dev/null
done

step "5. Delete the SQS queues"
for q in video-jobs-queue video-jobs-dlq; do
  url=$(aws sqs get-queue-url --queue-name "$q" --query QueueUrl --output text 2>/dev/null) && aws sqs delete-queue --queue-url "$url"
done

step "6. Delete the AppSync API"
API_ID="${APPSYNC_API_ID:-}"
[ -n "$API_ID" ] && aws appsync delete-graphql-api --api-id "$API_ID" 2>/dev/null

step "7. Remove the failure-test object uploads/bad.mp4 and any FAILED VideoJobs items"
aws s3 rm "s3://${BUCKET}/uploads/bad.mp4" 2>/dev/null
for id in $(aws dynamodb scan --table-name VideoJobs --filter-expression '#s = :f' \
    --expression-attribute-names '{"#s":"status"}' \
    --expression-attribute-values '{":f":{"S":"FAILED"}}' \
    --query 'Items[].jobId.S' --output text 2>/dev/null); do
  [ -n "$id" ] && aws dynamodb delete-item --table-name VideoJobs --key "{\"jobId\":{\"S\":\"$id\"}}"
done

step "8. Delete the DynamoDB table"
aws dynamodb delete-table --table-name VideoJobs >/dev/null 2>&1

step "9. Delete the SNS topic (this also deletes its subscriptions)"
aws sns delete-topic --topic-arn "arn:aws:sns:${REGION}:${ACCOUNT_ID}:video-ai-notifications" 2>/dev/null

step "10. Delete ECS task definitions, the cluster, the ECR repository and the /ecs/video-processor log group"
for td in $(aws ecs list-task-definitions --family-prefix video-processor-task --status ACTIVE --query 'taskDefinitionArns[]' --output text 2>/dev/null); do
  aws ecs deregister-task-definition --task-definition "$td" >/dev/null
done
INACTIVE=$(aws ecs list-task-definitions --family-prefix video-processor-task --status INACTIVE --query 'taskDefinitionArns[]' --output text 2>/dev/null)
# delete-task-definitions accepts up to 10 ARNs at a time
# shellcheck disable=SC2086
[ -n "$INACTIVE" ] && aws ecs delete-task-definitions --task-definitions $(echo $INACTIVE | tr ' ' '\n' | head -10) >/dev/null
aws ecs delete-cluster --cluster video-ai-cluster >/dev/null 2>&1
aws ecr delete-repository --repository-name video-processor --force >/dev/null 2>&1
aws logs delete-log-group --log-group-name /ecs/video-processor 2>/dev/null

step "11. Delete the Transcribe jobs (their names start with job-)"
for j in $(aws transcribe list-transcription-jobs --job-name-contains job- --query 'TranscriptionJobSummaries[].TranscriptionJobName' --output text 2>/dev/null); do
  aws transcribe delete-transcription-job --transcription-job-name "$j"
done

step "12. Turn off S3 -> EventBridge, empty and delete the bucket (this also removes uploads/bad.mp4 if it is still there)"
aws s3api put-bucket-notification-configuration --bucket "$BUCKET" --notification-configuration '{}' 2>/dev/null
aws s3 rb "s3://${BUCKET}" --force 2>/dev/null

step "13. Delete the Step Functions log group and the IAM roles (including the pipeline and logging inline policies)"
aws logs delete-log-group --log-group-name /aws/vendedlogs/states/video-ai-pipeline-Logs 2>/dev/null
for role in "${ROLES[@]}"; do
  for p in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text 2>/dev/null); do
    aws iam delete-role-policy --role-name "$role" --policy-name "$p"
  done
  for arn in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$arn"
  done
  aws iam delete-role --role-name "$role" 2>/dev/null
done

echo
echo "Done. Check the console (or the verification list in the blog) to confirm nothing is left."
