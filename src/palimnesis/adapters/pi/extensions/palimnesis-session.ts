// Palimnesis session association for Pi (Phase 4B S9; docs/probes/pi.md HP2, VERIFIED on
// Pi 1.5.0). Every model request carries X-Palimnesis-Session = Pi's own session id, so
// one Pi session is one Palimnesis session, through /new, /fork, /clone, /resume and
// restarts, on both protocols. Load it with `pi -e <this file>` or from the agent
// directory's extensions.
export default function (pi) {
  pi.on("before_provider_headers", (event, ctx) => {
    event.headers["X-Palimnesis-Session"] = ctx.sessionManager.getSessionId();
  });
}
