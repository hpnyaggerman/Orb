// Frontend entry point for the "image_gen" workflow. loadWorkflowModules()
// dynamic-imports this file from the /static mount when the workflow is listed
// in the manifest. It registers the Tools-panel config card and declares the
// two-pass reasoning rail. Rendered images use the framework's default image
// widget, so no attachment renderer is registered.

import { registerWorkflowPipeline, registerWorkflowToolsPanelCard } from "/static/state.js";
import { initConfigPanel, configPanelRenderer } from "./config_panel.js";
import { initGenerate } from "./generate.js";

const WORKFLOW_ID = "image_gen";

function injectStyles() {
  if (document.getElementById("image-gen-workflow-styles")) return;
  const link = document.createElement("link");
  link.id = "image-gen-workflow-styles";
  link.rel = "stylesheet";
  link.href = "/static/workflows/" + WORKFLOW_ID + "/image_gen.css";
  document.head.appendChild(link);
}

injectStyles();
initConfigPanel();
initGenerate();

registerWorkflowToolsPanelCard(WORKFLOW_ID, configPanelRenderer);
registerWorkflowPipeline({
  id: WORKFLOW_ID,
  label: "Image Generation",
  passes: [
    { id: "image_gen:analyze", label: "Scene" },
    { id: "image_gen:compose", label: "Prompt" },
  ],
});
