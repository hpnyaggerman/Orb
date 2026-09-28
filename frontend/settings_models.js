import { api } from "./api.js";
import { renderInspector } from "./chat.js";
import { CLOSE_ICON, EDIT_ICON, PLUS_ICON } from "./icons.js";
import { renderInteractiveFragments } from "./library_fragments.js";
import { closeModal, showConfirmModal, showModal } from "./modal.js";
import { filterModelChoices, mergeModelChoices, profileLabel } from "./model_catalog.js";
import { S } from "./state.js";
import { $, esc, escAttr, toast } from "./utils.js";
import { validate } from "./validate.js";

const MODEL_HYPERPARAM_KEYS = [
  "shared_system_prompt",
  "system_prompt",
  "temperature",
  "max_tokens",
  "top_p",
  "min_p",
  "top_k",
  "repetition_penalty",
  "reasoning_effort",
  "reasoning_effort_param",
  "reasoning_effort_value",
  "extra_headers",
  "extra_body",
];

const STANDARD_REASONING_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];

const SETTING_FIELDS = [
  { k: "endpoint_url", l: "Endpoint URL", t: "text" },
  { k: "api_key", l: "API Key", t: "api_key" },
  { k: "model_name", l: "Model Name", t: "text" },
  {
    k: "completion_mode",
    l: "API Mode",
    t: "select",
    opts: [
      ["chat", "Chat Completions"],
      ["text", "Text Completion (llama.cpp)"],
    ],
  },
  { k: "proxy", l: "Proxy", t: "text", ph: "socks5://127.0.0.1:1080" },
  { k: "shared_system_prompt", l: "System Prompt (global)", t: "textarea" },
  { k: "system_prompt", l: "System Prompt (model)", t: "textarea" },
  { k: "temperature", l: "Temperature", t: "number", s: "0.05", mn: "0", mx: "2" },
  { k: "max_tokens", l: "Max Tokens", t: "number", s: "64", mn: "64", mx: "32768" },
  { k: "top_p", l: "Top P", t: "number", s: "0.05", mn: "0", mx: "1" },
  { k: "min_p", l: "Min P", t: "number", s: "0.01", mn: "0", mx: "1" },
  { k: "top_k", l: "Top K", t: "number", s: "1", mn: "0", mx: "200" },
  { k: "repetition_penalty", l: "Rep. Penalty", t: "number", s: "0.05", mn: "1", mx: "2" },
  { k: "reasoning_effort", l: "Reasoning Effort", t: "reasoning_effort" },
  { k: "extra_headers", l: "Extra Request Headers", t: "textarea", ph: "X-Provider: deepinfra" },
  {
    k: "extra_body",
    l: "Extra Request Body (JSON, chat mode only)",
    t: "textarea",
    ph: '{"provider": {"only": ["deepinfra"]}}',
  },
];

const FIELD_GROUPS = [
  { l: "Prompts", cls: " ep-chat-only", keys: ["shared_system_prompt", "system_prompt"] },
  { l: "Sampling", keys: ["temperature", "max_tokens", "top_p", "min_p", "top_k", "repetition_penalty"] },
  { l: "Advanced", keys: ["reasoning_effort", "extra_headers", "extra_body"] },
];

const AGENT_MODEL_HYPERPARAM_KEYS = [
  "agent_shared_system_prompt",
  "agent_temperature",
  "agent_max_tokens",
  "agent_top_p",
  "agent_min_p",
  "agent_top_k",
  "agent_repetition_penalty",
  "agent_reasoning_effort",
  "agent_reasoning_effort_param",
  "agent_reasoning_effort_value",
  "agent_extra_headers",
  "agent_extra_body",
];

const AGENT_SETTING_FIELDS = [
  { k: "agent_endpoint_url", l: "Agent Endpoint URL", t: "text" },
  { k: "agent_api_key", l: "Agent API Key", t: "api_key" },
  { k: "agent_model_name", l: "Agent Model Name", t: "text" },
  {
    k: "agent_completion_mode",
    l: "Agent API Mode",
    t: "select",
    opts: [
      ["chat", "Chat Completions"],
      ["text", "Text Completion (llama.cpp)"],
    ],
  },
  { k: "agent_proxy", l: "Agent Proxy", t: "text", ph: "socks5://127.0.0.1:1080" },
  { k: "agent_shared_system_prompt", l: "Agent System Prompt (global)", t: "textarea" },
  { k: "agent_temperature", l: "Agent Temperature", t: "number", s: "0.05", mn: "0", mx: "2" },
  { k: "agent_max_tokens", l: "Agent Max Tokens", t: "number", s: "64", mn: "64", mx: "32768" },
  { k: "agent_top_p", l: "Agent Top P", t: "number", s: "0.05", mn: "0", mx: "1" },
  { k: "agent_min_p", l: "Agent Min P", t: "number", s: "0.01", mn: "0", mx: "1" },
  { k: "agent_top_k", l: "Agent Top K", t: "number", s: "1", mn: "0", mx: "200" },
  { k: "agent_repetition_penalty", l: "Agent Rep. Penalty", t: "number", s: "0.05", mn: "1", mx: "2" },
  { k: "agent_reasoning_effort", l: "Agent Reasoning Effort", t: "reasoning_effort" },
  { k: "agent_extra_headers", l: "Agent Extra Request Headers", t: "textarea", ph: "X-Provider: deepinfra" },
  {
    k: "agent_extra_body",
    l: "Agent Extra Request Body (JSON, chat mode only)",
    t: "textarea",
    ph: '{"provider": {"only": ["deepinfra"]}}',
  },
];

