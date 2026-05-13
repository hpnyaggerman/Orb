export const S = {
  conversations: [],
  activeConvId: null,
  activeCharId: null,
  messages: [],
  moodFragments: [],
  directorFragments: [],
  characters: [],
  personas: [],
  activePersonaId: null,
  settings: {},
  endpoints: [],
  activeEndpointId: null,
  modelConfigs: [],
  activeModelConfigId: null,
  agentSameAsWriter: true,
  agentEndpointId: null,
  agentModelConfigs: [],
  agentModelConfigId: null,
  directorState: null,
  lastDirectorData: null,
  isStreaming: false,
  streamingBodyEl: null,
  streamCutoffIndex: null,
  agentEnabled: true,
  enabledTools: {},
  lengthGuardEnabled: false,
  lengthGuardMaxWords: 240,
  lengthGuardMaxParagraphs: 4,
  lengthGuardEnforce: false,
  editingMsgId: null,
  magicInputMsgId: null,
  abortController: null,
  streamingContent: null,
  contextSize: null,
  pendingUserMsg: null,
  attachments: [],
  wasAborted: false,
  _selectCharLock: false,
  generationPhase: null,
  hideStreamingBox: false,
  reasoningDirector: "",
  reasoningWriter: "",
  reasoningEditor: "",
  reasoningPassActive: 0,
  reasoningPassSelected: 0,
  reasoningUserOverride: false,
  reasoningOpen: true,
  toolCallsOpen: false,
  injectionBlockOpen: false,
  contextSizeOpen: true,
  reasoningEnabled: { director: true, writer: false, editor: false, scripter: false },
  pendingRefineDiff: null, // {original, ops} set on writer_rewrite, cleared on next stream
  showEditorDiff: true, // when false, editor-pass diff highlights + "clear diff" button are suppressed
  hideUntilBaked: false, // when true, in-flight streaming message is kept detached from DOM until stream finalizes
  preventPromptOverrides: false, // when true, character card system_prompt and post_history_instructions are ignored
  autoscrollEnabled: true, // whether to auto-scroll chat to bottom during streaming
  _programmaticScroll: false, // true while scrollToBottom() is executing — suppresses scroll listener
  hasMultipleTabs: false, // true if multiple tabs of the app are open
  editingPendingUserMsg: false, // true when the pending (not-yet-persisted) user message is in edit mode
  pendingUserMsgEdit: null, // stores edited content for a pending user message to apply after streaming
  inspectedMsgId: null, // when set, Inspector shows director data for this message instead of current state
  inspectedDirectorData: null, // fetched director log data for the inspected message

  // Workflow slot registries -- pushed into at module load by workflow JS files.
  // Built-in chat/settings/index code iterates these; no built-in code knows about specific workflows.
  workflowInspectorCardRenderers: [], // [(msg?) => htmlString], rendered into the Inspector Secondary tab
  workflowToolsPanelRenderers: [], // [() => htmlString], rendered into the Agents panel Secondary tab
  workflowMessageButtonRenderers: [], // [(msg) => htmlString], extra per-message toolbar buttons
  workflowEventHandlers: {}, // {[event_name]: (data, msgDiv|null) => void}, custom SSE event dispatch
  workflowAttachmentRenderers: {}, // {[source]: (att, regenButtonHtml) => htmlString}, custom workflow-artifact rendering
  workflowPipelines: [], // [{id, label, passes:[{id,label}]}], pushed by registerWorkflowPipeline
  workflowState: {}, // {[workflow_id]: any}, per-workflow opaque UI state
  workflowPhases: {}, // {[channel]: label}, live status pill text per workflow channel

  workflowManifest: [], // fetched from /api/secondary-workflows at boot
  reasoningByPass: {}, // {[pass_id]: accumulatedText}, per-workflow-pipeline reasoning buffer
  inspectorTab: "main", // "main" | "secondary"
  toolsTab: "main", // "main" | "secondary"
};

const RESERVED_PASS_IDS = new Set(["director", "writer", "editor"]);

// Registers a workflow's reasoning pipeline so its pass dots and reasoning box render
// in the Inspector Secondary tab and so the SSE router can route `reasoning` events
// by `data.pass`. Validates per the pass id namespace rule: each pass id must start
// with `<workflow_id>:`, must not equal a reserved built-in pass name, and must not
// contain a second `:`. Failure path: console.error and skip registration so the
// missing rail is visible during development. Idempotent on workflow id.
export function registerWorkflowPipeline(entry) {
  if (!entry || typeof entry.id !== "string" || !entry.id) {
    console.error("registerWorkflowPipeline: missing or empty workflow id", entry);
    return;
  }
  const id = entry.id;
  const passes = Array.isArray(entry.passes) ? entry.passes : [];
  const prefix = id + ":";
  for (const p of passes) {
    if (!p || typeof p.id !== "string") {
      console.error("registerWorkflowPipeline: pass id missing for workflow", id, p);
      return;
    }
    if (RESERVED_PASS_IDS.has(p.id)) {
      console.error("registerWorkflowPipeline: pass id", p.id, "is a reserved built-in (workflow", id + ")");
      return;
    }
    if (!p.id.startsWith(prefix)) {
      console.error("registerWorkflowPipeline: pass id", p.id, "must start with", prefix);
      return;
    }
    if (p.id.indexOf(":", prefix.length) !== -1) {
      console.error("registerWorkflowPipeline: pass id", p.id, "contains a second ':'");
      return;
    }
  }
  for (const p of passes) {
    if (!(p.id in S.reasoningByPass)) S.reasoningByPass[p.id] = "";
  }
  const existing = S.workflowPipelines.findIndex((e) => e.id === id);
  const record = { id, label: entry.label || id, passes };
  if (existing >= 0) S.workflowPipelines[existing] = record;
  else S.workflowPipelines.push(record);
}
