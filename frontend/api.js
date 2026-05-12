export const api = {
  async _req(path, opts = {}) {
    const r = await fetch("/api" + path, opts);
    if (!r.ok) {
      const body = await r.text();
      const err = new Error(body);
      err.status = r.status;
      throw err;
    }
    return r.json();
  },
  get(p) {
    return this._req(p);
  },
  post(p, b) {
    return this._req(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
  },
  put(p, b) {
    return this._req(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
  },
  del(p) {
    return this._req(p, { method: "DELETE" });
  },
  upload(p, file) {
    const fd = new FormData();
    fd.append("file", file);
    return this._req(p, { method: "POST", body: fd });
  },
};

export async function speakMessage(convId, msgId) {
  const r = await fetch(`/api/conversations/${convId}/messages/${msgId}/speak`, {
    method: "POST",
  });
  if (!r.ok) {
    const err = new Error(await r.text());
    err.status = r.status;
    throw err;
  }
  const extractedText = decodeURIComponent(r.headers.get("X-Orb-TTS-Extracted-Text") || "");
  const extractionMethod = r.headers.get("X-Orb-TTS-Extraction-Method") || "";
  const blob = await r.blob();
  return {
    audioUrl: URL.createObjectURL(blob),
    extractedText,
    extractionMethod,
  };
}

export async function getMessageChunks(convId, msgId) {
  const r = await fetch(`/api/conversations/${convId}/messages/${msgId}/chunks`);
  if (!r.ok) {
    const err = new Error(await r.text());
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export async function speakChunk(convId, msgId, chunkIndex) {
  const r = await fetch(`/api/conversations/${convId}/messages/${msgId}/speak-chunk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chunk_index: chunkIndex }),
  });
  if (!r.ok) {
    const err = new Error(await r.text());
    err.status = r.status;
    throw err;
  }
  const blob = await r.blob();
  return { audioUrl: URL.createObjectURL(blob) };
}

export async function getTtsBackends() {
  const r = await fetch("/api/tts/backends");
  if (!r.ok) return [];
  return r.json();
}

export async function getTtsVoices(backend, language, { apiUrl, apiKey } = {}) {
  const params = new URLSearchParams({ backend });
  if (language) params.set("language", language);
  if (apiUrl) params.set("api_url", apiUrl);
  if (apiKey) params.set("api_key", apiKey);
  const r = await fetch(`/api/tts/voices?${params}`);
  if (!r.ok) return [];
  return r.json();
}

export async function getTtsModels(backend, { apiUrl, apiKey } = {}) {
  const params = new URLSearchParams({ backend });
  if (apiUrl) params.set("api_url", apiUrl);
  if (apiKey) params.set("api_key", apiKey);
  const r = await fetch(`/api/tts/models?${params}`);
  if (!r.ok) return [];
  return r.json();
}

export async function ttsPreview(params) {
  const r = await fetch("/api/tts/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}

export function stopConversation(convId) {
  fetch(`/api/conversations/${convId}/stop`, { method: "POST" }).catch(() => {});
}

export async function getContextSize(convId) {
  const r = await fetch(`/api/conversations/${convId}/context-size`);
  if (!r.ok) return null;
  return r.json();
}

export function summarizeConversation(convId, { keepCount, customInstructions }, signal) {
  return fetch(`/api/conversations/${convId}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keep_count: keepCount, custom_instructions: customInstructions }),
    signal,
  });
}

export function streamPost(path, body, signal) {
  return fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export async function getVoiceProfile(cardId) {
  const r = await fetch(`/api/characters/${cardId}/voice-profile`);
  if (!r.ok) return null;
  return r.json();
}

export async function saveVoiceProfile(cardId, profile) {
  const r = await fetch(`/api/characters/${cardId}/voice-profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