// A lane shows the profile it runs on: every field below edits that profile,
// except the global prompt, which belongs to settings and outlives any profile.
const WRITER_CTX = {
  role: "writer",
  label: "Profile",
  fieldsId: "writer-profile-fields",
  endpointIdKey: "activeEndpointId",
  configIdKey: "activeModelConfigId",
  urlField: "endpoint_url",
  apiKeyField: "api_key",
  modelField: "model_name",
  completionModeField: "completion_mode",
  proxyField: "proxy",
  activeConfigDbField: "active_model_config_id",
  settingsEndpointField: "active_endpoint_id",
  globalKeys: ["shared_system_prompt"],
  hyperparamKeys: MODEL_HYPERPARAM_KEYS,
  hyperparamPrefix: "",
};

const AGENT_CTX = {
  role: "agent",
  label: "Agent Profile",
  fieldsId: "agent-profile-fields",
  endpointIdKey: "agentEndpointId",
  configIdKey: "agentModelConfigId",
  urlField: "agent_endpoint_url",
  apiKeyField: "agent_api_key",
  modelField: "agent_model_name",
  completionModeField: "agent_completion_mode",
  proxyField: "agent_proxy",
  activeConfigDbField: "agent_active_model_config_id",
  settingsEndpointField: "agent_endpoint_id",
  globalKeys: ["agent_shared_system_prompt"],
  hyperparamKeys: AGENT_MODEL_HYPERPARAM_KEYS,
  hyperparamPrefix: "agent_",
};

// Profile fields that live on its endpoint row, by the name that row gives them.
const CONNECTION_COLUMNS = {
  endpoint_url: "url",
  api_key: "api_key",
  completion_mode: "completion_mode",
  proxy: "proxy",
};

// What a new profile copies from the one it starts from.
const PROFILE_COPY_FIELDS = [
  "endpoint_url",
  "api_key",
  "completion_mode",
  "proxy",
  "model_name",
  "system_prompt",
  "temperature",
  "min_p",
  "top_k",
  "top_p",
  "repetition_penalty",
  "max_tokens",
  "reasoning_effort",
  "reasoning_effort_param",
  "reasoning_effort_value",
  "extra_headers",
  "extra_body",
];

const CB_ARROW = `<span class="cb-arrow"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,4 6,8 10,4"/></svg></span>`;

function _profileOf(ctx) {
  return S.profiles.find((p) => p.id === S[ctx.configIdKey]) || null;
}

function _baseKey(ctx, key) {
  return ctx.hyperparamPrefix ? key.replace(ctx.hyperparamPrefix, "") : key;
}

function _fieldValue(ctx, key) {
  if (ctx.globalKeys.includes(key)) return S.settings[key] ?? "";
  return _profileOf(ctx)?.[_baseKey(ctx, key)] ?? "";
}

export async function toggleAgentSameAsWriter(checked) {
  S.agentSameAsWriter = checked;
  try {
    await api.put("/settings", { agent_same_as_writer: checked });
  } catch (_e) {
    toast("Failed to save agent toggle", true);
    return;
  }
  const container = document.getElementById("agent-fields");
  if (container) container.style.display = checked ? "none" : "";
  if (!checked) _fillProfileFields(AGENT_CTX);
  updateAgentModelWarning();
  renderInspector(); // the lane swap changes which endpoint gates the prefill box
}

