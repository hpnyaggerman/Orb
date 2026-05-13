import { api, getContextSize, stopConversation, streamPost } from "./api.js";
import { loadCharacters, refreshCharacters, renderCharacters } from "./library.js";
import { activateAndPrioritizeWorld, deactivateWorld } from "./lorebooks.js";
import { closeModal, showConfirmModal, showModal } from "./modal.js";
import { S } from "./state.js";
import { requestSendPermission } from "./tabLock.js";
import {
  $,
  avatarUrl,
  convUrl,
  esc,
  formatBytes,
  formatProse,
  formatProseWithDiff,
  formatRelativeDate,
  resolvePlaceholders,
  scrollToBottom,
  scrollToMessage,
  sentenceDiff,
  toast,
} from "./utils.js";
import { validate } from "./validate.js";

function canStartGeneration() {
  if (S.isStreaming) return false;
  return requestSendPermission();
}

function normalizeMessages(msgs) {
  if (!Array.isArray(msgs)) return msgs;
  for (const m of msgs) {
    if (m.attachments && Array.isArray(m.attachments)) {
      for (const att of m.attachments) {
        if (att.data_b64 != null && att.b64 == null) att.b64 = att.data_b64;
        if (att.mime_type != null && att.mime == null) att.mime = att.mime_type;
      }
    }
  }
  return msgs;
}

// Safe replacement for S.messages from a server response.
// During streaming, local-pending entries (id: null) are preserved because the
// server doesn't know about them yet — replacing blindly drops them from the DOM.
function setMessages(serverMsgs) {
  const normalized = normalizeMessages(serverMsgs);
  if (S.isStreaming) {
    const pending = S.messages.filter((m) => !m.id);
    S.messages = pending.length ? [...normalized, ...pending] : normalized;
  } else {
    S.messages = normalized;
  }
}

const ICON_EDIT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
const ICON_REGEN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/></svg>`;
const ICON_DEL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`;
const ICON_CLEAR = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/></svg>`;
const ICON_SUPER_REGEN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>`;
const ICON_MAGIC = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h.01"/><path d="M17.8 6.2 19 5"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/></svg>`;

function buildMsgToolbar(m) {
  const isAssistant = m.role === "assistant";
  const isGreeting = isAssistant && !m.parent_id;
  const childAssistant = !isAssistant ? S.messages.find((c) => c.parent_id === m.id && c.role === "assistant") : null;
  const regenTargetId = isAssistant ? m.id : childAssistant?.id;
  const canRegen = !isGreeting && (isAssistant || !!childAssistant || !!m.id);

  const editBtn = S.hasMultipleTabs
    ? `<button disabled title="Close other tabs to edit">${ICON_EDIT}</button>`
    : `<button onclick="${m.id ? `startEdit(${m.id})` : `startEditPending()`}" title="Edit">${ICON_EDIT}</button>`;

  const regenBtn = isGreeting
    ? ""
    : S.hasMultipleTabs || !canRegen
      ? `<button disabled title="${S.hasMultipleTabs ? "Close other tabs to regenerate" : ""}">${ICON_REGEN}</button>`
      : `<button onclick="${regenTargetId ? `regenerate(${regenTargetId})` : `continueFromUser()`}" title="Regenerate">${ICON_REGEN}</button>`;

  const superRegenBtn =
    isAssistant && m.id && !isGreeting
      ? S.hasMultipleTabs
        ? `<button disabled title="Close other tabs to regenerate">${ICON_SUPER_REGEN}</button>`
        : `<button onclick="superRegenerate(${m.id})" title="Super Regenerate">${ICON_SUPER_REGEN}</button>`
      : "";

  const magicBtn =
    isAssistant && m.id && !isGreeting
      ? S.hasMultipleTabs
        ? `<button disabled title="Close other tabs to use Magic">${ICON_MAGIC}</button>`
        : `<button onclick="toggleMagicInput(${m.id})" title="Magic Rewrite">${ICON_MAGIC}</button>`
      : "";

  const magicInput =
    isAssistant && m.id && !isGreeting && S.magicInputMsgId === m.id
      ? `<input class="magic-input" type="text" placeholder="Direction/Fix…" id="magic-input-${m.id}" onkeydown="handleMagicKey(event,${m.id})" autofocus>`
      : "";

  const delBtn = !m.id
    ? `<button disabled class="msg-btn-del">${ICON_DEL}</button>`
    : isGreeting
      ? ""
      : `<button onclick="deleteMessage(${m.id})" title="Delete message, siblings, and all children" class="msg-btn-del">${ICON_DEL}</button>`;

  const diffBtn =
    S.pendingRefineDiff?.msgId && m.id === S.pendingRefineDiff.msgId && S.showEditorDiff
      ? `<button onclick="clearRefineDiff()" title="Clear diff highlights" class="btn-clear-diff">${ICON_CLEAR}</button>`
      : "";

  return `${editBtn}${regenBtn}${superRegenBtn}${magicBtn}${magicInput}${_renderExtraButtons(m)}${delBtn}${diffBtn}`;
}

function _renderExtraButtons(msg) {
  if (!S.workflowMessageButtonRenderers.length) return "";
  let html = "";
  for (const fn of S.workflowMessageButtonRenderers) {
    try {
      const piece = fn(msg);
      if (typeof piece === "string" && piece) html += piece;
    } catch (e) {
      console.error("workflow message button renderer threw:", e);
    }
  }
  return html;
}

// ── Attachments rendering
function _isWorkflowAttachment(att) {
  return typeof att.source === "string" && att.source.startsWith("workflow:");
}

function renderAttachments(attachments) {
  if (!attachments || attachments.length === 0) return "";
  const userAtts = attachments.filter((a) => !_isWorkflowAttachment(a));
  if (!userAtts.length) return "";
  const items = userAtts
    .map((att) => {
      const b64 = att.b64 || att.data_b64 || "";
      const mime = att.mime || att.mime_type || "image/jpeg";
      const filename = att.filename || "image";
      const size = att.size || 0;
      return `
    <div class="attachment-item">
      <img src="data:${mime};base64,${b64}" alt="${esc(filename)}">
      <div class="attachment-info">
        <div class="attachment-name">${esc(filename)}</div>
        <div class="attachment-size">${formatBytes(size)}</div>
      </div>
    </div>
  `;
    })
    .join("");
  return `<div class="attachments">${items}</div>`;
}

// Per-instance swipe-widget index across re-renders. Default is "show the latest
// variant" so a freshly regenerated sibling lands in view immediately.
const _workflowSwipeIndexes = new Map();

function _autoRenderAttachment(att) {
  const b64 = att.b64 || att.data_b64 || "";
  const mime = att.mime || att.mime_type || "application/octet-stream";
  const filename = att.filename || att.workflow_id || "artifact";
  if (mime.startsWith("image/")) {
    return `<img class="workflow-artifact-image" src="data:${mime};base64,${b64}" alt="${esc(filename)}">`;
  }
  return `<a class="workflow-artifact-link" href="data:${mime};base64,${b64}" download="${esc(filename)}">${esc(filename)}</a>`;
}

function _workflowRegenButtonHtml(msg, att) {
  const wid = att.workflow_id;
  if (!wid) return "";
  const entry = S.workflowManifest.find((w) => w.id === wid);
  if (!entry || !entry.supports_regenerate || !entry.auto_regen_button) return "";
  return `<button class="workflow-regen-button" title="Regenerate" onclick="event.stopPropagation();workflowRegenerate(${msg.id},${att.id},this)">${ICON_REGEN}</button>`;
}

function _renderWorkflowSwipeContainer(msg, rootId, atts) {
  const instanceId = `ws-${msg.id}-${rootId}`;
  const total = atts.length;
  const stored = _workflowSwipeIndexes.get(instanceId);
  const idx = Math.min(stored ?? total - 1, total - 1);
  const active = atts[idx];
  const renderer = S.workflowAttachmentRenderers[active.source];
  const regenBtn = _workflowRegenButtonHtml(msg, active);
  let bodyHtml;
  if (typeof renderer === "function") {
    try {
      bodyHtml = renderer(active, regenBtn) || "";
    } catch (e) {
      console.error("workflow attachment renderer for", active.source, "threw:", e);
      bodyHtml = _autoRenderAttachment(active);
      if (regenBtn) bodyHtml += regenBtn;
    }
  } else {
    bodyHtml = _autoRenderAttachment(active);
    if (regenBtn) bodyHtml += regenBtn;
  }
  const indicator = total > 1 ? `<span class="workflow-artifact-counter">${idx + 1} / ${total}</span>` : "";
  const navDisabled = total <= 1 ? " disabled" : "";
  return `<div class="workflow-artifact-swipe" id="${instanceId}" data-msg-id="${msg.id}" data-root-id="${rootId}">
    <button class="workflow-swipe-btn"${navDisabled} onclick="event.stopPropagation();workflowArtifactStep('${instanceId}',-1)">&#9664;</button>
    <div class="workflow-artifact-body">${bodyHtml}</div>
    <button class="workflow-swipe-btn"${navDisabled} onclick="event.stopPropagation();workflowArtifactStep('${instanceId}',1)">&#9654;</button>
    ${indicator}
  </div>`;
}

function _workflowAttachmentGroups(msg) {
  if (!msg.attachments || !msg.attachments.length) return [];
  const workflowAtts = msg.attachments.filter(_isWorkflowAttachment);
  if (!workflowAtts.length) return [];
  const byId = new Map();
  for (const a of workflowAtts) byId.set(a.id, a);
  const groups = new Map();
  for (const a of workflowAtts) {
    const parent = a.parent_attachment_id;
    const rootId = parent && byId.has(parent) ? parent : a.id;
    if (!groups.has(rootId)) groups.set(rootId, []);
    groups.get(rootId).push(a);
  }
  const list = [];
  for (const [rootId, atts] of groups) {
    atts.sort((a, b) => a.id - b.id);
    list.push({ rootId, atts });
  }
  list.sort((a, b) => a.rootId - b.rootId);
  return list;
}

