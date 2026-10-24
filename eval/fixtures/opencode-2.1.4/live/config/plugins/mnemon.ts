// Mnemon per-session identity for OpenCode 2.1.4 (probe).
// Rewrites each model request's base URL to /s/<OpenCode sessionID>/v1 on the
// Mnemon proxy and tags the request kind in X-Mnemon-Kind (the proxy strips
// x-mnemon-* headers before forwarding upstream).
import { appendFileSync } from "node:fs"

const BASE = process.env.MNEMON_PROXY_ORIGIN ?? "http://127.0.0.1:9011"
const LOG = process.env.MNEMON_PLUGIN_LOG

export default {
  id: "mnemon-session-url",
  setup: async (ctx: any) => {
    await ctx.session.hook(
      "model.request",
      (event: any) => {
        const before = event.baseURL
        event.baseURL = `${BASE}/s/${event.sessionID}/v1`
        event.headers["X-Mnemon-Kind"] = event.kind
        if (LOG)
          appendFileSync(
            LOG,
            JSON.stringify({
              at: new Date().toISOString(),
              kind: event.kind,
              sessionID: event.sessionID,
              agent: event.agent,
              model: event.model,
              before,
              after: event.baseURL,
              headerNames: Object.keys(event.headers),
            }) + "\n",
          )
      },
      { providerID: "mnemon" },
    )
  },
}
