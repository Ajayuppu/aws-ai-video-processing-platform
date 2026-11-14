// Resolver for Mutation.publishJobUpdate, attached to a NONE data source (a "local resolver").
// It does not call any backend. It hands the input straight back, and because the mutation is
// listed in @aws_subscribe, AppSync pushes the result to every matching subscriber.
export function request(ctx) {
  return { payload: ctx.args.input };
}

export function response(ctx) {
  return ctx.result;
}