function _renderWorkflowArtifacts(msg) {
  const groups = _workflowAttachmentGroups(msg);
  if (!groups.length) return "";
  const containers = groups.map((g) => _renderWorkflowSwipeContainer(msg, g.rootId, g.atts));
  return `<div class="workflow-artifacts">${containers.join("")}</div>`;
}

window.workflowArtifactStep = function (instanceId, delta) {
  const el = document.getElementById(instanceId);
  if (!el) return;
  const msgId = Number(el.dataset.msgId);
  const rootId = Number(el.dataset.rootId);
  const msg = S.messages.find((m) => m.id === msgId);
  if (!msg) return;
  const group = _workflowAttachmentGroups(msg).find((g) => g.rootId === rootId);
  if (!group || group.atts.length <= 1) return;
  const cur = _workflowSwipeIndexes.get(instanceId) ?? group.atts.length - 1;
  let next = cur + delta;
  if (next < 0) next = group.atts.length - 1;
  if (next >= group.atts.length) next = 0;
  _workflowSwipeIndexes.set(instanceId, next);
  el.outerHTML = _renderWorkflowSwipeContainer(msg, rootId, group.atts);
};

window.workflowRegenerate = async function (msgId, attId, btn) {
  if (!S.activeConvId) return;
  const container = btn.closest(".workflow-artifact-swipe");
  btn.disabled = true;
  try {
    const result = await api.post(convUrl(S.activeConvId, "messages", msgId, "attachments", attId, "regenerate"), {});
    const newIds = Array.isArray(result?.attachments) ? result.attachments : [];
    setMessages(await api.get(convUrl(S.activeConvId, "messages")));
    const msg = S.messages.find((m) => m.id === msgId);
    if (msg && newIds.length) {
      const byId = new Map();
      for (const a of msg.attachments || []) byId.set(a.id, a);
      const original = byId.get(attId);
      if (original) {
        const rootId =
          original.parent_attachment_id && byId.has(original.parent_attachment_id)
            ? original.parent_attachment_id
            : attId;
        const group = _workflowAttachmentGroups(msg).find((g) => g.rootId === rootId);
        if (group) _workflowSwipeIndexes.set(`ws-${msgId}-${rootId}`, group.atts.length - 1);
      }
    }
    renderMessages();
  } catch (e) {
    console.error("Regenerate failed:", e);
    if (container && !container.querySelector(".workflow-regen-error")) {
      const cap = document.createElement("div");
      cap.className = "workflow-regen-error";
      cap.textContent = "Regenerate failed";
      container.appendChild(cap);
    }
  } finally {
    btn.disabled = false;
  }
};

// ── Generation Phase
const PHASE_ORDER = { pending: 0, directing: 0, generating: 1, refining: 2 };
const PHASE_LABELS = {
  pending: "Waiting for response…",
  directing: "Director analyzing scene…",
  generating: "Generating response…",
  refining: "Refining response…",
};
let _refineTimer = null;

function setGenerationPhase(phase) {
  if (!phase) {
    S.generationPhase = null;
  } else if (S.generationPhase && PHASE_ORDER[phase] < PHASE_ORDER[S.generationPhase]) {
    return; // never go backwards
  } else {
    S.generationPhase = phase;
  }
  const el = $("generation-status");
  if (!S.generationPhase) {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  el.querySelector(".gen-text").textContent = PHASE_LABELS[S.generationPhase] || "Processing…";
  el.querySelector(".gen-dot").className = "gen-dot" + (S.generationPhase === "refining" ? " spin" : "");
}

function smoothUpdateBody(el, newHtml, onComplete) {
  if (!el || el.innerHTML === newHtml) return;
  const prev = el.offsetHeight;
  el.innerHTML = newHtml;
  const next = el.scrollHeight;
  if (Math.abs(next - prev) > 4) {
    el.style.height = prev + "px";
    el.style.overflow = "hidden";
    el.offsetHeight; // force reflow
    el.style.transition = "height 0.3s ease";
    el.style.height = next + "px";
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      el.style.height = "";
      el.style.overflow = "";
      el.style.transition = "";
      onComplete?.();
    };
    el.addEventListener("transitionend", done, { once: true });
    setTimeout(done, 350); // fallback
  } else {
    onComplete?.();
  }
}

function finalizeStreamingDiv(lastMsg) {
  const body = S.streamingBodyEl;
  if (!body) return false;
  const div = body.closest(".message");
  if (!div || !div.isConnected || !lastMsg || lastMsg.role !== "assistant" || !lastMsg.id) return false;

  div.setAttribute("data-msg-id", lastMsg.id);
  body.removeAttribute("id");

  const bodyHtml =
    S.pendingRefineDiff && S.showEditorDiff
      ? formatProseWithDiff(S.pendingRefineDiff.ops)
      : formatProse(resolvePlaceholders(lastMsg.content));
  smoothUpdateBody(body, bodyHtml, () => scrollToBottom(true));

  const tb = div.querySelector(".msg-toolbar");
  if (tb) {
    tb.innerHTML = buildMsgToolbar(lastMsg);
  }

  const bc = lastMsg.branch_count || 1;
  if (bc > 1) {
    const bi = lastMsg.branch_index || 0;
    const roleEl = div.querySelector(".msg-role");
    if (roleEl && !roleEl.querySelector(".swipe-nav")) {
      roleEl.insertAdjacentHTML(
        "beforeend",
        `<span class="swipe-nav">
        <button onclick="event.stopPropagation();switchBranch(${lastMsg.prev_branch_id})" ${!lastMsg.prev_branch_id ? "disabled" : ""}>◀</button>
        <span class="swipe-counter">${bi + 1}/${bc}</span>
        <button onclick="event.stopPropagation();switchBranch(${lastMsg.next_branch_id})" ${!lastMsg.next_branch_id ? "disabled" : ""}>▶</button>
      </span>`,
      );
    }
  }

  return true;
}

function scheduleRefineTimer() {
  clearTimeout(_refineTimer);
  _refineTimer = setTimeout(() => {
    if (S.isStreaming && S.generationPhase === "generating") setGenerationPhase("refining");
  }, 1500);
}

function clearRefineTimer() {
  clearTimeout(_refineTimer);
  _refineTimer = null;
}

// ── Conversations
export async function loadConversations() {
  S.conversations = await api.get("/conversations");
}

export function resetChatUI() {
  S.activeCharId = null;
  S.activeConvId = null;
  S.messages = [];
  S.lastDirectorData = null;
  S.directorState = null;
  S.inspectedMsgId = null;
  S.inspectedDirectorData = null;
  $("chat-title-text").textContent = "Select a character";
  $("chat-avatar").textContent = "📜";
  $("chat-input").disabled = true;
  $("send-btn").disabled = true;
  renderMessages();
  renderInspector();
}

export async function selectChar(id, source = "recent") {
  if (S.isStreaming) {
    toast("Stop generation before switching characters", true);
    return;
  }
  if (S.activeCharId === id || S._selectCharLock) return;
  S._selectCharLock = true;
  try {
    const oldWorldId = (S.allCharacters || []).find((c) => c.id === S.activeCharId)?.world_id || null;
    const newWorldId = (S.allCharacters || []).find((c) => c.id === id)?.world_id || null;
    S.activeCharId = id;
    renderCharacters();
    if (oldWorldId && oldWorldId !== newWorldId) {
      await deactivateWorld(oldWorldId);
    }
    const existing = S.conversations.find((c) => c.character_card_id === id);
    if (existing) {
      // If selecting from library modal, bump conversation's updated_at
      if (source === "library") {
        try {
          await api.post(`/conversations/${existing.id}/touch`);
          // Update local conversation's updated_at to now
          existing.updated_at = new Date().toISOString();
        } catch (e) {
          // silently fail, not critical
          console.warn("Failed to touch conversation:", e);
        }
      }
      await selectConversation(existing.id);
    } else {
      try {
        const conv = await api.post("/conversations", { character_card_id: id });
        await loadConversations();
        await selectConversation(conv.id);
      } catch (e) {
        toast(e.message, true);
      }
    }
    // Refresh the recent characters panel to reflect updated timestamps
    refreshCharacters();
  } finally {
    S._selectCharLock = false;
  }
}

export async function newConvForChar(id) {
  if (S.isStreaming) {
    toast("Stop generation before switching characters", true);
    return;
  }
  try {
    const oldWorldId = (S.allCharacters || []).find((c) => c.id === S.activeCharId)?.world_id || null;
    const newWorldId = (S.allCharacters || []).find((c) => c.id === id)?.world_id || null;
    const conv = await api.post("/conversations", { character_card_id: id });
    await loadConversations();
    S.activeCharId = id;
    renderCharacters();
    if (oldWorldId && oldWorldId !== newWorldId) {
      await deactivateWorld(oldWorldId);
    }
    await selectConversation(conv.id);
  } catch (e) {
    toast(e.message, true);
  }
}

