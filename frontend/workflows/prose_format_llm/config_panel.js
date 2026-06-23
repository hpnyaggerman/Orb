// Settings modal for the prose_format_llm workflow. Global behavior config goes
// through the /config route; the per-conversation prose-format spec goes through
// the on-demand trigger RPC. Mirrors the TTS panel pattern.

import { api } from "/static/api.js";
import { S } from "/static/state.js";
import { convUrl, esc } from "/static/utils.js";
import { showModal } from "/static/modal.js";

const WORKFLOW_ID = "prose_format_llm";

// One array of {name, description, value} drives both spec sections, so renaming
// an element never desyncs its recorded value. Rebuilt from the server on every
// open / analyze / reset.
let spec = [];

export function initConfigPanel() {
  window.pfOpenSettings = openSettings;
  window.pfSaveGlobal = saveGlobal;
  window.pfAddRow = addRow;
  window.pfDelRow = delRow;
  window.pfAnalyze = analyze;
  window.pfSaveSpec = saveSpec;
  window.pfReset = reset;
}

export function configCardRenderer() {
  return `<div class="tool-card-desc">Enforce a recorded prose format on replies via an LLM judge/enforce loop.</div>
    <button class="pf-settings-btn" onclick="window.pfOpenSettings()">Settings</button>`;
}

function triggerUrl() {
  return convUrl(S.activeConvId, "workflows", WORKFLOW_ID, "trigger");
}

async function openSettings() {
  showModal(modalShell());
  await loadGlobal();
  await populateSpec();
}

function modalShell() {
  return `<h2>Prose Format (LLM)</h2>
    <div class="pf-config">
      <h3>Enforcement</h3>
      <label class="pf-cfg-row">Max enforce iterations
        <input type="number" id="pf-cfg-iters" min="0" step="1" value="1" onchange="window.pfSaveGlobal()"></label>
      <label class="pf-cfg-row">Prompt mode
        <select id="pf-cfg-mode" onchange="window.pfSaveGlobal()">
          <option value="minimal">Minimal</option>
          <option value="extend">Full context</option>
        </select></label>
      <label class="pf-cfg-row"><input type="checkbox" id="pf-cfg-auto" onchange="window.pfSaveGlobal()"> Auto-analyze new conversations</label>
      <label class="pf-cfg-row"><input type="checkbox" id="pf-cfg-reasoning" onchange="window.pfSaveGlobal()"> Show model reasoning</label>
    </div>
    <div class="pf-spec" id="pf-spec">Loading...</div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`;
}

async function loadGlobal() {
  let cfg = {};
  try {
    const res = await api.get("/workflows/" + WORKFLOW_ID + "/config");
    cfg = (res && res.config) || {};
  } catch (e) {
    console.warn("prose_format_llm: config load failed", e);
  }
  const iters = document.getElementById("pf-cfg-iters");
  const mode = document.getElementById("pf-cfg-mode");
  const auto = document.getElementById("pf-cfg-auto");
  const reasoning = document.getElementById("pf-cfg-reasoning");
  if (iters) iters.value = Number.isInteger(cfg.max_iterations) ? cfg.max_iterations : 1;
  if (mode) mode.value = cfg.prompt_mode === "extend" ? "extend" : "minimal";
  if (auto) auto.checked = !!cfg.auto_analyze;
  if (reasoning) reasoning.checked = !!cfg.reasoning;
}

// The config slot is replaced wholesale on write, so every key must be sent or an
// omitted one reverts to its default.
async function saveGlobal() {
  const iters = parseInt(document.getElementById("pf-cfg-iters")?.value, 10);
  const config = {
    max_iterations: Number.isFinite(iters) && iters >= 0 ? iters : 1,
    prompt_mode: document.getElementById("pf-cfg-mode")?.value === "extend" ? "extend" : "minimal",
    auto_analyze: !!document.getElementById("pf-cfg-auto")?.checked,
    reasoning: !!document.getElementById("pf-cfg-reasoning")?.checked,
  };
  try {
    await api.put("/workflows/" + WORKFLOW_ID + "/config", { config });
  } catch (e) {
    console.warn("prose_format_llm: config save failed", e);
  }
}