export function renderEndpoints() {
  function renderField(f, isAgent) {
    const ctx = isAgent ? AGENT_CTX : WRITER_CTX;
    const v = _fieldValue(ctx, f.k);
    const saveFn = isAgent ? "saveAgentSetting" : "saveSetting";
    if (f.t === "textarea") {
      const rows = f.k === "system_prompt" || f.k === "agent_system_prompt" ? ' rows="2"' : "";
      const cls = f.k === "system_prompt" || f.k === "shared_system_prompt" ? " ep-chat-only" : "";
      const ph = f.ph ? ` placeholder="${escAttr(f.ph)}"` : "";
      return `<div class="field${cls}"><label>${f.l}</label>
                <textarea data-key="${f.k}"${rows}${ph} onchange="${saveFn}(this)">${v}</textarea>
              </div>`;
    }
    if (f.t === "api_key") {
      return `<div class="field"><label>${f.l}</label>
        <div class="api-key-wrap">
          <input type="text" class="api-key-input" value="${esc(v)}" data-key="${f.k}" autocomplete="off" onchange="${saveFn}(this)">
          <button type="button" class="api-key-toggle" onclick="toggleApiKeyVisibility(this)" aria-label="Show/hide API key">
            <svg class="eye-show" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            <svg class="eye-hide" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          </button>
        </div>
      </div>`;
    }
    if (f.k === "endpoint_url" || f.k === "model_name" || f.k === "agent_endpoint_url" || f.k === "agent_model_name") {
      const ph =
        f.k === "endpoint_url" || f.k === "agent_endpoint_url" ? "http://localhost:5000/v1" : "google/gemma-4-31b-it";
      const warningHtml =
        f.k === "agent_model_name"
          ? `<div id="agent-model-match-warning" class="field-warning" style="display:none">Warning: Same endpoint and model as writer detected - this increases cache cost significantly.</div>`
          : "";
      return `<div class="field"><label>${f.l}</label>
        <div class="cb-root" data-combobox="${f.k}">
          <div class="cb-control">
            <input type="text" class="cb-input" value="${v}" data-key="${f.k}" placeholder="${ph}" autocomplete="off" onchange="${saveFn}(this)">
            ${CB_ARROW}
          </div>
          <div class="cb-dropdown" hidden><div class="cb-list"></div></div>
        </div>
        ${warningHtml}
      </div>`;
    }
    if (f.t === "select") {
      const opts = f.opts
        .map(([val, label]) => `<option value="${val}"${v === val ? " selected" : ""}>${esc(label)}</option>`)
        .join("");
      return `<div class="field"><label>${f.l}</label>
                <select data-key="${f.k}" onchange="${saveFn}(this)">${opts}</select>
              </div>`;
    }
    if (f.t === "reasoning_effort") {
      const p = isAgent ? "agent_" : "";
      const paramV = _fieldValue(ctx, `${p}reasoning_effort_param`);
      const valueV = _fieldValue(ctx, `${p}reasoning_effort_value`);
      return `<div class="field"><label>${f.l}</label>
                <select data-key="${f.k}" data-desired="${esc(v)}"></select>
              </div>
              <div data-reasoning-custom="${p}" style="display:none">
                <div class="field"><label>Reasoning Param Name</label>
                  <input type="text" value="${esc(paramV)}" data-key="${p}reasoning_effort_param" placeholder="reasoning_effort">
                </div>
                <div class="field"><label>Reasoning Param Value</label>
                  <input type="text" value="${esc(valueV)}" data-key="${p}reasoning_effort_value" placeholder="high, 4096, or {&quot;effort&quot;:&quot;high&quot;}">
                </div>
              </div>`;
    }
    const attrs = f.s ? `step="${f.s}" min="${f.mn}" max="${f.mx}"` : "";
    const ph = f.ph ? ` placeholder="${esc(f.ph)}"` : "";
    return `<div class="field"><label>${f.l}</label>
              <input type="${f.t}" value="${v}" data-key="${f.k}" ${attrs}${ph} onchange="${saveFn}(this)">
            </div>`;
  }

  function renderForm(fields, isAgent) {
    const p = isAgent ? "agent_" : "";
    const byKey = new Map(fields.map((f) => [f.k, f]));
    const grouped = new Set(FIELD_GROUPS.flatMap((g) => g.keys.map((k) => p + k)));
    let html = fields
      .filter((f) => !grouped.has(f.k))
      .map((f) => renderField(f, isAgent))
      .join("");
    for (const g of FIELD_GROUPS) {
      const members = g.keys.map((k) => byKey.get(p + k)).filter(Boolean);
      if (!members.length) continue;
      html += `<details class="ep-group${g.cls || ""}">
        <summary>${g.l}</summary>
        ${members.map((f) => renderField(f, isAgent)).join("")}
      </details>`;
    }
    return html;
  }

  function renderPicker(ctx) {
    return `<div class="field"><label>${ctx.label}</label>
      <div class="ep-profile-row" data-profile-lane="${ctx.role}">
        <div class="cb-root" data-combobox="${ctx.role}_profile">
          <div class="cb-control">
            <input type="text" class="cb-input" readonly placeholder="Choose a profile" aria-label="${ctx.label}">
            ${CB_ARROW}
          </div>
          <div class="cb-dropdown" hidden><div class="cb-list"></div></div>
        </div>
        <button type="button" class="btn btn-sm btn-square" data-profile-action="new" title="New profile, copied from this one" aria-label="New profile">${PLUS_ICON}</button>
        <button type="button" class="btn btn-sm btn-square" data-profile-action="rename" title="Rename profile" aria-label="Rename profile">${EDIT_ICON}</button>
      </div>
    </div>`;
  }

  const agentHidden = S.agentSameAsWriter ? ' style="display:none"' : "";

  $("endpoints-form").innerHTML = `
    ${renderPicker(WRITER_CTX)}
    <div id="${WRITER_CTX.fieldsId}">${renderForm(SETTING_FIELDS, false)}</div>
    <div class="ep-chat-only">
      <div style="display:flex;align-items:center;gap:12px;margin:12px 0 8px"><div style="flex:1;height:1px;background:var(--accent-dim)"></div><span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--accent-dim)">Agent</span><div style="flex:1;height:1px;background:var(--accent-dim)"></div></div>
      <div class="tool-card" style="margin-bottom:12px">
        <div class="tool-card-header">
          <span class="tool-card-name">Same as Writer</span>
          <label class="tog" onclick="event.stopPropagation()">
            <input type="checkbox" ${S.agentSameAsWriter ? "checked" : ""} onchange="toggleAgentSameAsWriter(this.checked)">
            <span class="tog-slider"></span>
          </label>
        </div>
        <div class="tool-card-desc">Use the same endpoint and model for Agent passes as the Writer.</div>
      </div>
      <div id="agent-fields"${agentHidden}>
        ${renderPicker(AGENT_CTX)}
        <div id="${AGENT_CTX.fieldsId}">${renderForm(AGENT_SETTING_FIELDS, true)}</div>
      </div>
    </div>
  `;
  for (const ctx of [WRITER_CTX, AGENT_CTX]) {
    const row = document.querySelector(`[data-profile-lane="${ctx.role}"]`);
    row?.querySelector('[data-profile-action="new"]').addEventListener("click", () => _showNewProfileModal(ctx));
    row?.querySelector('[data-profile-action="rename"]').addEventListener("click", () => _showRenameProfileModal(ctx));
  }
  initComboboxes();
  updateReasoningEffortFields();
  _fillProfileFields(WRITER_CTX);
  _fillProfileFields(AGENT_CTX);
  updateAgentModelWarning();
  updateEndpointsLabel();
}

