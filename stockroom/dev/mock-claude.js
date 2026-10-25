/* Stand-in for the Claude artifact runtime (db / assets / downloads / sample), for LOCAL TESTS AND PREVIEWS ONLY.
   It holds SYNTHETIC records passed in by the test or preview page. It is never part of stockroom-dev.html,
   never shipped, and cannot reach a real database. */
(function () {
  function makeDb(data) {
    const listeners = [];
    const col = (name) => (data[name] = data[name] || {});
    const snapOf = (name, q) => {
      let docs = Object.entries(col(name)).map(([id, d]) => ({id, d}));
      for (const w of q.where) docs = docs.filter(({d}) => w.op === "==" ? d[w.f] === w.v : true);
      if (q.order) docs.sort((a, b) => (String(a.d[q.order.f]) < String(b.d[q.order.f]) ? -1 : String(a.d[q.order.f]) > String(b.d[q.order.f]) ? 1 : 0) * (q.order.dir === "desc" ? -1 : 1));
      if (q.lim) docs = docs.slice(0, q.lim);
      return {docs: docs.map(({id, d}) => ({id, data: () => JSON.parse(JSON.stringify(d))})), size: docs.length};
    };
    const query = (name, q = {where: [], order: null, lim: 0}) => ({
      orderBy: (f, dir) => query(name, {...q, order: {f, dir}}), limit: (n) => query(name, {...q, lim: n}),
      where: (f, op, v) => query(name, {...q, where: [...q.where, {f, op, v}]}),
      get: async () => snapOf(name, q),
      onSnapshot: (cb) => { const run = () => cb(snapOf(name, q)); listeners.push({name, run}); setTimeout(run, 0); return () => {}; },
      doc: (id) => docRef(name, id),
    });
    const notify = (name) => listeners.filter((l) => l.name === name).forEach((l) => setTimeout(l.run, 0));
    const docRef = (name, id) => ({
      get: async () => { const d = col(name)[id]; return {exists: !!d, id, data: () => JSON.parse(JSON.stringify(d || {}))}; },
      set: async (v) => { col(name)[id] = JSON.parse(JSON.stringify(v)); notify(name); },
      update: async (v) => { col(name)[id] = {...(col(name)[id] || {}), ...JSON.parse(JSON.stringify(v))}; notify(name); },
      delete: async () => { delete col(name)[id]; notify(name); },
      onSnapshot: (cb) => { const run = () => { const d = col(name)[id]; cb({exists: !!d, id, data: () => JSON.parse(JSON.stringify(d || {}))}); }; listeners.push({name, run}); setTimeout(run, 0); return () => {}; },
    });
    return {collection: (n) => query(n), doc: (path) => { const [n, id] = path.split("/"); return docRef(n, id); }};
  }
  window.__installMock = function (data) {
    const db = makeDb(data);
    window.__mockData = data;
    window.claude = {use: async (name) => name === "db" ? db : name === "downloads" ? {save: async (x) => { (window.__saved = window.__saved || []).push(x.filename); }} : null};
  };
})();
