export const api = {
  async _req(path, opts = {}) {
    const r = await fetch('/api' + path, opts);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  get(p)    { return this._req(p); },
  post(p, b){ return this._req(p, { method: 'POST',   headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); },
  put(p, b) { return this._req(p, { method: 'PUT',    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); },
  del(p)    { return this._req(p, { method: 'DELETE' }); },
  upload(p, file) {
    const fd = new FormData();
    fd.append('file', file);
    return this._req(p, { method: 'POST', body: fd });
  },
};