function updateReasoningEffortFields() {
  for (const prefix of ["", "agent_"]) {
    const sel = document.querySelector(`[data-key="${prefix}reasoning_effort"]`);
    if (!sel) continue;
    const save = prefix ? saveAgentSetting : saveSetting;
    const desired = sel.dataset.desired ?? sel.value ?? "";
    const levels = [...STANDARD_REASONING_LEVELS];
    if (desired && desired !== "custom" && !levels.includes(desired)) levels.push(desired);
    sel.innerHTML = [
      `<option value="">Provider default</option>`,
      ...levels.map((l) => `<option value="${esc(l)}"${desired === l ? " selected" : ""}>${esc(l)}</option>`),
      `<option value="custom"${desired === "custom" ? " selected" : ""}>Other...</option>`,
    ].join("");
    sel.value = desired;
    sel.onchange = () => {
      sel.dataset.desired = sel.value;
      save(sel);
      updateReasoningEffortFields();
    };
    const wrap = document.querySelector(`[data-reasoning-custom="${prefix}"]`);
    if (wrap) {
      wrap.style.display = desired === "custom" ? "" : "none";
      for (const input of wrap.querySelectorAll("input[data-key]")) {
        input.onchange = () => save(input);
      }
    }
  }
}

export function updateEndpointsLabel() {
  const el = document.getElementById("endpoints-label");
  if (!el) return;
  const profile = _profileOf(WRITER_CTX);
  const label = profile ? profileLabel(profile) : "";
  if (!label) {
    el.textContent = "Endpoints";
    el.title = "";
    return;
  }
  const MAX = 30;
  const EDGE = 12;
  el.textContent = label.length <= MAX ? label : `${label.slice(0, EDGE)}...${label.slice(-EDGE)}`;
  el.title = label;
}

function updateAgentModelWarning() {
  const el = document.getElementById("agent-model-match-warning");
  if (!el) return;
  if (S.agentSameAsWriter) {
    el.style.display = "none";
    return;
  }
  const writerUrlEl = document.querySelector('[data-key="endpoint_url"]');
  const writerModelEl = document.querySelector('[data-key="model_name"]');
  const agentUrlEl = document.querySelector('[data-key="agent_endpoint_url"]');
  const agentModelEl = document.querySelector('[data-key="agent_model_name"]');
  if (!writerUrlEl || !writerModelEl || !agentUrlEl || !agentModelEl) return;
  const writerUrl = writerUrlEl.value.trim();
  const writerModel = writerModelEl.value.trim();
  const agentUrl = agentUrlEl.value.trim();
  const agentModel = agentModelEl.value.trim();
  const same =
    writerUrl && agentUrl && writerUrl === agentUrl && writerModel && agentModel && writerModel === agentModel;
  el.style.display = same ? "" : "none";
}

let _comboboxCleanups = [];
// Finger travel allowed before a touch counts as a scroll rather than a tap.
const TAP_SLOP_PX = 10;
const _availableModels = new Map();
const _availableModelRequests = new Map();

function _invalidateAvailableModels(endpointId) {
  _availableModels.delete(endpointId);
  _availableModelRequests.delete(endpointId);
}

// Models other profiles already use on this server come first, and stay listed
// when the server cannot enumerate its own. Id-less, so they carry no delete button.
function _modelChoices(ctx) {
  const url = _profileOf(ctx)?.endpoint_url;
  const used = S.profiles.filter((p) => url && p.endpoint_url === url).map((p) => ({ model_name: p.model_name }));
  return mergeModelChoices(used, _availableModels.get(S[ctx.endpointIdKey]));
}

async function _loadAvailableModels(ctx) {
  const endpointId = S[ctx.endpointIdKey];
  if (!endpointId) throw new Error("Choose a profile first");
  if (_availableModels.has(endpointId)) return;

  let request = _availableModelRequests.get(endpointId);
  if (!request) {
    request = api.get(`/endpoints/${endpointId}/available-models`).then((payload) => {
      if (!Array.isArray(payload?.models)) throw new Error("Endpoint returned an invalid models response");
      if (_availableModelRequests.get(endpointId) === request) _availableModels.set(endpointId, payload.models);
    });
    _availableModelRequests.set(endpointId, request);
  }
  try {
    await request;
  } finally {
    if (_availableModelRequests.get(endpointId) === request) _availableModelRequests.delete(endpointId);
  }
}

function highlightMatch(text, query) {
  if (!query) return esc(text);
  const lText = text.toLowerCase();
  const lQuery = query.toLowerCase();
  const idx = lText.indexOf(lQuery);
  if (idx === -1) return esc(text);
  return (
    esc(text.slice(0, idx)) +
    `<mark class="cb-hl">${esc(text.slice(idx, idx + query.length))}</mark>` +
    esc(text.slice(idx + query.length))
  );
}

