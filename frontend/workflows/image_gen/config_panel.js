// Tools-panel "Secondary" card. A modal with the global config slot (backend,
// prompt tags, default prompts, per-persona prompts, generation parameters) read
// and written through the workflow config route, the active conversation's
// per-character enable + prompt read and written through the on-demand trigger,
// and a test-generation preview that renders inline without persisting.

import { S } from "/static/state.js";
import { api } from "/static/api.js";
import { convUrl, esc } from "/static/utils.js";
import { showModal } from "/static/modal.js";

const WORKFLOW_ID = "image_gen";

// Local merge base so a config slot missing a key still populates the form. The
// config route returns the backend defaults for an unset slot, so these are only
// a fallback for a partial slot.
const DEFAULTS = {
  comfy_url: "http://127.0.0.1:8188",
  timeout_s: 180,
  artist_tags: "",
  style_tags: "",
  quality_tags: "",
  negative_prompt: "",
  persona_prompts: {},
  prompt_guideline: "",
  cfg: 5,
  steps: 40,
  width: 1536,
  height: 1152,
  seed: -1,
};

let cfg = { ...DEFAULTS };
let personaIds = [];

export function initConfigPanel() {
  window.imageGenOpenSettings = openSettings;
  window.imageGenSaveGlobal = saveGlobal;
  window.imageGenSaveChar = saveChar;
  window.imageGenTest = runTest;
}

function triggerUrl() {
  return convUrl(S.activeConvId, "workflows", WORKFLOW_ID, "trigger");
}

export function configPanelRenderer() {
  return `<div class="tool-card">
    <div class="tool-card-header">
      <span class="tool-card-name">Image Generation</span>
      <button class="ig-settings-btn" onclick="window.imageGenOpenSettings()">Settings</button>
    </div>
    <div class="tool-card-desc">Illustrate each reply through a ComfyUI backend.</div>
  </div>`;
}

function openSettings() {
  showModal(`<h2>Image Generation</h2><div class="ig-config" id="ig-config">Loading settings...</div>`);
  setTimeout(populate, 0);
}

async function populate() {
  let personas = [];
  try {
    const [cres, pres] = await Promise.all([
      api.get("/workflows/" + WORKFLOW_ID + "/config"),
      api.get("/user-personas"),
    ]);
    cfg = { ...DEFAULTS, ...((cres && cres.config) || {}) };
    if (!cfg.persona_prompts || typeof cfg.persona_prompts !== "object") cfg.persona_prompts = {};
    personas = Array.isArray(pres) ? pres : (pres && pres.personas) || [];
  } catch (e) {
    console.warn("image_gen: settings load failed", e);
  }
  const el = document.getElementById("ig-config");
  if (!el) return;
  personaIds = personas.map((p) => String(p.id));
  el.innerHTML = formHtml(personas);
  setTimeout(populateChar, 0);
}

function row(label, inner) {
  return `<label class="ig-row">${label} ${inner}</label>`;
}

function stacked(label, inner) {
  return `<label class="ig-row ig-stack">${label}${inner}</label>`;
}

// Fields with a baked default (quality tags, negative prompt, prompting
// guideline) show it as placeholder (ghost) text rather than a stored value, so
// the default is sourced from the manifest's config schema -- the backend
// applies it whenever the field is left empty.
function schemaDefault(key) {
  const entry = (S.workflowManifest || []).find((w) => w.id === WORKFLOW_ID);
  return entry?.config_schema?.properties?.[key]?.default || "";
}

function formHtml(personas) {
  const personaRows = personas.length
    ? personas
        .map((p) => {
          const id = esc(String(p.id));
          const val = esc((cfg.persona_prompts && cfg.persona_prompts[String(p.id)]) || "");
          return stacked(
            esc(p.name || "Persona " + p.id),
            `<textarea id="ig-persona-${id}" rows="2">${val}</textarea>`,
          );
        })
        .join("")
    : `<div class="ig-note">No personas defined.</div>`;
  return `
    <div class="ig-section">
      <div class="ig-heading">Backend</div>
      ${row("ComfyUI URL", `<input type="text" id="ig-comfy_url" value="${esc(cfg.comfy_url)}">`)}
      ${row("Render timeout (s)", `<input type="number" id="ig-timeout_s" value="${esc(String(cfg.timeout_s))}">`)}
    </div>
    <div class="ig-section">
      <div class="ig-heading">Prompt tags (prepended to every positive prompt)</div>
      ${row("Artist", `<input type="text" id="ig-artist_tags" value="${esc(cfg.artist_tags)}">`)}
      ${row("Style", `<input type="text" id="ig-style_tags" value="${esc(cfg.style_tags)}">`)}
      ${row("Quality", `<input type="text" id="ig-quality_tags" value="${esc(cfg.quality_tags)}" placeholder="${esc(schemaDefault("quality_tags"))}">`)}
      ${stacked("Negative prompt", `<textarea id="ig-negative_prompt" rows="2" placeholder="${esc(schemaDefault("negative_prompt"))}">${esc(cfg.negative_prompt)}</textarea>`)}
    </div>
    <div class="ig-section">
      <div class="ig-heading">Backend prompting guideline</div>
      ${stacked("Leave empty to use the default shown", `<textarea id="ig-prompt_guideline" rows="4" placeholder="${esc(schemaDefault("prompt_guideline"))}">${esc(cfg.prompt_guideline)}</textarea>`)}
    </div>
    <div class="ig-section">
      <div class="ig-heading">Per-persona prompts</div>
      ${personaRows}
    </div>
    <div class="ig-section">
      <div class="ig-heading">Generation</div>
      ${row("CFG", `<input type="number" step="0.1" id="ig-cfg" value="${esc(String(cfg.cfg))}">`)}
      ${row("Steps", `<input type="number" id="ig-steps" value="${esc(String(cfg.steps))}">`)}
      ${row("Width", `<input type="number" id="ig-width" value="${esc(String(cfg.width))}">`)}
      ${row("Height", `<input type="number" id="ig-height" value="${esc(String(cfg.height))}">`)}
      ${row("Seed (-1 random)", `<input type="number" id="ig-seed" value="${esc(String(cfg.seed))}">`)}
      <div class="ig-row"><button type="button" class="btn btn-accent" onclick="window.imageGenSaveGlobal()">Save settings</button><span id="ig-global-status"></span></div>
    </div>
    <div class="ig-section" id="ig-char">Loading character...</div>
    <div class="ig-section">
      <div class="ig-heading">Test generation</div>
      <div class="ig-row">
        <button type="button" class="btn" onclick="window.imageGenTest()">Test</button>
        <span id="ig-test-status"></span>
      </div>
      <div class="ig-preview" id="ig-preview"></div>
    </div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`;
}

