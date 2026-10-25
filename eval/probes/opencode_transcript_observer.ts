// Probe-only OpenCode 2.1.4 plugin (opencode_transcript_probe.py): logs every permission
// evaluation (action, resources, rule-derived effect) to $PROBE_PERMISSION_LOG. It observes
// only; it never changes `effect`. The `permission` "evaluate" hook fires after the rules are
// evaluated and before `opencode run` answers an "ask" (core/src/permission.ts evaluateInput),
// so asks show here even under --auto. Deny short-circuits before the hook and is not logged.
import { appendFileSync } from "node:fs"

const LOG = process.env.PROBE_PERMISSION_LOG

export default {
  id: "probe-permission-observer",
  setup: async (ctx: any) => {
    await ctx.permission.hook("evaluate", (event: any) => {
      if (!LOG) return
      appendFileSync(
        LOG,
        JSON.stringify({
          t: Date.now(),
          label: process.env.PROBE_LABEL,
          agent: event.agent,
          action: event.action,
          resources: event.resources,
          effect: event.effect,
        }) + "\n",
      )
    })
  },
}