export async function selectConversation(id) {
  if (S.isStreaming) {
    toast("Stop generation before switching conversations", true);
    return;
  }
  const oldWorldId = (S.allCharacters || []).find((c) => c.id === S.activeCharId)?.world_id || null;
  S.activeConvId = id;
  S.lastDirectorData = null;
  S.reasoningDirector = "";
  S.reasoningWriter = "";
  S.reasoningEditor = "";
  S.reasoningPassActive = 0;
  S.reasoningPassSelected = 0;
  const conv = S.conversations.find((c) => c.id === id);
  if (conv?.character_card_id && S.activeCharId !== conv.character_card_id) {
    S.activeCharId = conv.character_card_id;
    renderCharacters();
  }
  $("chat-title-text").textContent = conv ? conv.title || conv.character_name : "";
  const av = $("chat-avatar");
  if (conv?.character_card_id) {
    av.innerHTML = `<img src="${avatarUrl(conv.character_card_id)}?t=${Date.now()}" onerror="this.parentElement.textContent='📜'" onclick="showAvatarPopup()" style="cursor:pointer">`;
  } else {
    av.textContent = "📜";
  }
  $("chat-input").disabled = false;
  $("send-btn").disabled = false;

  // If the character has a linked lorebook, activate it and move it to the top
  if (conv?.character_card_id) {
    const char = (S.allCharacters || []).find((c) => c.id === conv.character_card_id);
    if (char?.world_id) {
      await activateAndPrioritizeWorld(char.world_id);
    }
  }

  const newWorldId = (S.allCharacters || []).find((c) => c.id === S.activeCharId)?.world_id || null;
  if (oldWorldId && oldWorldId !== newWorldId) {
    await deactivateWorld(oldWorldId);
  }

  setMessages(await api.get(convUrl(id, "messages")));
  S.directorState = await api.get(convUrl(id, "director"));
  S.editingMsgId = null;
  S.magicInputMsgId = null;
  renderMessages();
  const lastAsst = [...S.messages].reverse().find((m) => m.role === "assistant" && m.id);
  if (lastAsst) {
    await inspectMessage(lastAsst.id);
  } else {
    clearInspectedMessage();
  }
  scrollToBottom();
}

function confirmDeleteConversation(id, msgCount, afterDelete) {
  const countNote =
    msgCount != null
      ? `<p style="color:var(--text-muted);font-size:0.88em;margin-top:8px">${msgCount} message${msgCount !== 1 ? "s" : ""} in this conversation</p>`
      : "";
  showConfirmModal(
    {
      title: "Delete Conversation",
      message: "Are you sure you want to delete this conversation?",
      confirmText: "Delete",
      extraHtml: countNote,
    },
    async () => {
      try {
        await api.del("/conversations/" + id);
        if (S.activeConvId === id) {
          S.activeConvId = null;
          S.messages = [];
          $("chat-input").disabled = true;
          $("send-btn").disabled = true;
          renderMessages();
        }
        await afterDelete();
      } catch (e) {
        toast(e.message, true);
      }
    },
  );
}

async function deleteConversation(id) {
  const conv = S.conversations.find((c) => c.id === id);
  confirmDeleteConversation(
    id,
    conv?.message_count ?? (S.activeConvId === id ? S.messages.length : null),
    loadConversations,
  );
}

export async function deleteConversationFromModal(id) {
  const conv = S.conversations.find((c) => c.id === id);
  confirmDeleteConversation(id, conv?.message_count ?? null, showConvHistoryModal);
}

export async function showConvHistoryModal() {
  if (!S.activeCharId) {
    toast("Select a character first", true);
    return;
  }
  await loadConversations();
  const convs = S.conversations.filter((c) => c.character_card_id === S.activeCharId);
  if (!convs.length) {
    toast("No conversations yet", true);
    return;
  }
  const char = S.characters.find((c) => c.id === S.activeCharId);
  const charName = char ? char.name : "Character";
  const items = convs
    .map((c) => {
      const isActive = c.id === S.activeConvId;
      const preview = esc((c.last_message_preview || "").substring(0, 80));
      const title = esc(c.title || c.character_name || "Untitled");
      const ts = c.updated_at || c.created_at;
      return `<div class="conv-history-item${isActive ? " active-conv" : ""}" onclick="closeModal();selectConversation('${c.id}')">
      <div class="conv-history-meta">
        <span class="conv-history-title">${title}</span>
        <span class="conv-history-date">${formatRelativeDate(ts)}</span>
        <button class="conv-history-delete" title="Delete conversation" onclick="event.stopPropagation();deleteConversationFromModal('${c.id}')">&#x2715;</button>
      </div>
      ${
        preview
          ? `<div class="conv-history-preview">${preview}</div>`
          : `<div class="conv-history-preview" style="color:var(--text-muted);font-style:italic">No messages yet</div>`
      }
    </div>`;
    })
    .join("");
  showModal(`
    <h2>Conversations — ${esc(charName)}</h2>
    <div class="modal-list">${items}</div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`);
}

// ── Title Edit
let _titleEditBackup = "";

export function startEditTitle() {
  if (!S.activeConvId) return;
  const conv = S.conversations.find((c) => c.id === S.activeConvId);
  if (!conv) return;
  const area = $("chat-title-text");
  if (!area) return;
  _titleEditBackup = area.textContent;

  const input = document.createElement("input");
  input.type = "text";
  input.id = "chat-title-input";
  input.className = "chat-title-input";
  input.value = _titleEditBackup;
  input.addEventListener("keydown", handleTitleEditKey);
  input.addEventListener("blur", saveTitleEdit);

  area.replaceWith(input);
  input.focus();
  input.select();
}

export function handleTitleEditKey(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    saveTitleEdit();
  }
  if (e.key === "Escape") {
    e.preventDefault();
    cancelTitleEdit();
  }
}

export async function saveTitleEdit() {
  const inp = $("chat-title-input");
  if (!inp) return;
  const newTitle = inp.value.trim();
  if (!newTitle) {
    cancelTitleEdit();
    return;
  }
  const validation = validate.validateConversationTitle(newTitle);
  if (!validation.valid) {
    toast(validation.error, true);
    cancelTitleEdit();
    return;
  }
  if (newTitle === _titleEditBackup) {
    cancelTitleEdit();
    return;
  }
  try {
    const updated = await api.put("/conversations/" + S.activeConvId, { title: newTitle });
    const conv = S.conversations.find((c) => c.id === S.activeConvId);
    if (conv) conv.title = updated.title;
    const div = document.createElement("div");
    div.className = "chat-title";
    div.id = "chat-title-text";
    div.textContent = updated.title || conv?.character_name || "";
    inp.replaceWith(div);
    _titleEditBackup = "";
    toast("Title updated");
  } catch (e) {
    toast(e.message, true);
    cancelTitleEdit();
  }
}

export function cancelTitleEdit() {
  const inp = $("chat-title-input");
  if (!inp) return;
  const div = document.createElement("div");
  div.className = "chat-title";
  div.id = "chat-title-text";
  div.textContent = _titleEditBackup;
  inp.replaceWith(div);
  _titleEditBackup = "";
}

// ── Messages
function getCharName() {
  const c = S.conversations.find((c) => c.id === S.activeConvId);
  return c?.character_name || "Assistant";
}

export function renderMessages() {
  const ct = $("chat-messages");
  const distFromBottom = ct.scrollHeight - ct.scrollTop - ct.clientHeight;
  let streamingEl = null;
  let badgeEl = null;
  if (S.isStreaming) {
    streamingEl = S.streamingBodyEl?.closest(".message") ?? null;
    badgeEl = document.getElementById("active-director-badge");
  }
  if (!S.activeConvId) {
    ct.innerHTML = '<div class="empty-state"><div class="icon">📜</div><div>Select a character to begin</div></div>';
  } else if (!S.messages.length) {
    ct.innerHTML =
      '<div class="empty-state"><div class="icon">📜</div><div>Start writing to begin the scene</div></div>';
  } else {
    let msgs = S.messages;
    if (S.isStreaming && S.streamCutoffIndex != null) {
      msgs = S.messages.slice(0, S.streamCutoffIndex);
    }
    ct.innerHTML = msgs
      .map((m) => {
        const isEditing = (S.editingMsgId !== null && S.editingMsgId === m.id) || (!m.id && S.editingPendingUserMsg);
        const bc = m.branch_count || 1;
        const bi = m.branch_index || 0;
        const branchHtml =
          bc > 1
            ? `
        <span class="swipe-nav">
          <button onclick="event.stopPropagation();switchBranch(${m.prev_branch_id})" ${!m.prev_branch_id ? "disabled" : ""}>◀</button>
          <span class="swipe-counter">${bi + 1}/${bc}</span>
          <button onclick="event.stopPropagation();switchBranch(${m.next_branch_id})" ${!m.next_branch_id ? "disabled" : ""}>▶</button>
        </span>`
            : "";
        const toolbar = isEditing ? "" : `<div class="msg-toolbar">${buildMsgToolbar(m)}</div>`;
        const taId = m.id ? `edit-textarea-${m.id}` : `edit-textarea-pending`;
        const body = isEditing
          ? `
        <div class="msg-edit-area">
          <textarea id="${taId}" rows="5">${esc(m.content)}</textarea>
          <div class="msg-edit-actions">
            <button class="btn btn-sm" onclick="${m.id ? `cancelEdit()` : `cancelEditPending()`}">Cancel</button>
            <button class="btn btn-sm btn-accent" onclick="${m.id ? `saveEdit(${m.id},'${m.role}')` : `saveEditPending()`}">Save</button>
          </div>
        </div>`
          : `<div class="msg-body">${
              S.pendingRefineDiff?.msgId && m.id === S.pendingRefineDiff.msgId && S.showEditorDiff
                ? formatProseWithDiff(S.pendingRefineDiff.ops)
                : formatProse(resolvePlaceholders(m.content))
            }</div>`;
        const attachmentsHtml = renderAttachments(m.attachments);
        const workflowArtifactsHtml = _renderWorkflowArtifacts(m);
        return `<div class="message ${m.role}" data-msg-id="${m.id}">
        <div class="msg-role">${m.role === "user" ? "You" : esc(getCharName())} ${branchHtml}</div>
        ${body}${attachmentsHtml}${workflowArtifactsHtml}${toolbar}
      </div>`;
      })
      .join("");
  }
  if (badgeEl) ct.appendChild(badgeEl);
  // Keep streaming box visible while editing; only hide if explicitly flagged
  if (streamingEl && !S.hideStreamingBox && !S.hideUntilBaked) ct.appendChild(streamingEl);
  // Restore scroll position synchronously so the browser never paints a jump.
  // Near-bottom → snap to bottom; otherwise preserve distance from bottom.
  if (distFromBottom <= 50) {
    ct.scrollTop = ct.scrollHeight;
  } else {
    ct.scrollTop = Math.max(0, ct.scrollHeight - ct.clientHeight - distFromBottom);
  }
  if (!S.isStreaming) updateContextCounter();
}

