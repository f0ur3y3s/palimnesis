// Mnemon session identity for OpenCode 2.1.4.
// Routes every model request for the `mnemon` provider to
// /s/<OpenCode sessionID>/v1 so each OpenCode session maps to exactly one
// Mnemon session, and tags the request kind (primary, title, compaction,
// generate) in X-Mnemon-Kind. If this plugin fails to load, requests hit the
// unprefixed base URL and Mnemon rejects them with `session_required`
// instead of merging chats.
const ORIGIN = process.env.MNEMON_PROXY_ORIGIN ?? "http://127.0.0.1:9000"

export default {
  id: "mnemon-session-url",
  setup: async (ctx: any) => {
    await ctx.session.hook(
      "model.request",
      (event: any) => {
        event.baseURL = `${ORIGIN}/s/${event.sessionID}/v1`
        event.headers["X-Mnemon-Kind"] = event.kind
      },
      { providerID: "mnemon" },
    )
  },
}
