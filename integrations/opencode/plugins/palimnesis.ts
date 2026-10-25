// Palimnesis session identity for OpenCode 2.1.4.
// Routes every model request for the `palimnesis` provider to
// /s/<OpenCode sessionID>/v1 so each OpenCode session maps to exactly one
// Palimnesis session, and tags the request kind (primary, title, compaction,
// generate) in X-Palimnesis-Kind. If this plugin fails to load, requests hit the
// unprefixed base URL and Palimnesis rejects them with `session_required`
// instead of merging chats.
const ORIGIN = process.env.PALIMNESIS_PROXY_ORIGIN ?? "http://127.0.0.1:9000"

export default {
  id: "palimnesis-session-url",
  setup: async (ctx: any) => {
    await ctx.session.hook(
      "model.request",
      (event: any) => {
        event.baseURL = `${ORIGIN}/s/${event.sessionID}/v1`
        event.headers["X-Palimnesis-Kind"] = event.kind
      },
      { providerID: "palimnesis" },
    )
  },
}