function refreshMessageToolbar(msgId) {
  if (!msgId) return;
  const msg = S.messages.find((m) => m.id === msgId);
  const toolbar = document.querySelector(`[data-msg-id="${msgId}"] .msg-toolbar`);
  if (msg && toolbar) toolbar.innerHTML = buildMsgToolbar(msg);
}

function updateContextCounter() {
  fetchContextSize();
}

async function fetchContextSize() {
  if (!S.activeConvId) return;
  try {
    const data = await getContextSize(S.activeConvId);
    if (data) {
      S.contextSize = data;
      renderContextSize();
    }
  } catch (e) {
    /* ignore */
  }
}

function renderContextSize() {
  const el = document.getElementById("inspector-context-size");
  if (!el) return;
  const data = S.contextSize;
  if (!data) {
    el.outerHTML = `<div class="inspector-block" id="inspector-context-size"><div style="color:var(--text-muted);font-size:12px;">—</div></div>`;
    return;
  }
  const total = data.total_tokens_est;
  const rows = Object.entries(data.breakdown)
    .filter(([_, v]) => v.tokens_est > 0)
    .sort((a, b) => b[1].tokens_est - a[1].tokens_est)
    .map(([key, val]) => {
      const pct = ((val.tokens_est / total) * 100).toFixed(0);
      const label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      return `<div class="ctx-row">
        <span class="ctx-label">${esc(label)}</span>
        <span class="ctx-bar"><span class="ctx-bar-fill" style="width:${pct}%"></span></span>
        <span class="ctx-tokens">${val.tokens_est.toLocaleString()}</span>
      </div>`;
    })
    .join("");
  const openAttr = S.contextSizeOpen ? " open" : "";
  el.outerHTML = `<details class="inspector-block ctx-section" id="inspector-context-size"${openAttr} ontoggle="S.contextSizeOpen=this.open;saveInspectorOpenStates()">
    <summary class="ctx-summary">
      <span class="reasoning-summary-arrow">▶</span>
      <span class="ctx-total">~${total.toLocaleString()} tokens <span class="ctx-msgs">(${data.message_count} msgs)</span></span>
    </summary>
    <div class="ctx-rows">${rows}</div>
  </details>`;
}

export function startEdit(msgId) {
  S.editingMsgId = msgId;
  S.editingPendingUserMsg = false;
  renderMessages();
  // If editing the latest message, scroll to bottom so it's at the bottom of view.
  // Otherwise, center-focus on the message being edited.
  const msgEl = document.querySelector(`[data-msg-id="${msgId}"]`);
  const isLatest = msgEl && !msgEl.nextElementSibling;
  if (isLatest) {
    scrollToBottom(true);
  } else {
    scrollToMessage(msgId);
  }
  focusEditTextarea($("edit-textarea-" + msgId), cancelEdit);
  inspectMessage(msgId);
}

export function cancelEdit() {
  S.editingMsgId = null;
  S.editingPendingUserMsg = false;
  renderMessages();
  clearInspectedMessage();
}

export async function inspectMessage(msgId) {
  if (!S.activeConvId) return;
  try {
    S.inspectedMsgId = msgId;
    S.inspectedDirectorData = await api.get(convUrl(S.activeConvId, "messages", msgId, "director-log"));
    S.reasoningDirector = S.inspectedDirectorData.reasoning_director || "";
    S.reasoningWriter = S.inspectedDirectorData.reasoning_writer || "";
    S.reasoningEditor = S.inspectedDirectorData.reasoning_editor || "";
    const highestPassIdx = S.reasoningEditor ? 2 : S.reasoningWriter ? 1 : 0;
    S.reasoningPassActive = highestPassIdx;
    S.reasoningPassSelected = highestPassIdx;
    S.reasoningUserOverride = false;
    renderInspector();
  } catch (e) {
    // If the log doesn't exist (e.g. very old messages before logs were added), silently ignore
    S.inspectedDirectorData = null;
    renderInspector();
  }
}

export function clearInspectedMessage() {
  S.inspectedMsgId = null;
  S.inspectedDirectorData = null;
  renderInspector();
}

function focusEditTextarea(ta, onEscape) {
  if (!ta) return;
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onEscape();
    }
  });
  ta.focus();
  ta.selectionStart = ta.selectionEnd = ta.value.length;
  ta.style.height = "auto";
  const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 20;
  ta.style.height = Math.max(lineH * 3, ta.scrollHeight) + "px";
}

export async function deleteMessage(msgId) {
  if (S.isStreaming) return;
  showConfirmModal(
    {
      title: "Delete Message",
      message: "Delete this message, all its siblings, and all their children?",
      confirmText: "Delete",
    },
    async () => {
      try {
        setMessages(await api.del(convUrl(S.activeConvId, "messages", msgId)));
        S.lastDirectorData = null;
        // Re-fetch director state so moods are correct after deletion
        S.directorState = await api.get(convUrl(S.activeConvId, "director"));
        renderMessages();
        clearInspectedMessage();
        scrollToBottom();
        toast("Message deleted");
      } catch (e) {
        toast(e.message, true);
      }
    },
  );
}

export async function switchBranch(msgId) {
  if (!msgId || S.isStreaming) return;
  try {
    // Use the parent user message as scroll anchor so the viewport doesn't jump
    const currentBranchMsg = S.messages.find((m) => m.next_branch_id === msgId || m.prev_branch_id === msgId);
    const anchorMsgId = currentBranchMsg?.parent_id ?? null;

    const ct = $("chat-messages");
    const anchorEl = anchorMsgId ? ct?.querySelector(`[data-msg-id="${anchorMsgId}"]`) : null;
    const anchorOffset = anchorEl ? anchorEl.offsetTop - ct.scrollTop : null;
    const scrollTop = ct ? ct.scrollTop : 0;

    setMessages(await api.post(convUrl(S.activeConvId, "messages", msgId, "switch-branch"), {}));
    S.lastDirectorData = null;
    // Re-fetch director state so moods are correct for this branch
    S.directorState = await api.get(convUrl(S.activeConvId, "director"));
    renderMessages();
    await inspectMessage(msgId);

    if (anchorMsgId && anchorOffset !== null) {
      const newAnchorEl = ct.querySelector(`[data-msg-id="${anchorMsgId}"]`);
      if (newAnchorEl) ct.scrollTop = newAnchorEl.offsetTop - anchorOffset;
      else ct.scrollTop = scrollTop;
    } else if (ct) {
      ct.scrollTop = scrollTop;
    }
  } catch (e) {
    toast(e.message, true);
  }
}

// Shared gate for arrow-key / touch-swipe branch navigation. Returns true if
// we should ignore the gesture entirely (typing, streaming, modal open, …).
function isChatNavBlocked(target) {
  if (target) {
    const tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable) return true;
  }
  if ($("modal-root")?.innerHTML || $("modal-crop-root")?.innerHTML) return true;
  if (!S.activeConvId) return true;
  if (S.editingMsgId != null || S.editingPendingUserMsg) return true;
  return false;
}

// Swipe to the prev (dir = -1) or next (dir = +1) branch of the last branched
// message. Returns true if a switch was issued.
function navigateLastBranch(dir) {
  if (S.isStreaming) return false;
  const msgs = S.messages || [];
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if ((m.branch_count || 1) > 1) {
      const target = dir < 0 ? m.prev_branch_id : m.next_branch_id;
      if (target) {
        switchBranch(target);
        return true;
      }
      return false;
    }
  }
  return false;
}

// ── Keyboard navigation for the chat window:
// ←/→ swipe branches on the last branched message, ↑/↓ scroll the chat.
export function handleChatKeyNav(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  const key = e.key;
  if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "ArrowUp" && key !== "ArrowDown") return;
  if (isChatNavBlocked(e.target)) return;

  if (key === "ArrowLeft" || key === "ArrowRight") {
    if (navigateLastBranch(key === "ArrowLeft" ? -1 : 1)) e.preventDefault();
    return;
  }

  const ct = $("chat-messages");
  if (!ct) return;
  e.preventDefault();
  ct.scrollTop += key === "ArrowUp" ? -60 : 60;
}

// ── Touch swipe navigation: horizontal swipe on the chat area switches
// branches, mirroring the ←/→ keyboard behavior. Vertical-dominant motion is
// ignored so scrolling still works.
export function initChatSwipeNav() {
  const ct = $("chat-messages");
  if (!ct) return;

  const SWIPE_MIN_DX = 50; // px of horizontal travel required
  const SWIPE_MAX_DT = 600; // ms — anything slower is treated as a scroll
  const SWIPE_RATIO = 1.5; // |dx| must exceed |dy| by this factor

  let startX = 0;
  let startY = 0;
  let startT = 0;
  let active = false;

  ct.addEventListener(
    "touchstart",
    (e) => {
      if (e.touches.length !== 1) {
        active = false;
        return;
      }
      // Let taps on the existing swipe buttons / toolbar pass through normally
      const tgt = e.target;
      if (tgt?.closest?.(".swipe-nav, .msg-toolbar, .msg-edit-area, button, a, input, textarea")) {
        active = false;
        return;
      }
      if (isChatNavBlocked(tgt)) {
        active = false;
        return;
      }
      const t = e.touches[0];
      startX = t.clientX;
      startY = t.clientY;
      startT = Date.now();
      active = true;
    },
    { passive: true },
  );

  ct.addEventListener(
    "touchend",
    (e) => {
      if (!active) return;
      active = false;
      const t = e.changedTouches[0];
      if (!t) return;
      const dx = t.clientX - startX;
      const dy = t.clientY - startY;
      const dt = Date.now() - startT;
      if (dt > SWIPE_MAX_DT) return;
      if (Math.abs(dx) < SWIPE_MIN_DX) return;
      if (Math.abs(dx) < Math.abs(dy) * SWIPE_RATIO) return;
      if (isChatNavBlocked(e.target)) return;
      // Swipe left (finger moves left → dx < 0) advances to next, like ▶.
      navigateLastBranch(dx < 0 ? 1 : -1);
    },
    { passive: true },
  );
}

