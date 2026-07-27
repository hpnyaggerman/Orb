// Message-toolbar "generate image" action. The button shows on an assistant
// message that has no image_gen attachment yet; clicking it runs an on-demand
// render whose live progress (phase pill + reasoning rail) streams back over the
// trigger route, so a manual generation looks like the per-turn automatic one.

import { S, registerWorkflowMessageButton } from "/static/state.js";
import { convUrl } from "/static/utils.js";
import { streamPost } from "/static/sse.js";
import { setWorkflowPhase, clearWorkflowPhase, selectWorkflowPipelinePass } from "/static/chat_inspector.js";
import { refreshConversationMessages } from "/static/chat_workflow.js";

const WORKFLOW_ID = "image_gen";
const PHASE_CHANNEL = "workflow:" + WORKFLOW_ID;

const ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>`;

function hasImage(msg) {
  return (msg.workflow_attachments || []).some((a) => a.workflow_id === WORKFLOW_ID);
}

// Assistant replies only (the image depicts the reply), and only while none exists
// yet -- the button is the manual fallback when auto-generation is off or produced
// nothing. Multi-tab disables it as the edit/regen buttons do, so a single writer
// avoids racing duplicate roots onto the message.
function messageButtonRenderer(msg) {
  if (msg.role !== "assistant" || !msg.id || hasImage(msg)) return "";
  if (S.hasMultipleTabs) return `<button disabled title="Close other tabs to generate">${ICON}</button>`;
  return `<button onclick="imageGenGenerate(${msg.id}, this)" title="Generate image">${ICON}</button>`;
}

export function initGenerate() {
  window.imageGenGenerate = generate;
  registerWorkflowMessageButton(WORKFLOW_ID, messageButtonRenderer);
}

async function generate(msgId, btn) {
  if (btn) btn.disabled = true;
  setWorkflowPhase(PHASE_CHANNEL, "Generating image...");
  try {
    const resp = await streamPost(convUrl(S.activeConvId, "workflows", WORKFLOW_ID, "trigger"), {
      action: "generate",
      message_id: msgId,
    });
    if (!resp.ok || !resp.body) throw new Error("trigger failed: " + resp.status);
    await consumeStream(resp);
  } catch (e) {
    console.error("image_gen: production generate failed", e);
  } finally {
    // Backstop the per-step phase clears; the refetch surfaces the new image and
    // drops the button (its hasImage guard now passes).
    clearWorkflowPhase(PHASE_CHANNEL);
    await refreshConversationMessages(msgId);
  }
}

async function consumeStream(resp) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ") && event) {
        const ev = event;
        handleEvent(ev, line.slice(6));
        event = null;
        // The terminal event is the explicit done signal; finish on it rather than
        // waiting for the stream to close, which can stall and hang the reader.
        if (ev === "image_generated") {
          await reader.cancel();
          return;
        }
      }
    }
  }
}

function handleEvent(event, data) {
  let d;
  try {
    d = JSON.parse(data);
  } catch {
    return;
  }
  if (event === "phase_status") {
    if (d.state === "done" || !d.label) clearWorkflowPhase(d.channel);
    else setWorkflowPhase(d.channel, d.label);
  } else if (event === "reasoning" && d.pass) {
    S.reasoningByPass[d.pass] = (S.reasoningByPass[d.pass] || "") + (d.delta || "");
    // Repaint so the rail streams live while the Secondary inspector tab is open;
    // both passes are short, so a full rebuild per delta is cheap.
    if (S.inspectorTab === "secondary") selectWorkflowPipelinePass(WORKFLOW_ID, d.pass);
  }
}