export function initComboboxes() {
  _comboboxCleanups.forEach((fn) => {
    fn();
  });
  _comboboxCleanups = [];
  const profileItems = () =>
    S.profiles.map((p) => ({
      value: profileLabel(p),
      id: p.id,
      type: "profile",
      title: `${p.model_name} @ ${p.endpoint_url}`,
    }));
  // Other profiles' servers, offered so a new profile can point at a known one.
  const serverItems = () =>
    [...new Set(S.profiles.map((p) => p.endpoint_url).filter(Boolean))].map((value) => ({ value, type: "endpoint" }));
  for (const ctx of [WRITER_CTX, AGENT_CTX]) {
    const isAgent = ctx === AGENT_CTX;
    const profileRoot = document.querySelector(`[data-combobox="${ctx.role}_profile"]`);
    if (profileRoot)
      initCombobox(profileRoot, profileItems, { isAgent, onSelect: (item) => _selectProfile(ctx, item.id) });
    const urlRoot = document.querySelector(`[data-combobox="${ctx.urlField}"]`);
    if (urlRoot) initCombobox(urlRoot, serverItems, { isAgent });
    const modelRoot = document.querySelector(`[data-combobox="${ctx.modelField}"]`);
    if (modelRoot)
      initCombobox(modelRoot, () => _modelChoices(ctx), {
        isAgent,
        searchable: true,
        loadItems: () => _loadAvailableModels(ctx),
      });
  }
}

window.deleteComboboxItem = (_btn, type, id) => {
  if (type === "profile") _confirmDeleteProfile(id);
};

