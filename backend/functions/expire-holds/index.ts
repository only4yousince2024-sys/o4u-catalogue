// FALLBACK scheduler for expire_holds() - for a Supabase plan/region where pg_cron is not available. CODE ONLY: not
// deployed, not tested here (no Deno/Supabase in the development sandbox). See backend/README.md for how the owner would use it.
//
// What it does: calls the database function expire_holds() with the service role. The function itself is safe to call from
// several schedulers at once and from a retry (migration 0003), so it does not matter if this runs twice.
//
// Secrets (set in the Supabase dashboard / `supabase secrets set`; NEVER committed):
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   - provided to every Edge Function by Supabase itself
//   EXPIRE_HOLDS_SECRET                       - a long random string the scheduler sends in the `x-o4u-cron` header
// Deploy with JWT verification OFF for this function (`--no-verify-jwt`) because the caller is a scheduler, not a signed-in
// user; the shared secret below is what protects it.
import { createClient } from "npm:@supabase/supabase-js@2";

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("POST only", { status: 405 });
  const secret = Deno.env.get("EXPIRE_HOLDS_SECRET");
  const given = req.headers.get("x-o4u-cron") ?? "";
  // constant-time-ish comparison; an unset secret means the function refuses everything
  if (!secret || secret.length < 24 || given.length !== secret.length ||
      [...secret].reduce((d, c, i) => d | (c.charCodeAt(0) ^ given.charCodeAt(i)), 0) !== 0) {
    return new Response("forbidden", { status: 403 });
  }
  const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await db.rpc("expire_holds");
  if (error) {
    console.error("expire_holds failed", error.message);
    return new Response(JSON.stringify({ ok: false, error: error.message }), { status: 500, headers: { "content-type": "application/json" } });
  }
  return new Response(JSON.stringify({ ok: true, released: data }), { headers: { "content-type": "application/json" } });
});