async function populateSpec() {
  const host = document.getElementById("pf-spec");
  if (!host) return;
  if (!S.activeConvId) {
    host.innerHTML = `<div class="pf-note">Open a conversation to edit its prose format.</div>`;
    return;
  }
  try {
    applyState(await postAction({ action: "get" }));
  } catch (e) {
    // The trigger route is 404 when the workflow is toggled off.
    host.innerHTML = `<div class="pf-note">Enable this workflow to view or edit its prose format.</div>`;
  }
}

function postAction(body) {
  return api.post(triggerUrl(), body);
}

function applyState(res) {
  const schema = (res && res.schema) || {};
  const values = (res && res.values) || {};
  const names = Object.keys(schema);
  for (const k of Object.keys(values)) if (!names.includes(k)) names.push(k);
  spec = names.map((n) => ({ name: n, description: schema[n] || "", value: values[n] || "" }));
  renderSpec();
}

// Read the editable fields back into the spec array before any mutation or save.
function gather() {
  for (const el of document.querySelectorAll("[data-pf-name]"))
    if (spec[+el.dataset.i]) spec[+el.dataset.i].name = el.value;
  for (const el of document.querySelectorAll("[data-pf-desc]"))
    if (spec[+el.dataset.i]) spec[+el.dataset.i].description = el.value;
  for (const el of document.querySelectorAll("[data-pf-val]"))
    if (spec[+el.dataset.i]) spec[+el.dataset.i].value = el.value;
}

function renderSpec() {
  const host = document.getElementById("pf-spec");
  if (!host) return;
  const schemaRows = spec
    .map(
      (r, i) => `<div class="pf-row">
      <input type="text" data-pf-name data-i="${i}" value="${esc(r.name)}" placeholder="element">
      <textarea data-pf-desc data-i="${i}" rows="2" placeholder="how the analyzer should describe this element">${esc(r.description)}</textarea>
      <button onclick="window.pfDelRow(${i})">Remove</button>
    </div>`,
    )
    .join("");
  const valueRows = spec
    .map(
      (r, i) => `<div class="pf-row">
      <span class="pf-elem">${esc(r.name) || "(unnamed)"}</span>
      <textarea data-pf-val data-i="${i}" rows="2" placeholder="recorded format (filled by Analyze)">${esc(r.value)}</textarea>
    </div>`,
    )
    .join("");
  host.innerHTML = `<h3>Elements (analyzer guidance)</h3>
    ${schemaRows}
    <button onclick="window.pfAddRow()">+ Add element</button>
    <h3>Recorded format (what gets enforced)</h3>
    ${valueRows}
    <div class="pf-actions">
      <button onclick="window.pfAnalyze()">Analyze now</button>
      <button onclick="window.pfSaveSpec()">Save</button>
      <button onclick="window.pfReset()">Reset to defaults</button>
      <span id="pf-status"></span>
    </div>`;
}

function setStatus(msg) {
  const el = document.getElementById("pf-status");
  if (el) el.textContent = msg;
}

function buildMaps() {
  const schema = {};
  const values = {};
  for (const r of spec) {
    const name = (r.name || "").trim();
    if (!name) continue;
    schema[name] = r.description || "";
    values[name] = r.value || "";
  }
  return { schema, values };
}

function addRow() {
  gather();
  spec.push({ name: "", description: "", value: "" });
  renderSpec();
}

function delRow(i) {
  gather();
  spec.splice(i, 1);
  renderSpec();
}

async function saveSpec() {
  gather();
  const { schema, values } = buildMaps();
  try {
    applyState(await postAction({ action: "save", schema, values }));
    setStatus("Saved");
  } catch (e) {
    setStatus("Save failed");
  }
}

async function analyze() {
  gather();
  const { schema, values } = buildMaps();
  setStatus("Analyzing...");
  try {
    // Persist the current guidance first so the analyzer reads the edited schema.
    await postAction({ action: "save", schema, values });
    applyState(await postAction({ action: "analyze" }));
    setStatus("Analyzed");
  } catch (e) {
    setStatus("Analyze failed");
  }
}

async function reset() {
  try {
    applyState(await postAction({ action: "reset" }));
    setStatus("Reset to defaults");
  } catch (e) {
    setStatus("Reset failed");
  }
}