// ── Edit Message
export async function saveEdit(msgId, role) {
  const ta = $("edit-textarea-" + msgId);
  if (!ta) return;
  const content = ta.value;
  const validation = validate.validateEditMessage(content);
  if (!validation.valid) {
    toast(validation.error, true);
    return;
  }
  const trimmed = content.trim();
  S.editingMsgId = null;
  S.editingPendingUserMsg = false;
  try {
    await api.post(convUrl(S.activeConvId, "messages", msgId, "edit"), { content, regenerate: false });
    if (S.isStreaming) {
      // Don't replace S.messages during streaming — it would evict any pending
      // user message that the server hasn't persisted yet, making it vanish from the DOM.
      const idx = S.messages.findIndex((m) => m.id === msgId);
      if (idx >= 0) S.messages[idx].content = content;
    } else {
      setMessages(await api.get(convUrl(S.activeConvId, "messages")));
    }
    renderMessages();
    toast("Message edited");
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Edit Pending Message
export function startEditPending() {
  S.editingPendingUserMsg = true;
  S.editingMsgId = null;
  renderMessages();
  focusEditTextarea($("edit-textarea-pending"), cancelEditPending);
}

export async function saveEditPending() {
  const ta = $("edit-textarea-pending");
  if (!ta) return;
  const content = ta.value;
  const validation = validate.validateEditMessage(content);
  if (!validation.valid) {
    toast(validation.error, true);
    return;
  }
  const trimmed = content.trim();
  S.editingPendingUserMsg = false;

  // Update the pending message in S.messages so the UI reflects the edit immediately
  const pendingIdx = S.messages.findLastIndex((m) => m.role === "user" && !m.id);
  if (pendingIdx >= 0) {
    S.messages[pendingIdx].content = trimmed;
  }

  // If the message already has a backend ID, save immediately; otherwise queue for later
  const lastUser = S.messages.findLast((m) => m.role === "user");
  if (lastUser?.id) {
    saveEdit(lastUser.id, "user");
    return;
  }
  S.pendingUserMsgEdit = trimmed;

  renderMessages();
}

export function cancelEditPending() {
  S.editingPendingUserMsg = false;
  renderMessages();
}

function updateUserMessageBody(msgId, content) {
  const div = document.querySelector(`.message.user[data-msg-id="${msgId}"]`);
  if (!div) return;
  const body = div.querySelector(".msg-body");
  if (body) body.innerHTML = formatProse(resolvePlaceholders(content));
}

// ── Streaming Helpers
function setStreaming(active) {
  S.isStreaming = active;
  $("send-btn").style.display = active ? "none" : "flex";
  $("stop-btn").style.display = active ? "flex" : "none";
  const cm = $("chat-messages");
  if (cm) cm.classList.toggle("streaming", active);
}

export function stopGeneration() {
  if (S.abortController) S.abortController.abort();
  if (S.activeConvId) {
    stopConversation(S.activeConvId);
  }
}

function createStreamingDiv() {
  const div = document.createElement("div");
  div.className = "message assistant";
  div.innerHTML = `<div class="msg-role">${esc(getCharName())}</div>
    <div class="msg-body" id="streaming-body">
      <span class="typing-indicator"><span></span><span></span><span></span></span>
    </div>
    <div class="msg-toolbar">
      <button disabled>${ICON_EDIT}</button>
      <button disabled>${ICON_REGEN}</button>
      <button disabled class="msg-btn-del">${ICON_DEL}</button>
    </div>`;
  S.streamingBodyEl = div.querySelector(".msg-body");
  return div;
}

function patchParentUserMessage(assistantMsg) {
  if (!assistantMsg?.parent_id || S.hasMultipleTabs) return;
  const userDiv = document.querySelector(`.message.user[data-msg-id="${assistantMsg.parent_id}"]`);
  if (!userDiv) return;
  const regenBtn = userDiv.querySelector('.msg-toolbar [title="Regenerate"]');
  if (regenBtn) regenBtn.setAttribute("onclick", `regenerate(${assistantMsg.id})`);
}

function patchPendingUserMessage(pendingMsg) {
  const freshMsg = S.messages.find((m) => m.role === "user" && m.id && m.content === pendingMsg.content);
  if (!freshMsg) return;
  const div = document.querySelector('.message.user[data-msg-id="null"]');
  if (!div) return;
  div.setAttribute("data-msg-id", freshMsg.id);
  const tb = div.querySelector(".msg-toolbar");
  if (tb) tb.innerHTML = buildMsgToolbar(freshMsg);
}

async function afterStream() {
  const preservedContent = S.streamingContent;
  const pendingUserMsg = S.pendingUserMsg || null;
  const wasAborted = S.wasAborted;
  S.abortController = null;
  S.streamCutoffIndex = null;
  S.streamingContent = null;
  S.pendingUserMsg = null;
  S.wasAborted = false;
  S.hideStreamingBox = false; // Ensure streaming box is visible after streaming ends
  clearRefineTimer();
  setGenerationPhase(null);

  if (!S.activeConvId) {
    S.streamingBodyEl = null;
    setStreaming(false);
    $("send-btn").disabled = false;
    renderMessages();
    clearInspectedMessage();
    return;
  }

  if (wasAborted) {
    await new Promise((r) => setTimeout(r, 500));
  }

  try {
    setMessages(await api.get(convUrl(S.activeConvId, "messages")));
    S.directorState = await api.get(convUrl(S.activeConvId, "director"));
    // Update the conversation's updated_at timestamp so refreshCharacters() can
    // correctly place the active character at the top of the recent list.
    if (S.activeConvId) {
      const conv = S.conversations?.find((c) => c.id === S.activeConvId);
      if (conv) conv.updated_at = new Date().toISOString();
    }
  } catch (e) {
    toast("Failed to sync messages: " + e.message, true);
  }

  if (pendingUserMsg) {
    const hasUserMsg = S.messages.some((m) => m.role === "user" && m.content === pendingUserMsg.content);
    if (!hasUserMsg) {
      if (S.pendingUserMsgEdit) {
        pendingUserMsg.content = S.pendingUserMsgEdit;
      }
      S.messages.push(pendingUserMsg);
    }
  }
  S.pendingUserMsgEdit = null;

  if (preservedContent?.trim()) {
    const lastMsg = S.messages[S.messages.length - 1];
    if (!lastMsg || lastMsg.role !== "assistant") {
      S.messages.push({
        role: "assistant",
        content: preservedContent,
        id: null,
        branch_count: 1,
        branch_index: 0,
        prev_branch_id: null,
        next_branch_id: null,
      });
    }
  }

  setStreaming(false);
  $("send-btn").disabled = false;

  // Anchor the pending diff to the specific message ID it was generated for,
  // so branch navigation doesn't show stale diffs on the wrong message.
  if (S.pendingRefineDiff) {
    const lastAssistant = [...S.messages].reverse().find((m) => m.role === "assistant" && m.id);
    S.pendingRefineDiff.msgId = lastAssistant?.id ?? null;
  }

  // Finalize the streaming div in-place — no DOM destruction, no flash
  const lastMsg = S.messages[S.messages.length - 1];
  const finalized = finalizeStreamingDiv(lastMsg);
  S.streamingBodyEl = null;

  if (finalized) {
    // Streaming div already updated in-place — no full re-render needed.
    // Only patch the pending user message if one exists (sendMessage path).
    if (pendingUserMsg) patchPendingUserMessage(pendingUserMsg);
    patchParentUserMessage(lastMsg);
    updateContextCounter();
    // Magic rewrite updates a message in-place, so subsequent messages survive on the
    // backend but were hidden by streamCutoffIndex during streaming. Re-render if any
    // are missing from the DOM.
    const ct = $("chat-messages");
    if (ct.querySelectorAll(".message[data-msg-id]").length < S.messages.length) {
      renderMessages();
    }
  } else {
    renderMessages();
  }
  clearInspectedMessage();
  scrollToBottom(true);
  refreshCharacters();
}

async function processSSEStream(resp, container, msgDiv, signal) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    fullResponse = "",
    rewrittenResponse = null,
    firstToken = true,
    currentEvent = null;

  // Clear any diff from the previous turn
  S.pendingRefineDiff = null;

  // Reset reasoning state for this generation turn
  S.reasoningDirector = "";
  S.reasoningWriter = "";
  S.reasoningEditor = "";
  S.reasoningPassActive = 0; // tracks streaming progress (for dot lighting)
  S.reasoningPassSelected = 0; // tracks what the user is viewing
  S.reasoningUserOverride = false; // true when user has manually clicked a dot

  if (signal) signal.addEventListener("abort", () => reader.cancel());

  while (true) {
    const { done, value } = await reader.read();
    if (done || signal?.aborted) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        const data = line.slice(6);
        handleSSEEvent(
          currentEvent,
          data,
          container,
          msgDiv,
          () => {
            if (firstToken) {
              firstToken = false;
              if (!msgDiv.isConnected && !S.hideUntilBaked) container.appendChild(msgDiv);
              if (S.streamingBodyEl) S.streamingBodyEl.innerHTML = "";
            }
            fullResponse += data.replace(/\\n/g, "\n");
            S.streamingContent = rewrittenResponse || fullResponse;
            if (S.streamingBodyEl) S.streamingBodyEl.innerHTML = formatProse(rewrittenResponse || fullResponse);
            scrollToBottom();
          },
          (text) => {
            rewrittenResponse = text;
            S.streamingContent = text;
            if (S.streamingBodyEl) {
              const html =
                S.pendingRefineDiff && S.showEditorDiff
                  ? formatProseWithDiff(S.pendingRefineDiff.ops)
                  : formatProse(text);
              smoothUpdateBody(S.streamingBodyEl, html, scrollToBottom);
            } else {
              scrollToBottom();
            }
          },
        );
        currentEvent = null;
      }
    }
  }
  // reader.cancel() resolves read() with done:true rather than throwing, so
  // re-throw here so callers can set S.wasAborted and wait for the backend.
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
}

