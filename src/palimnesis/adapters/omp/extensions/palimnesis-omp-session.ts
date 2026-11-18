// Route each OMP session to its own Palimnesis archive through the session URL (D104).
// OMP has no per-request header hook like Pi's, so the provider's base URL is
// re-registered whenever the session changes, and every request checks that the URL in
// use still belongs to the current session: a mismatch fails the request instead of
// archiving it into another session. The palimnesis-unrouted provider (background
// roles) is never routed, so Palimnesis refuses it with session_required.
export default function (pi) {
  let routed = null;

  async function route(_event, ctx) {
    const id = ctx.sessionManager.getSessionId();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) {
      throw new Error(`Invalid Palimnesis session id: ${id}`);
    }
    const base = `http://127.0.0.1:9000/s/${id}`;
    pi.registerProvider("palimnesis", { baseUrl: `${base}/v1` });
    const current = ctx.models.current();
    if (current?.provider === "palimnesis") {
      const updated = ctx.models.resolve(`${current.provider}/${current.id}`);
      if (!updated) throw new Error(`Palimnesis: cannot re-resolve ${current.provider}/${current.id}`);
      await pi.setModel(updated);
    }
    routed = id;
  }

  pi.on("session_start", route);
  pi.on("session_switch", route);
  pi.on("session_branch", route);
  pi.on("before_provider_request", (event, ctx) => {
    if (ctx.model?.provider !== "palimnesis") return;
    const id = ctx.sessionManager?.getSessionId?.();
    if (!routed || id !== routed) {
      throw new Error(`Palimnesis: request for session ${id} but the provider is routed to ${routed}`);
    }
  });
}