function initCombobox(
  rootEl,
  getItems,
  { isAgent = false, searchable = false, loadItems = null, onSelect = null } = {},
) {
  const input = rootEl.querySelector(".cb-input");
  const control = rootEl.querySelector(".cb-control");
  const dropdown = rootEl.querySelector(".cb-dropdown");
  const list = rootEl.querySelector(".cb-list");
  let activeIdx = -1;
  let isOpen = false;
  let isLoading = false;
  let loadError = "";
  let destroyed = false;
  let valueBeforeInput = input.value;
  let valueBeforeSearch = input.value;
  let searchQuery = "";
  let touchTap = null;

  function getFiltered() {
    const items = getItems();
    return searchable ? filterModelChoices(items, searchQuery) : items;
  }

  function render() {
    const items = getFiltered();
    const total = items.length;
    activeIdx = Math.max(-1, Math.min(activeIdx, total - 1));
    const q = searchQuery.trim();
    const optionHtml = items
      .map((item, i) => {
        const value = item.value;
        const id = item.id;
        const type = item.type;
        const agentArg = isAgent ? ", true" : "";
        const idAttrs = id == null ? "" : ` data-id="${id}"`;
        const deleteHtml =
          id == null
            ? ""
            : `<button class="cb-delete-btn" title="Delete" onclick="event.stopPropagation(); deleteComboboxItem(this, '${type}', ${id}${agentArg})">${CLOSE_ICON}</button>`;
        const titleAttr = item.title ? ` title="${escAttr(item.title)}"` : "";
        return `
              <div class="cb-option${i === activeIdx ? " active" : ""}" data-value="${escAttr(value)}"${idAttrs} data-type="${escAttr(type)}"${titleAttr}>
                <span class="cb-option-text">${highlightMatch(value, q)}</span>
                ${deleteHtml}
              </div>`;
      })
      .join("");
    let statusHtml = "";
    if (isLoading) statusHtml = '<div class="cb-status">Loading available models…</div>';
    else if (loadError)
      statusHtml = `<div class="cb-status cb-status-error" title="${escAttr(loadError)}">Available models unavailable; type a model name.</div>`;
    else if (!total)
      statusHtml = `<div class="cb-empty">${searchable ? (q ? "No matching models" : "No available models") : "No saved options"}</div>`;
    list.innerHTML = optionHtml + statusHtml;
    list.querySelectorAll(".cb-option").forEach((el, i) => {
      el.onmousedown = (e) => {
        // The delete button wraps an inline SVG, so a click on the X targets the
        // icon rather than the button -- match with closest(), not the target's
        // own class, or mousedown selects the row and re-renders the list out
        // from under the button before its click can fire.
        if (e.target.closest(".cb-delete-btn")) return;
        e.preventDefault();
        void selectItem(items[i]);
      };
      el.onmouseenter = () => {
        activeIdx = i;
        render();
      };
    });
  }

  async function openDropdown({ revertValue = input.value, query = "" } = {}) {
    if (isOpen) return;
    isOpen = true;
    valueBeforeSearch = revertValue;
    searchQuery = searchable ? query : "";
    activeIdx = -1;
    control.classList.add("open");
    dropdown.hidden = false;
    isLoading = Boolean(loadItems);
    loadError = "";
    render();
    // A list opened near the sidebar's bottom edge would hang below its visible area.
    dropdown.scrollIntoView({ block: "nearest" });
    if (!loadItems) return;
    try {
      await loadItems();
    } catch (e) {
      loadError = e.message || "Model discovery failed";
    } finally {
      isLoading = false;
      if (!destroyed && isOpen) {
        render();
        dropdown.scrollIntoView({ block: "nearest" });
      }
    }
  }

  function closeDropdown() {
    if (!isOpen) return;
    isOpen = false;
    control.classList.remove("open");
    dropdown.hidden = true;
  }

  async function selectItem(item) {
    searchQuery = "";
    closeDropdown();
    if (onSelect) {
      await onSelect(item);
      return;
    }
    input.value = item.value;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const onInput = () => {
    if (!searchable) return;
    activeIdx = -1;
    searchQuery = input.value;
    if (!isOpen) void openDropdown({ revertValue: valueBeforeInput, query: searchQuery });
    else render();
  };
  const onBeforeInput = () => {
    if (searchable && !isOpen) valueBeforeInput = input.value;
  };
  const onKeydown = (e) => {
    if (e.key === "Escape") {
      if (isOpen) {
        e.preventDefault();
        e.stopPropagation();
        if (searchable) input.value = valueBeforeSearch;
        searchQuery = "";
        closeDropdown();
      }
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen) {
        void openDropdown();
        return;
      }
      const total = getFiltered().length;
      if (!total) return;
      activeIdx = e.key === "ArrowDown" ? (activeIdx + 1) % total : (activeIdx - 1 + total) % total;
      render();
      list.querySelector(".cb-option.active")?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && isOpen && activeIdx >= 0) {
      e.preventDefault();
      const item = getFiltered()[activeIdx];
      if (item) void selectItem(item);
    }
  };
  // A read-only picker has no text to edit, so the whole control opens it.
  const opensDropdown = (e) => input.readOnly || e.target.closest(".cb-arrow");
  const onControlDown = (e) => {
    if (!opensDropdown(e)) return;
    e.preventDefault();
    const opening = !isOpen;
    if (opening) void openDropdown();
    else closeDropdown();
    input.focus();
    if (opening && searchable) input.select();
    // Focus parks the caret at the end, which scrolls a long name to its tail.
    if (input.readOnly) input.setSelectionRange(0, 0);
  };
  const onControlTouch = (e) => {
    if (!opensDropdown(e)) return;
    e.preventDefault();
    if (isOpen) closeDropdown();
    else void openDropdown();
  };
  // Touch selects on touchend, not touchstart: a finger landing on an option is
  // usually the start of a scroll, and preventDefault-on-touchstart kills it.
  const onListTouchStart = (e) => {
    const touch = e.touches[0];
    const option = e.target.closest(".cb-option");
    touchTap =
      touch && option
        ? {
            x: touch.clientX,
            y: touch.clientY,
            scrollTop: list.scrollTop,
            option,
            deleteBtn: e.target.closest(".cb-delete-btn"),
          }
        : null;
  };
  const onListTouchMove = (e) => {
    if (!touchTap) return;
    const touch = e.touches[0];
    if (!touch) return;
    if (Math.abs(touch.clientX - touchTap.x) > TAP_SLOP_PX || Math.abs(touch.clientY - touchTap.y) > TAP_SLOP_PX)
      touchTap = null;
  };
  const onListTouchCancel = () => {
    touchTap = null;
  };
  const onListTouchEnd = (e) => {
    const tap = touchTap;
    touchTap = null;
    if (!tap || list.scrollTop !== tap.scrollTop) return;
    e.preventDefault();
    if (tap.deleteBtn) {
      window.deleteComboboxItem(tap.deleteBtn, tap.option.dataset.type, Number(tap.option.dataset.id), isAgent);
      return;
    }
    const item = getFiltered()[[...list.querySelectorAll(".cb-option")].indexOf(tap.option)];
    if (item) void selectItem(item);
  };
  const onDocDown = (e) => {
    if (!rootEl.contains(e.target)) closeDropdown();
  };
  const onDocTouch = (e) => {
    if (!rootEl.contains(e.target)) closeDropdown();
  };
  input.addEventListener("beforeinput", onBeforeInput);
  input.addEventListener("input", onInput);
  input.addEventListener("keydown", onKeydown);
  control.addEventListener("mousedown", onControlDown);
  control.addEventListener("touchstart", onControlTouch, { passive: false });
  list.addEventListener("touchstart", onListTouchStart, { passive: true });
  list.addEventListener("touchmove", onListTouchMove, { passive: true });
  list.addEventListener("touchcancel", onListTouchCancel, { passive: true });
  list.addEventListener("touchend", onListTouchEnd, { passive: false });
  document.addEventListener("mousedown", onDocDown);
  document.addEventListener("touchstart", onDocTouch, { passive: true });
  _comboboxCleanups.push(() => {
    destroyed = true;
    input.removeEventListener("beforeinput", onBeforeInput);
    input.removeEventListener("input", onInput);
    input.removeEventListener("keydown", onKeydown);
    control.removeEventListener("mousedown", onControlDown);
    control.removeEventListener("touchstart", onControlTouch);
    list.removeEventListener("touchstart", onListTouchStart);
    list.removeEventListener("touchmove", onListTouchMove);
    list.removeEventListener("touchcancel", onListTouchCancel);
    list.removeEventListener("touchend", onListTouchEnd);
    document.removeEventListener("mousedown", onDocDown);
    document.removeEventListener("touchstart", onDocTouch);
    control.classList.remove("open");
    dropdown.hidden = true;
  });
}

export async function loadEndpoints() {
  try {
    [S.endpoints, S.profiles] = await Promise.all([api.get("/endpoints"), api.get("/profiles")]);
  } catch (e) {
    console.error("Failed to load profiles:", e);
    S.endpoints = [];
    S.profiles = [];
  }
  // Settings name each lane's endpoint row, and that row names the lane's profile.
  S.activeEndpointId = S.settings.active_endpoint_id || null;
  S.activeModelConfigId = S.endpoints.find((e) => e.id === S.activeEndpointId)?.active_model_config_id || null;
  S.agentEndpointId = S.settings.agent_endpoint_id || null;
  S.agentModelConfigId = S.endpoints.find((e) => e.id === S.agentEndpointId)?.agent_active_model_config_id || null;
}