function handleSSEEvent(event, data, container, msgDiv, onToken, onRewrite) {
  switch (event) {
    case "director_start":
      setGenerationPhase("directing");
      S.lastDirectorData = null;
      S.inspectedMsgId = null;
      S.inspectedDirectorData = null;
      renderInspector();
      break;
    case "director_done": {
      try {
        S.lastDirectorData = JSON.parse(data);
      } catch (_) {}
      _advanceReasoningPass(1); // director done → move to Writer dot
      renderInspector();
      break;
    }
    case "prompt_rewritten":
      try {
        const d = JSON.parse(data);
        const lastUser =
          [...S.messages].reverse().find((m) => m.role === "user" && !m.id) ||
          [...S.messages].reverse().find((m) => m.role === "user");
        if (lastUser) lastUser.content = d.refined_message;
        if (S.pendingUserMsg) S.pendingUserMsg.content = d.refined_message;
        if (S.isStreaming) {
          const userBodies = document.querySelectorAll("#chat-messages .message.user .msg-body");
          const last = userBodies[userBodies.length - 1];
          if (last) last.innerHTML = formatProse(d.refined_message);
        } else {
          renderMessages();
        }
      } catch (_) {}
      break;
    case "token":
      setGenerationPhase("generating");
      onToken();
      scheduleRefineTimer();
      break;
    case "writer_rewrite":
      clearRefineTimer();
      setGenerationPhase("refining");
      _advanceReasoningPass(2); // writer done, editor starting → move to Editor dot
      try {
        const refined = JSON.parse(data).refined_text;
        // S.streamingContent still holds the writer's unrefined text at this point
        const original = resolvePlaceholders(S.streamingContent || "");
        const refinedResolved = resolvePlaceholders(refined);
        S.pendingRefineDiff = { original, ops: sentenceDiff(original, refinedResolved) };
        onRewrite(refined);
      } catch (_) {}
      break;
    case "reasoning": {
      try {
        const d = JSON.parse(data);
        const passKey = d.pass;
        const delta = d.delta;
        const builtinIdx = REASONING_PASSES.findIndex((p) => p.key === passKey);
        if (builtinIdx >= 0) {
          // Built-in pass: append delta to the named state and update the Main reasoning box.
          const stateKey = "reasoning" + passKey.charAt(0).toUpperCase() + passKey.slice(1);
          S[stateKey] = (S[stateKey] || "") + delta;
          const rebuilt = _advanceReasoningPass(builtinIdx);
          const viewingThisPass = S.reasoningPassSelected === builtinIdx;
          const box = document.getElementById("reasoning-box");
          if (box && viewingThisPass) {
            // Skip the append when _advanceReasoningPass already rebuilt the section
            // from the (now-current) state; appending again would duplicate this delta.
            // Text node append (not `textContent += ...`) avoids the DOM re-serialisation
            // that produced the visible scrollbar wobble on long streams.
            if (!rebuilt) box.appendChild(document.createTextNode(delta));
            box.scrollTop = box.scrollHeight;
          }
          // When the box is absent (Inspector closed, or user is on the Secondary tab)
          // state accumulates silently; renderInspector will paint the full text the
          // next time it runs.
          break;
        }
        const pipeline = S.workflowPipelines.find((p) => p.passes.some((pp) => pp.id === passKey));
        if (pipeline) {
          S.reasoningByPass[passKey] = (S.reasoningByPass[passKey] || "") + delta;
          if (S.inspectorTab === "secondary") {
            const wbox = document.getElementById("reasoning-box-" + pipeline.id);
            if (wbox && wbox.dataset.passId === passKey) {
              wbox.appendChild(document.createTextNode(delta));
              wbox.scrollTop = wbox.scrollHeight;
            }
          }
          break;
        }
        console.warn("Unrouted reasoning event for pass id:", passKey, d);
      } catch (_) {}
      break;
    }
    case "phase_status": {
      try {
        const d = JSON.parse(data);
        const channel = d.channel;
        if (typeof channel === "string" && channel.startsWith("workflow:")) {
          const label = typeof d.label === "string" ? d.label : "";
          const done = d.state === "done" || !label.trim();
          if (done) delete S.workflowPhases[channel];
          else S.workflowPhases[channel] = label;
          _renderWorkflowPhasesPill();
        }
      } catch (_) {}
      break;
    }
    case "editor_done": {
      try {
        const d = JSON.parse(data);
        if (d.tool_calls?.length) {
          if (!S.lastDirectorData) S.lastDirectorData = {};
          S.lastDirectorData.tool_calls = [...(S.lastDirectorData.tool_calls || []), ...d.tool_calls];
          renderInspector();
        }
      } catch (_) {}
      break;
    }
    case "user_message_created": {
      try {
        const d = JSON.parse(data);
        const realId = d.id;
        if (!realId) break;
        // Find the pending user message (most recent user message without an id)
        const pendingIdx = S.messages.findLastIndex((m) => m.role === "user" && !m.id);
        if (pendingIdx >= 0) {
          S.messages[pendingIdx].id = realId;
        }
        if (S.pendingUserMsg) {
          S.pendingUserMsg.id = realId;
        }
        // If the user is currently editing the pending message, transition to normal edit mode
        if (S.editingPendingUserMsg) {
          S.editingPendingUserMsg = false;
          S.editingMsgId = realId;
          renderMessages();
          const ta = $("edit-textarea-" + realId);
          if (ta) {
            ta.focus();
            ta.selectionStart = ta.selectionEnd = ta.value.length;
          }
        } else {
          // Patch the DOM element's data-msg-id and toolbar
          const div = document.querySelector('.message.user[data-msg-id="null"]');
          if (div) {
            div.setAttribute("data-msg-id", realId);
            const tb = div.querySelector(".msg-toolbar");
            if (tb) tb.innerHTML = buildMsgToolbar({ id: realId, role: "user" });
          }
        }
        // If an edit was already queued before the ID arrived, apply it now
        if (S.pendingUserMsgEdit) {
          api
            .post(convUrl(S.activeConvId, "messages", realId, "edit"), {
              content: S.pendingUserMsgEdit,
              regenerate: false,
            })
            .catch((e) => toast("Failed to save pending edit: " + e.message, true));
          // Optimistically update local content
          if (pendingIdx >= 0) {
            S.messages[pendingIdx].content = S.pendingUserMsgEdit;
            updateUserMessageBody(realId, S.pendingUserMsgEdit);
          }
          S.pendingUserMsgEdit = null;
        }
      } catch (_) {}
      break;
    }
    case "error":
      toast("Error: " + data, true);
      break;
    default: {
      const handler = S.workflowEventHandlers[event];
      if (typeof handler === "function") {
        let parsed = data;
        try {
          parsed = JSON.parse(data);
        } catch (_) {}
        try {
          handler(parsed, msgDiv || null);
        } catch (e) {
          console.error("workflow event handler for", event, "threw:", e);
        }
      }
      break;
    }
  }
}

function agentPayload() {
  return { enable_agent: S.agentEnabled };
}

async function runStreamRequest(path, body, cutoffMsgId = null) {
  setStreaming(true);
  setGenerationPhase("pending");
  $("send-btn").disabled = true;

  if (cutoffMsgId != null) {
    const idx = S.messages.findIndex((m) => m.id === cutoffMsgId);
    S.streamCutoffIndex = idx >= 0 ? idx : S.messages.length;
    S.autoscrollEnabled = true;
  }

  renderMessages();
  const ct = $("chat-messages");
  const msgDiv = createStreamingDiv();
  if (!S.hideUntilBaked) ct.appendChild(msgDiv);
  scrollToBottom();
  S.abortController = new AbortController();
  try {
    const resp = await streamPost(path, body, S.abortController.signal);
    await processSSEStream(resp, ct, msgDiv, S.abortController.signal);
  } catch (e) {
    if (e.name === "AbortError") S.wasAborted = true;
    else toast("Error: " + e.message, true);
  }
  await afterStream();
}

export async function continueFromUser() {
  if (!S.activeConvId || !canStartGeneration()) return;
  const lastMsg = S.messages[S.messages.length - 1];
  if (lastMsg?.role !== "user") {
    toast("Last message is not a user message", true);
    return;
  }
  await runStreamRequest(convUrl(S.activeConvId, "continue"), agentPayload());
}

// ── Send Message
export async function sendMessage() {
  if (!S.activeConvId || !canStartGeneration()) return;

  const inp = $("chat-input");
  let content = inp.value.trim();

  // Guard against double user turns: if the last message is already from the user,
  // ask the backend to generate a response for it without creating a new message.
  const lastMsg = S.messages[S.messages.length - 1];
  if (lastMsg?.role === "user" && lastMsg.id) {
    inp.value = "";
    inp.style.height = "auto";
    await continueFromUser();
    return;
  }

  if (!content) return;

  // Resolve {{user}} and {{char}} placeholders before sending
  content = resolvePlaceholders(content);

  setStreaming(true);
  setGenerationPhase("pending");
  inp.value = "";
  inp.style.height = "auto";
  $("send-btn").disabled = true;

  const attachments = [...S.attachments];
  S.attachments.length = 0;
  updateAttachmentPreview();
  const userMsg = {
    role: "user",
    content,
    id: null,
    branch_count: 1,
    branch_index: 0,
    prev_branch_id: null,
    next_branch_id: null,
    attachments,
  };
  S.messages.push(userMsg);
  S.pendingUserMsg = userMsg;
  renderMessages();

  const ct = $("chat-messages");
  const msgDiv = createStreamingDiv();
  if (!S.hideUntilBaked) ct.appendChild(msgDiv);
  scrollToBottom();

  S.abortController = new AbortController();
  try {
    const resp = await streamPost(
      convUrl(S.activeConvId, "send"),
      { content, attachments, ...agentPayload() },
      S.abortController.signal,
    );
    await processSSEStream(resp, ct, msgDiv, S.abortController.signal);
  } catch (e) {
    if (e.name === "AbortError") {
      S.wasAborted = true;
    } else {
      toast("Connection error: " + e.message, true);
    }
  }
  await afterStream();
}

