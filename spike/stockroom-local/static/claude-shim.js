/* SPIKE ONLY. A stand-in for the Claude artifact runtime (window.claude.use("db" | "assets" | "downloads" | "sample")) that talks to
   the local spike server. Unlike dev/mock-claude.js this is NOT in-memory: documents live in PostgreSQL, photos are files on disk,
   leases are real database rows, live updates are pushed by the database (LISTEN/NOTIFY -> server-sent events).
   `sample` is deliberately null: there is no tag reading outside Claude and no paid API is used.
   Set localStorage.spike_nolock = "1" to make acquire() a no-op (used only to prove the concurrency test can fail). */
(function () {
  const J = {"Content-Type": "application/json"};
  const err = (code, message) => Object.assign(new Error(message || code), {code});
  async function api(method, path, body) {
    let r;
    try { r = await fetch(path, {method, headers: body === undefined ? {} : J, body: body === undefined ? undefined : JSON.stringify(body)}); }
    catch (e) { throw err("unavailable", "network"); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw err(j.code || "error", j.error);
    return j;
  }

  // one shared stream of "collection X changed" events
  const listeners = [];
  let es = null;
  function ensureStream() {
    if (es) return;
    es = new EventSource("/api/events");
    es.onmessage = (m) => listeners.filter((l) => l.name === m.data).forEach((l) => l.kick());
    es.onerror = () => { /* the browser reconnects by itself; a missed event is repaired by the next change or a reload */ };
  }

  const qs = (q) => {
    const p = new URLSearchParams();
    (q.where || []).forEach((w) => p.append("where", `${w.f}|${w.op}|${JSON.stringify(w.v)}`));
    if (q.order) { p.set("orderBy", q.order.f); p.set("dir", q.order.dir || "asc"); }
    if (q.lim) p.set("limit", q.lim);
    return p.toString();
  };
  const mkSnap = (docs) => ({docs: docs.map((d) => ({id: d.id, exists: true, data: () => JSON.parse(JSON.stringify(d.data))})), size: docs.length, empty: !docs.length});
  const mkDoc = (id, r) => ({exists: !!r.exists, id, data: () => JSON.parse(JSON.stringify(r.data || {}))});

  function onSnap(name, fetcher, cb, errcb) {
    ensureStream();
    let dead = false, busy = false, again = false;
    const run = async () => {
      if (dead) return;
      if (busy) { again = true; return; }
      busy = true;
      try { const s = await fetcher(); if (!dead) cb(s); } catch (e) { if (!dead && errcb) errcb(e); }
      busy = false;
      if (again) { again = false; run(); }
    };
    const l = {name, kick: () => setTimeout(run, 30)};
    listeners.push(l);
    run();
    return () => { dead = true; const i = listeners.indexOf(l); if (i >= 0) listeners.splice(i, 1); };
  }

  const query = (name, q = {where: [], order: null, lim: 0}) => ({
    orderBy: (f, dir) => query(name, {...q, order: {f, dir}}),
    limit: (n) => query(name, {...q, lim: n}),
    where: (f, op, v) => query(name, {...q, where: [...q.where, {f, op, v}]}),
    get: async () => mkSnap((await api("GET", `/api/col/${name}?${qs(q)}`)).docs),
    onSnapshot: (cb, errcb) => onSnap(name, async () => mkSnap((await api("GET", `/api/col/${name}?${qs(q)}`)).docs), cb, errcb),
    doc: (id) => docRef(name, id),
  });
  const docRef = (name, id) => ({
    get: async () => mkDoc(id, await api("GET", `/api/doc/${name}/${encodeURIComponent(id)}`)),
    set: async (v) => { await api("PUT", `/api/doc/${name}/${encodeURIComponent(id)}`, v); },
    update: async (v) => { await api("PATCH", `/api/doc/${name}/${encodeURIComponent(id)}`, v); },
    delete: async () => { await api("DELETE", `/api/doc/${name}/${encodeURIComponent(id)}`); },
    onSnapshot: (cb, errcb) => onSnap(name, async () => mkDoc(id, await api("GET", `/api/doc/${name}/${encodeURIComponent(id)}`)), cb, errcb),
    acquire: async ({holder, ttlMs}) => {
      if (localStorage.getItem("spike_nolock") === "1") return {acquired: true};      // test switch only
      return api("POST", `/api/lease/${name}/${encodeURIComponent(id)}`, {holder, ttlMs});
    },
  });
  const db = {collection: (n) => query(n), doc: (path) => { const [n, id] = path.split("/"); return docRef(n, id); }};

  const assets = {
    upload: async (blob, opts) => {
      let r;
      try { r = await fetch("/api/assets", {method: "POST", headers: {"Content-Type": (opts && opts.type) || blob.type || "application/octet-stream"}, body: blob}); }
      catch (e) { throw err("store_unavailable"); }
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw err(j.code || "store_unavailable", j.error);
      return {id: j.id};
    },
    list: async () => api("GET", "/api/assets"),
    delete: async (id) => { await api("DELETE", `/api/assets/${id}`); },
  };

  // a normal browser download (an <a download> click) - what a self-hosted page would do
  const downloads = {
    save: async ({filename, data}) => {
      const blob = data instanceof Blob ? data : new Blob([data]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.style.display = "none";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    },
  };

  // The page has no message of its own for "tag reading unavailable" (it simply never offers it), so the shim says it out loud.
  function notice() {
    if (document.getElementById("spike-notice")) return;
    const d = document.createElement("div");
    d.id = "spike-notice";
    d.setAttribute("role", "note");
    d.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:2147483000;background:#fff7d6;color:#4a3b00;border-top:1px solid #d9c36a;font:12px/1.35 system-ui,sans-serif;padding:6px 10px;text-align:center;pointer-events:none";
    d.textContent = "SPIKE (local test): reading tags with Claude is NOT available here. Save products with their photos and type the tag details yourself.";
    document.body.appendChild(d);
  }
  if (document.body) notice(); else document.addEventListener("DOMContentLoaded", notice);

  window.claude = {use: async (name) => name === "db" ? db : name === "assets" ? assets : name === "downloads" ? downloads : null /* "sample": deliberately unavailable */};
})();