function _syncProfilePicker(ctx) {
  const profile = _profileOf(ctx);
  const row = document.querySelector(`[data-profile-lane="${ctx.role}"]`);
  const picker = row?.querySelector(".cb-input");
  if (picker) {
    picker.value = profile ? profileLabel(profile) : "";
    picker.title = profile ? `${profile.model_name} @ ${profile.endpoint_url}` : "";
    picker.setSelectionRange(0, 0);
  }
  const rename = row?.querySelector('[data-profile-action="rename"]');
  if (rename) rename.disabled = !profile;
  const fields = document.getElementById(ctx.fieldsId);
  if (fields) fields.hidden = !profile;
}

function _fillProfileFields(ctx) {
  _syncProfilePicker(ctx);
  const profile = _profileOf(ctx);
  if (!profile) return;
  const keys = [
    ctx.urlField,
    ctx.apiKeyField,
    ctx.modelField,
    ctx.completionModeField,
    ctx.proxyField,
    ...ctx.hyperparamKeys,
  ];
  for (const key of keys) {
    const el = document.querySelector(`[data-key="${key}"]`);
    if (el && !ctx.globalKeys.includes(key)) el.value = _fieldValue(ctx, key);
  }
  const reSel = document.querySelector(`[data-key="${ctx.hyperparamPrefix}reasoning_effort"]`);
  if (reSel) {
    reSel.dataset.desired = profile.reasoning_effort ?? "";
    updateReasoningEffortFields();
  }
}

function _mergeEndpoint(row) {
  const existing = S.endpoints.find((e) => e.id === row.id);
  if (existing) Object.assign(existing, row);
  for (const p of S.profiles) {
    if (p.endpoint_id !== row.id) continue;
    Object.assign(p, {
      endpoint_url: row.url,
      api_key: row.api_key,
      completion_mode: row.completion_mode,
      proxy: row.proxy,
    });
  }
}

async function _selectProfile(ctx, id) {
  const profile = S.profiles.find((p) => p.id === id);
  if (!profile) return;
  try {
    await api.put(`/endpoints/${profile.endpoint_id}`, { [ctx.activeConfigDbField]: profile.id });
    S.settings = await api.put("/settings", { [ctx.settingsEndpointField]: profile.endpoint_id });
  } catch (e) {
    toast(`Failed to select profile: ${e.message}`, true);
    return;
  }
  const row = S.endpoints.find((e) => e.id === profile.endpoint_id);
  if (row) row[ctx.activeConfigDbField] = profile.id;
  S[ctx.endpointIdKey] = profile.endpoint_id;
  S[ctx.configIdKey] = profile.id;
  _fillProfileFields(ctx);
  updateAgentModelWarning();
  updateEndpointsLabel();
  renderInspector();
}

function _showNewProfileModal(ctx) {
  const source = _profileOf(ctx);
  const hint = source ? `starts as a copy of ${esc(profileLabel(source))}` : "starts from the defaults";
  showModal(`
    <h2>New Profile</h2>
    <div class="field">
      <label>Name <span style="font-size:10px;color:var(--text-muted)">(${hint})</span></label>
      <input id="profile-name-inp" placeholder="e.g. Local Gemma" autocomplete="off">
    </div>
    <div class="modal-actions">
      <button class="btn" id="profile-name-cancel">Cancel</button>
      <button class="btn btn-accent" id="profile-name-ok">Create</button>
    </div>`);
  _wireProfileNameModal(() => _createProfile(ctx, source));
}

function _showRenameProfileModal(ctx) {
  const profile = _profileOf(ctx);
  if (!profile) return;
  showModal(`
    <h2>Rename Profile</h2>
    <div class="field">
      <label>Name</label>
      <input id="profile-name-inp" value="${escAttr(profileLabel(profile))}" autocomplete="off">
    </div>
    <div class="modal-actions">
      <button class="btn" id="profile-name-cancel">Cancel</button>
      <button class="btn btn-accent" id="profile-name-ok">Rename</button>
    </div>`);
  _wireProfileNameModal(() => _renameProfile(profile));
}

function _wireProfileNameModal(onOk) {
  const input = $("profile-name-inp");
  $("profile-name-cancel").addEventListener("click", closeModal);
  $("profile-name-ok").addEventListener("click", onOk);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") onOk();
  });
  setTimeout(() => {
    input.focus();
    input.select();
  }, 50);
}

function _profileName() {
  const name = $("profile-name-inp")?.value?.trim();
  if (!name) toast("Name is required", true);
  return name;
}

async function _createProfile(ctx, source) {
  const name = _profileName();
  if (!name) return;
  const fields = source
    ? Object.fromEntries(PROFILE_COPY_FIELDS.map((k) => [k, source[k]]))
    : { endpoint_url: "http://localhost:5000/v1", model_name: "default" };
  try {
    const profile = await api.post("/profiles", { ...fields, name });
    S.profiles.push(profile);
    S.endpoints = await api.get("/endpoints");
    closeModal();
    await _selectProfile(ctx, profile.id);
    toast("Profile created");
  } catch (e) {
    toast(`Failed to create profile: ${e.message}`, true);
  }
}