// ── Regenerate
export async function regenerate(msgId) {
  if (!S.activeConvId || !canStartGeneration()) return;
  await runStreamRequest(convUrl(S.activeConvId, "messages", msgId, "regenerate"), agentPayload(), msgId);
}

// ── Super Regenerate
export async function superRegenerate(msgId) {
  if (!S.activeConvId || !canStartGeneration()) return;
  await runStreamRequest(convUrl(S.activeConvId, "messages", msgId, "super_regenerate"), agentPayload(), msgId);
}

// ── Magic Rewrite
export function toggleMagicInput(msgId) {
  S.magicInputMsgId = S.magicInputMsgId === msgId ? null : msgId;
  renderMessages();
  if (S.magicInputMsgId !== msgId) return;

  requestAnimationFrame(() => {
    const el = document.getElementById(`magic-input-${msgId}`);
    if (el) el.focus();
  });

  const onMouseDown = (e) => {
    const el = document.getElementById(`magic-input-${msgId}`);
    if (el?.contains(e.target)) return;
    // If the magic button itself was clicked, its onclick will handle the toggle.
    if (e.target.closest(`[onclick="toggleMagicInput(${msgId})"]`)) {
      document.removeEventListener("mousedown", onMouseDown);
      return;
    }
    document.removeEventListener("mousedown", onMouseDown);
    if (S.magicInputMsgId === msgId) {
      S.magicInputMsgId = null;
      renderMessages();
    }
  };
  document.addEventListener("mousedown", onMouseDown);
}

export function handleMagicKey(event, msgId) {
  if (event.key === "Enter") {
    event.preventDefault();
    submitMagicRewrite(msgId);
  } else if (event.key === "Escape") {
    S.magicInputMsgId = null;
    renderMessages();
  }
}

export async function submitMagicRewrite(msgId) {
  const input = document.getElementById(`magic-input-${msgId}`);
  if (!input) return;
  const direction = input.value.trim();
  if (!direction) return;
  if (!S.activeConvId || !canStartGeneration()) return;
  S.magicInputMsgId = null;
  await runStreamRequest(convUrl(S.activeConvId, "messages", msgId, "magic_rewrite"), { direction }, msgId);
}

// ── Inspector — Reasoning stepper rail

const REASONING_PASSES = [
  { key: "director", label: "Director", color: "var(--accent-dim)" },
  { key: "writer", label: "Writer", color: "var(--accent-dim)" },
  { key: "editor", label: "Editor", color: "var(--accent-dim)" },
];

// Advance the streaming-progress dot to `targetIdx` when it is further ahead.
// Auto-follows the streaming pass into the selected view only while the user
// has not manually clicked a dot this turn: once `reasoningUserOverride` is
// set, subsequent transitions leave the selection alone so the user's click
// survives until the next turn (which resets the flag in `processSSEStream`).
// Returns true if the reasoning section was rebuilt -- callers that just
// updated state and would otherwise append the same delta into the freshly
// painted box use this to skip their per-chunk append.
function _advanceReasoningPass(targetIdx) {
  if (targetIdx <= S.reasoningPassActive) return false;
  S.reasoningPassActive = targetIdx;
  if (!S.reasoningUserOverride) {
    const targetKey = REASONING_PASSES[targetIdx]?.key;
    const targetEnabled = targetKey && S.reasoningEnabled[targetKey] !== false;
    if (targetEnabled) S.reasoningPassSelected = targetIdx;
  }
  const existing = document.getElementById("reasoning-section");
  if (!existing) return false;
  _refreshReasoningSection();
  return true;
}

function _buildReasoningHtml() {
  // reasoningPassActive tracks streaming progress (for dot lighting/lines).
  // reasoningPassSelected tracks what the user is viewing.
  const streamIdx = S.reasoningPassActive;
  const selectedIdx = S.reasoningPassSelected;
  const dotsHtml = REASONING_PASSES.map((p, i) => {
    const hasText = !!S["reasoning" + p.key.charAt(0).toUpperCase() + p.key.slice(1)];
    const isStreaming = i === streamIdx;
    const isSelected = i === selectedIdx;
    const lit = hasText || isStreaming;
    const enabled = S.reasoningEnabled[p.key] !== false;
    const dotStyle = [
      `background:${lit ? p.color : "var(--bg-elevated)"}`,
      `color:${lit ? "#fff" : "var(--text-muted)"}`,
      `border:2px solid ${isSelected ? "var(--accent)" : lit ? p.color : "var(--border)"}`,
      isSelected ? "box-shadow:0 0 0 2px var(--accent)" : "",
      !enabled ? "opacity:0.4" : "",
    ]
      .filter(Boolean)
      .join(";");
    const lineColor = i < streamIdx ? REASONING_PASSES[i + 1].color : "var(--border)";
    const checkId = `reasoning-enabled-${p.key}`;
    return (
      `<div class="reasoning-dot-col">
        <button class="reasoning-dot" onclick="selectReasoningPass(${i})" style="${dotStyle}">${i + 1}</button>
        <label class="reasoning-enabled-label" for="${checkId}">
          <input type="checkbox" id="${checkId}" ${enabled ? "checked" : ""} onchange="toggleReasoningPass('${p.key}')">
          <span>on</span>
        </label>
      </div>` + (i < 2 ? `<div class="reasoning-rail-line" style="background:${lineColor}"></div>` : "")
    );
  }).join("");

  const selectedPass = REASONING_PASSES[selectedIdx];
  const currentText = S["reasoning" + selectedPass.key.charAt(0).toUpperCase() + selectedPass.key.slice(1)] || "";
  const openAttr = S.reasoningOpen ? " open" : "";

  return `<details class="inspector-block reasoning-section" id="reasoning-section"${openAttr} ontoggle="S.reasoningOpen=this.open;saveInspectorOpenStates()">
    <summary class="reasoning-summary">
      <span class="reasoning-summary-arrow">▶</span>
      <h4 style="margin:0;display:inline">Reasoning</h4>
    </summary>
    <div style="margin-top:8px">
      <div class="reasoning-stepper">
        ${dotsHtml}
        <span class="reasoning-pass-label">${esc(selectedPass.label)}</span>
      </div>
      <div class="reasoning-box" id="reasoning-box">${esc(currentText)}</div>
    </div>
  </details>`;
}

function _refreshReasoningSection() {
  const existing = document.getElementById("reasoning-section");
  if (!existing) return;
  existing.outerHTML = _buildReasoningHtml();
  // Auto-scroll the newly rendered box to bottom only when viewing the streaming pass
  if (!S.reasoningUserOverride) {
    const box = document.getElementById("reasoning-box");
    if (box) box.scrollTop = box.scrollHeight;
  }
}

export function selectReasoningPass(idx) {
  S.reasoningPassSelected = idx;
  S.reasoningUserOverride = true;
  _refreshReasoningSection();
}

// Selected pass per workflow pipeline. Keyed by pipeline id; value is one of its
// pass ids. Defaults to the first pass at registration.
const _workflowPipelineSelected = new Map();

function _pipelineSelectedPassId(pipeline) {
  if (!pipeline.passes?.length) return null;
  const cur = _workflowPipelineSelected.get(pipeline.id);
  if (cur && pipeline.passes.some((p) => p.id === cur)) return cur;
  return pipeline.passes[0].id;
}

function _buildSecondaryReasoningHtml() {
  if (!S.workflowPipelines.length) return "";
  return S.workflowPipelines
    .map((pipeline) => {
      const selectedId = _pipelineSelectedPassId(pipeline);
      const dotsHtml = pipeline.passes
        .map((p, i) => {
          const hasText = !!S.reasoningByPass[p.id];
          const isSelected = p.id === selectedId;
          const lit = hasText || isSelected;
          const dotStyle = [
            `background:${lit ? "var(--accent)" : "var(--bg-elevated)"}`,
            `color:${lit ? "#fff" : "var(--text-muted)"}`,
            `border:2px solid ${isSelected ? "var(--accent)" : lit ? "var(--accent)" : "var(--border)"}`,
            isSelected ? "box-shadow:0 0 0 2px var(--accent)" : "",
          ]
            .filter(Boolean)
            .join(";");
          const lineColor = hasText ? "var(--accent)" : "var(--border)";
          return (
            `<div class="reasoning-dot-col">
              <button class="reasoning-dot" onclick="selectWorkflowPipelinePass('${pipeline.id}','${p.id}')" style="${dotStyle}">${i + 1}</button>
              <span class="reasoning-pass-label" style="margin:0">${esc(p.label || p.id)}</span>
            </div>` +
            (i < pipeline.passes.length - 1
              ? `<div class="reasoning-rail-line" style="background:${lineColor}"></div>`
              : "")
          );
        })
        .join("");
      const text = S.reasoningByPass[selectedId] || "";
      return `<div class="workflow-card workflow-pipeline-card" data-pipeline-id="${esc(pipeline.id)}">
        <h4>${esc(pipeline.label || pipeline.id)}</h4>
        <div class="reasoning-stepper">${dotsHtml}</div>
        <div class="reasoning-box" id="reasoning-box-${esc(pipeline.id)}" data-pass-id="${esc(selectedId)}">${esc(text)}</div>
      </div>`;
    })
    .join("");
}

function _buildSecondaryAgentsHtml() {
  if (!S.workflowInspectorCardRenderers.length) return "";
  let html = "";
  for (const fn of S.workflowInspectorCardRenderers) {
    try {
      const piece = fn();
      if (typeof piece === "string" && piece) html += piece;
    } catch (e) {
      console.error("workflow inspector card renderer threw:", e);
    }
  }
  return html;
}

