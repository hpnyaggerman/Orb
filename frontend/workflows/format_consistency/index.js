// Frontend entry point for the "format_consistency" workflow. The boot loader
// (loadWorkflowModules) dynamic-imports this file from the /static mount when
// the workflow is listed in the manifest. It registers a single Tools-panel
// (Secondary) card with one toggle that enables/disables the deterministic
// RP-markup normalizer, backed by the workflow's global config slot.

import { S } from "/static/state.js";
import { api } from "/static/api.js";
import { renderToolsPanel } from "/static/settings.js";

const WORKFLOW_ID = "format_consistency";

// The config slot is stored as a full replacement (not merged with defaults), so
// a persisted slot may lack this key; defaulting it to the backend
// config_defaults value keeps that case consistent.
const config = { enabled: true };

async function loadConfig() {
  try {
    const res = await api.get("/workflows/" + WORKFLOW_ID + "/config");
    const c = (res && res.config) || {};
    if (typeof c.enabled === "boolean") config.enabled = c.enabled;
  } catch (e) {
    console.warn("format_consistency: config load failed", e);
  }
  // The boot loader paints the tools panel before this async load resolves, so
  // re-render to reflect a persisted (non-default) value on the toggle.
  renderToolsPanel();
}

// Inline onchange handler (window.* pattern, like window.ttsCfgGlobal). The slot
// is replaced wholesale on write, so send the whole config — trivial for one key.
window.fcToggleEnabled = function (checked) {
  config.enabled = !!checked;
  api
    .put("/workflows/" + WORKFLOW_ID + "/config", { config: { enabled: config.enabled } })
    .catch((e) => console.warn("format_consistency: config save failed", e));
};

function configPanelRenderer() {
  return `<div class="tool-card ${config.enabled ? "tool-on" : ""}">
    <div class="tool-card-header">
      <span class="tool-card-name">Format Consistency</span>
      <label class="tog" onclick="event.stopPropagation()">
        <input type="checkbox" ${config.enabled ? "checked" : ""} onchange="window.fcToggleEnabled(this.checked)">
        <span class="tog-slider"></span>
      </label>
    </div>
    <div class="tool-card-desc">Normalize each reply's RP markup (quotes / *asterisks*) to match your recent messages.</div>
  </div>`;
}

S.workflowToolsPanelRenderers.push(configPanelRenderer);

loadConfig();