async function _renameProfile(profile) {
  const name = _profileName();
  if (!name) return;
  try {
    Object.assign(profile, await api.put(`/models/${profile.id}`, { name }));
  } catch (e) {
    toast(`Failed to rename profile: ${e.message}`, true);
    return;
  }
  closeModal();
  _syncProfilePicker(WRITER_CTX);
  _syncProfilePicker(AGENT_CTX);
  renderInteractiveFragments();
  toast("Profile renamed");
}

function _confirmDeleteProfile(id) {
  const profile = S.profiles.find((p) => p.id === id);
  if (!profile) return;
  if (S.profiles.length === 1) {
    toast("Keep at least one profile", true);
    return;
  }
  const users = S.interactiveFragments.filter((f) => f.model_config_id === id).length;
  const fallback = users
    ? ` ${users === 1 ? "One fragment runs" : `${users} fragments run`} on it and will go back to the Agent.`
    : "";
  showConfirmModal(
    {
      title: "Delete profile?",
      message: `Are you sure you want to delete the profile "${esc(profileLabel(profile))}"? This action cannot be undone.${fallback}`,
      confirmText: "Delete",
      confirmClass: "btn-danger",
    },
    () => _deleteProfile(profile),
  );
}

async function _deleteProfile(profile) {
  try {
    await api.del(`/profiles/${profile.id}`);
    [S.endpoints, S.settings] = await Promise.all([api.get("/endpoints"), api.get("/settings")]);
  } catch (e) {
    toast(`Failed to delete: ${e.message}`, true);
    return;
  }
  S.profiles = S.profiles.filter((p) => p.id !== profile.id);
  _invalidateAvailableModels(profile.endpoint_id);
  for (const f of S.interactiveFragments) if (f.model_config_id === profile.id) f.model_config_id = null;
  renderInteractiveFragments();
  for (const ctx of [WRITER_CTX, AGENT_CTX]) {
    if (S[ctx.configIdKey] !== profile.id) continue;
    S[ctx.configIdKey] = null;
    S[ctx.endpointIdKey] = null;
    _fillProfileFields(ctx);
  }
  // The Writer always runs on a profile; an Agent left without one runs on the Writer's.
  if (!S.activeModelConfigId) await _selectProfile(WRITER_CTX, S.profiles[0].id);
  updateAgentModelWarning();
  updateEndpointsLabel();
  renderInspector();
  toast("Deleted");
}

let _endpointSaveQueue = Promise.resolve();

function _saveEndpointSetting(ctx, el) {
  const next = _endpointSaveQueue.catch(() => {}).then(() => _doSaveEndpointSetting(ctx, el));
  _endpointSaveQueue = next;
  return next;
}

async function _doSaveEndpointSetting(ctx, el) {
  let v = el.value;
  if (el.type === "number") v = parseFloat(v);
  const key = el.dataset.key;
  const baseKey = _baseKey(ctx, key);
  const validation = validate.validateSetting(baseKey, v);
  if (!validation.valid) {
    toast(validation.error, true);
    return;
  }
  const profile = _profileOf(ctx);
  if (!ctx.globalKeys.includes(key) && !profile) return;
  if ((baseKey === "endpoint_url" || baseKey === "model_name") && !String(v).trim()) {
    toast(`${baseKey === "endpoint_url" ? "Endpoint URL" : "Model name"} is required`, true);
    el.value = _fieldValue(ctx, key);
    return;
  }
  try {
    if (ctx.globalKeys.includes(key)) {
      S.settings = await api.put("/settings", { [key]: v });
    } else if (CONNECTION_COLUMNS[baseKey]) {
      _mergeEndpoint(await api.put(`/endpoints/${profile.endpoint_id}`, { [CONNECTION_COLUMNS[baseKey]]: v }));
      if (baseKey !== "completion_mode") _invalidateAvailableModels(profile.endpoint_id);
    } else {
      Object.assign(profile, await api.put(`/models/${profile.id}`, { [baseKey]: v }));
    }
    toast("Settings saved");
  } catch (e) {
    toast(`Failed: ${e.message}`, true);
    return;
  }
  // Both lanes may show the same profile; the other lane's fields follow the edit.
  const other = ctx === WRITER_CTX ? AGENT_CTX : WRITER_CTX;
  if (profile && S[other.configIdKey] === profile.id) _fillProfileFields(other);
  _syncProfilePicker(WRITER_CTX);
  _syncProfilePicker(AGENT_CTX);
  updateAgentModelWarning();
  updateEndpointsLabel();
  renderInspector();
}

export async function saveSetting(el) {
  await _saveEndpointSetting(WRITER_CTX, el);
}

export async function saveAgentSetting(el) {
  await _saveEndpointSetting(AGENT_CTX, el);
}

window.saveAgentSetting = saveAgentSetting;
window.toggleAgentSameAsWriter = toggleAgentSameAsWriter;

window.toggleApiKeyVisibility = (btn) => {
  const input = btn.closest(".api-key-wrap").querySelector(".api-key-input");
  const visible = btn.dataset.visible === "1";
  if (!visible) {
    input.style.webkitTextSecurity = "none";
    btn.dataset.visible = "1";
    btn.querySelector(".eye-show").style.display = "none";
    btn.querySelector(".eye-hide").style.display = "";
  } else {
    input.style.webkitTextSecurity = "disc";
    btn.dataset.visible = "";
    btn.querySelector(".eye-show").style.display = "";
    btn.querySelector(".eye-hide").style.display = "none";
  }
};