export function selectWorkflowPipelinePass(pipelineId, passId) {
  _workflowPipelineSelected.set(pipelineId, passId);
  renderInspectorSecondary();
}

export function renderInspectorSecondary() {
  const el = $("inspector-secondary-content");
  if (!el) return;
  const reasoning = _buildSecondaryReasoningHtml();
  const cards = _buildSecondaryAgentsHtml();
  if (!reasoning && !cards) {
    el.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:8px 0;">No secondary workflows registered.</div>`;
    return;
  }
  el.innerHTML = reasoning + cards;
}

export function setInspectorTab(name) {
  S.inspectorTab = name === "secondary" ? "secondary" : "main";
  _applyInspectorTab();
}

function _applyInspectorTab() {
  const main = $("inspector-content");
  const sec = $("inspector-secondary-content");
  const btnMain = $("inspector-tab-main");
  const btnSec = $("inspector-tab-secondary");
  if (!main || !sec || !btnMain || !btnSec) return;
  if (S.inspectorTab === "secondary") {
    main.classList.add("hidden");
    sec.classList.remove("hidden");
    btnMain.classList.remove("tab-button-active");
    btnSec.classList.add("tab-button-active");
    renderInspectorSecondary();
  } else {
    sec.classList.add("hidden");
    main.classList.remove("hidden");
    btnSec.classList.remove("tab-button-active");
    btnMain.classList.add("tab-button-active");
  }
}

export function setToolsTab(name) {
  S.toolsTab = name === "secondary" ? "secondary" : "main";
  _applyToolsTab();
}

function _applyToolsTab() {
  const main = $("tools-pane-main");
  const sec = $("tools-pane-secondary");
  const btnMain = $("tools-tab-main");
  const btnSec = $("tools-tab-secondary");
  if (!main || !sec || !btnMain || !btnSec) return;
  if (S.toolsTab === "secondary") {
    main.classList.add("hidden");
    sec.classList.remove("hidden");
    btnMain.classList.remove("tab-button-active");
    btnSec.classList.add("tab-button-active");
  } else {
    sec.classList.add("hidden");
    main.classList.remove("hidden");
    btnSec.classList.remove("tab-button-active");
    btnMain.classList.add("tab-button-active");
  }
}

function _renderWorkflowPhasesPill() {
  const el = $("gen-text-secondary");
  if (!el) return;
  const entries = Object.entries(S.workflowPhases);
  if (!entries.length) {
    el.textContent = "";
    el.style.display = "none";
    return;
  }
  const [, label] = entries[entries.length - 1];
  el.textContent = label;
  el.style.display = "";
}

export async function loadSecondaryWorkflowManifest() {
  try {
    const manifest = await api.get("/secondary-workflows");
    if (Array.isArray(manifest)) S.workflowManifest = manifest;
  } catch (e) {
    console.error("Failed to load secondary workflow manifest:", e);
  }
}

export async function toggleReasoningPass(passKey) {
  S.reasoningEnabled[passKey] = !S.reasoningEnabled[passKey];
  _refreshReasoningSection();
  await api.put("/settings", { reasoning_enabled_passes: { ...S.reasoningEnabled } });
}

function _buildToolCallsHtml(tc) {
  const openAttr = S.toolCallsOpen ? " open" : "";
  return `<details class="inspector-block"${openAttr} ontoggle="S.toolCallsOpen=this.open;saveInspectorOpenStates()">
    <summary class="reasoning-summary">
      <span class="reasoning-summary-arrow">▶</span>
      <h4 style="margin:0;display:inline">Tool Calls</h4>
    </summary>
    <div class="injection-box" style="margin-top:8px">${esc(tc.map((c) => JSON.stringify(c)).join("\n\n"))}</div>
  </details>`;
}

function _buildInjectionBlockHtml(inj) {
  const openAttr = S.injectionBlockOpen ? " open" : "";
  return `<details class="inspector-block"${openAttr} ontoggle="S.injectionBlockOpen=this.open;saveInspectorOpenStates()">
    <summary class="reasoning-summary">
      <span class="reasoning-summary-arrow">▶</span>
      <h4 style="margin:0;display:inline">Injection Block</h4>
    </summary>
    <div class="injection-box" style="margin-top:8px">${esc(inj)}</div>
  </details>`;
}

export function saveInspectorOpenStates() {
  api
    .put("/settings", {
      inspector_open_states: {
        reasoning: S.reasoningOpen,
        tool_calls: S.toolCallsOpen,
        injection_block: S.injectionBlockOpen,
        context_size: S.contextSizeOpen,
      },
    })
    .catch(() => {});
}

// ── Inspector
export function clearRefineDiff() {
  S.pendingRefineDiff = null;
  renderMessages();
}

export function toggleInspector() {
  const inspector = $("inspector");
  const toolsPanel = $("tools-panel");
  const btn = $("inspector-toggle");
  const toolsBtn = $("tools-panel-btn");
  const wasOpen = inspector.classList.contains("open");
  const switching = !wasOpen && toolsPanel.classList.contains("open");

  if (wasOpen) {
    inspector.classList.remove("open");
    btn.classList.remove("btn-active");
  } else {
    toolsPanel.classList.remove("open");
    toolsBtn.classList.remove("btn-active");
    const open = () => {
      inspector.classList.add("open");
      btn.classList.add("btn-active");
    };
    if (switching) setTimeout(open, 180);
    else open();
  }
}

export function renderInspector() {
  _renderInspectorMain();
  renderInspectorSecondary();
}

function _renderInspectorMain() {
  if (S.isStreaming && S.lastDirectorData === null) {
    $("inspector-content").innerHTML = `${_buildReasoningHtml()}
       <div class="inspector-block" id="inspector-context-size"></div>
       <div style="color:var(--text-muted);font-size:12px;display:flex;align-items:center;gap:8px">
         <span class="typing-indicator"><span></span><span></span><span></span></span> Director thinking…
       </div>`;
    const _rb = document.getElementById("reasoning-box");
    if (_rb) _rb.scrollTop = _rb.scrollHeight;
    return;
  }

  const insp = S.inspectedMsgId && S.inspectedDirectorData ? S.inspectedDirectorData : null;

  if (insp) {
    const activeIds = insp.active_moods || [];
    const stylesHtml = S.moodFragments
      .map((f) => `<span class="style-tag ${activeIds.includes(f.id) ? "active" : ""}">${esc(f.label)}</span>`)
      .join("");
    const lat = insp.agent_latency_ms || 0;
    const tc = insp.tool_calls || [];
    const inj = insp.injection_block || "";
    $("inspector-content").innerHTML = `
      <div class="inspector-block" id="inspector-context-size"></div>
      <div class="inspector-block">
        <h4>Moods</h4>
        <div>${stylesHtml || '<span style="color:var(--text-muted);font-size:12px">None</span>'}</div>
      </div>
      ${_buildReasoningHtml()}
      ${tc.length ? _buildToolCallsHtml(tc) : ""}
      ${inj ? _buildInjectionBlockHtml(inj) : ""}
      ${
        lat
          ? `<div class="inspector-block"><h4>Agent Latency</h4>
                 <div style="font-size:12px;color:var(--text-secondary)">${lat}ms</div></div>`
          : ""
      }`;
    const _rb = document.getElementById("reasoning-box");
    if (_rb) _rb.scrollTop = _rb.scrollHeight;
    renderContextSize();
    return;
  }

  // Check if we have any director data to display
  const hasDirectorData =
    (S.directorState && Object.keys(S.directorState).length > 0) ||
    (S.lastDirectorData && Object.keys(S.lastDirectorData).length > 0);

  if (!hasDirectorData) {
    $("inspector-content").innerHTML = `${_buildReasoningHtml()}
       <div class="inspector-block" id="inspector-context-size"></div>
       <div style="color:var(--text-muted);font-size:12px;">
         Send a message to see director output
       </div>`;
    return;
  }

  const ds = S.directorState || {};
  const ld = S.lastDirectorData || {};
  const activeIds = ld.active_moods || ds.active_moods || [];
  const stylesHtml = S.moodFragments
    .map((f) => `<span class="style-tag ${activeIds.includes(f.id) ? "active" : ""}">${esc(f.label)}</span>`)
    .join("");
  const lat = ld.agent_latency_ms || 0;
  const tc = ld.tool_calls || [];
  const inj = ld.injection_block || "";
  $("inspector-content").innerHTML = `
    <div class="inspector-block" id="inspector-context-size"></div>
    <div class="inspector-block"><h4>Moods</h4>
      <div>${stylesHtml || '<span style="color:var(--text-muted);font-size:12px">None</span>'}</div>
    </div>
    ${_buildReasoningHtml()}
    ${tc.length ? _buildToolCallsHtml(tc) : ""}
    ${inj ? _buildInjectionBlockHtml(inj) : ""}
    ${
      lat
        ? `<div class="inspector-block"><h4>Agent Latency</h4>
               <div style="font-size:12px;color:var(--text-secondary)">${lat}ms</div></div>`
        : ""
    }`;
  // Scroll the freshly rendered reasoning box to bottom
  const _rb = document.getElementById("reasoning-box");
  if (_rb) _rb.scrollTop = _rb.scrollHeight;
  renderContextSize();
}

export function showAvatarPopup() {
  if (!S.activeCharId) return;
  const popup = document.getElementById("avatar-popup");
  if (!popup) return;
  if (!popup.classList.contains("hidden")) {
    hideAvatarPopup();
    return;
  }
  const img = document.getElementById("avatar-popup-image");
  if (img) img.src = `/api/characters/${S.activeCharId}/avatar?t=${Date.now()}`;
  popup.classList.remove("hidden");
}

export function hideAvatarPopup() {
  const popup = document.getElementById("avatar-popup");
  if (popup) popup.classList.add("hidden");
}