function strVal(id) {
  return document.getElementById(id)?.value || "";
}

function numVal(id, fallback) {
  const v = parseFloat(document.getElementById(id)?.value);
  return Number.isFinite(v) ? v : fallback;
}

function intVal(id, fallback) {
  const v = parseInt(document.getElementById(id)?.value, 10);
  return Number.isFinite(v) ? v : fallback;
}

// The config slot is replaced wholesale on write, so every key must be sent or
// an omitted one reverts to its default.
function readGlobal() {
  const persona_prompts = {};
  for (const id of personaIds) {
    const t = document.getElementById("ig-persona-" + id);
    if (t && t.value.trim()) persona_prompts[id] = t.value;
  }
  return {
    comfy_url: strVal("ig-comfy_url"),
    timeout_s: numVal("ig-timeout_s", 180),
    artist_tags: strVal("ig-artist_tags"),
    style_tags: strVal("ig-style_tags"),
    quality_tags: strVal("ig-quality_tags"),
    negative_prompt: strVal("ig-negative_prompt"),
    persona_prompts,
    prompt_guideline: strVal("ig-prompt_guideline"),
    cfg: numVal("ig-cfg", 5),
    steps: intVal("ig-steps", 40),
    width: intVal("ig-width", 1536),
    height: intVal("ig-height", 1152),
    seed: intVal("ig-seed", -1),
  };
}

async function saveGlobal() {
  const blob = readGlobal();
  cfg = { ...cfg, ...blob };
  const status = document.getElementById("ig-global-status");
  try {
    await api.put("/workflows/" + WORKFLOW_ID + "/config", { config: blob });
    if (status) status.textContent = "Saved";
  } catch (e) {
    console.warn("image_gen: config save failed", e);
    if (status) status.textContent = "Save failed";
  }
}

async function populateChar() {
  let el = document.getElementById("ig-char");
  if (!el) return;
  if (!S.activeConvId) {
    el.innerHTML = `<div class="ig-heading">This character</div><div class="ig-note">Open a conversation to configure its character.</div>`;
    return;
  }
  let state;
  try {
    state = await api.post(triggerUrl(), { action: "get_char_state" });
  } catch (e) {
    console.warn("image_gen: character load failed", e);
    el = document.getElementById("ig-char");
    if (el)
      el.innerHTML = `<div class="ig-heading">This character</div><div class="ig-note">Could not load character settings.</div>`;
    return;
  }
  el = document.getElementById("ig-char");
  if (!el) return;
  if (!state || !state.character_id) {
    el.innerHTML = `<div class="ig-heading">This character</div><div class="ig-note">This conversation has no character.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="ig-heading">This character</div>
    <label class="ig-row"><input type="checkbox" id="ig-ch-enabled"${state.enabled ? " checked" : ""}> Auto-generate an image for this character's replies</label>
    ${stacked("Default character prompt (this character)", `<textarea id="ig-ch-prompt" rows="3">${esc(state.prompt || "")}</textarea>`)}
    <div class="ig-row"><button type="button" class="btn btn-accent" onclick="window.imageGenSaveChar()">Save character</button><span id="ig-ch-status"></span></div>`;
}

async function saveChar() {
  if (!S.activeConvId) return;
  const status = document.getElementById("ig-ch-status");
  try {
    const res = await api.post(triggerUrl(), {
      action: "set_char_state",
      enabled: !!document.getElementById("ig-ch-enabled")?.checked,
      prompt: strVal("ig-ch-prompt"),
    });
    if (status) status.textContent = res && res.error ? res.error : "Saved";
  } catch (e) {
    console.error("image_gen: character save failed", e);
    if (status) status.textContent = "Save failed";
  }
}

function runTest() {
  const body = { action: "test", config: readGlobal() };
  // The active character's live prompt is only present when the conversation has
  // one; omit it otherwise so the backend reads the stored value.
  const ch = document.getElementById("ig-ch-prompt");
  if (ch) body.char_prompt = ch.value;
  return doTest(body);
}

async function doTest(body) {
  if (!S.activeConvId) return;
  const status = document.getElementById("ig-test-status");
  const preview = document.getElementById("ig-preview");
  if (status) status.textContent = "Generating...";
  if (preview) preview.innerHTML = "";
  try {
    const res = await api.post(triggerUrl(), body);
    if (res && res.image_b64) {
      if (preview)
        preview.innerHTML = `<img src="data:${esc(res.mime || "image/png")};base64,${res.image_b64}" alt="test render">`;
      if (status) status.textContent = "";
    } else if (status) {
      status.textContent = (res && res.error) || "Test failed";
    }
  } catch (e) {
    console.error("image_gen: test failed", e);
    if (status) status.textContent = "Test failed";
  }
}
