// Resolver for Query.getJob, attached to the DynamoDB data source (table VideoJobs).
import { util } from '@aws-appsync/utils';

export function request(ctx) {
  return {
    operation: 'GetItem',
    key: util.dynamodb.toMapValues({ jobId: ctx.args.jobId }),
  };
}

export function response(ctx) {
  // Returns null (no error) when the job does not exist.
  return ctx.result;
}
