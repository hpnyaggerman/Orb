import { $ } from "./utils.js";
import { S } from "./state.js";
import { validate } from "./validate.js";
import {
  initTheme,
  loadSettings,
  saveSetting,
  onHybridInput,
  showUserModal,
  saveUserProfile,
  applyTheme,
  toggleToolsPanel,
  setAgentEnabled,
  toggleToolEnabled,
  toggleLengthGuard,
  saveLengthGuardConfig,
  toggleLengthGuardEnforce,
  showPhraseBankModal,
  showAddPhraseGroupModal,
  showPersonaEditModal,
  savePersona,
  deletePersona,
  editPersona,
  activatePersona,
} from "./settings.js";
import {
  loadMoodFragments,
  showMoodFragmentModal,
  saveMoodFragment,
  deleteMoodFragment,
  toggleMoodFragmentEnabled,
  loadDirectorFragments,
  showDirectorFragmentModal,
  saveDirectorFragment,
  deleteDirectorFragment,
  toggleDirectorFragmentEnabled,
  loadCharacters,
  renderCharacters,
  triggerImport,
  handleImportFile,
  deleteCharacter,
  showCharCreateModal,
  createCharacter,
  showCharEditModal,
  saveCharEdit,
  saveImportedChar,
  addAltGreeting,
  triggerAvatarCrop,
  exportCharacter,
  showCharacterBrowserModal,
  setCharBrowserView,
  onCharBrowserSearch,
  setCharBrowserSort,
  toggleTagSelection,
  refreshCharacters,
} from "./library.js";
import {
  loadConversations,
  resetChatUI,
  selectChar,
  newConvForChar,
  selectConversation,
  deleteConversationFromModal,
  showConvHistoryModal,
  renderMessages,
  startEdit,
  cancelEdit,
  saveEdit,
  deleteMessage,
  switchBranch,
  regenerate,
  sendMessage,
  stopGeneration,
  toggleInspector,
  selectReasoningPass,
  toggleReasoningPass,
  clearRefineDiff,
  showAvatarPopup,
  hideAvatarPopup,
} from "./chat.js";
import { closeModal, switchTab, showConfirmModal, runConfirmCb, closeCropModal } from "./modal.js";

// ── Sidebar toggle
function toggleSection(header) {
  header.querySelector(".arrow").classList.toggle("collapsed");
  header.nextElementSibling.classList.toggle("collapsed");
}

const MOBILE_SIDEBAR_BREAKPOINT = 900;
let _mobileBackArmed = false;
let _handlingMobilePop = false;

function isMobileSidebarViewport() {
  return window.matchMedia(`(max-width: ${MOBILE_SIDEBAR_BREAKPOINT}px)`).matches;
}

function closeMobileSidebar() {
  $("app")?.classList.remove("mobile-sidebar-open");
}

function toggleMobileHeaderActions() {
  if (!isMobileSidebarViewport()) return;
  $("mobile-chat-actions-menu")?.classList.toggle("open");
  closeBurger();
  armMobileBackIfNeeded();
}

function closeMobileHeaderActions() {
  $("mobile-chat-actions-menu")?.classList.remove("open");
}

function syncMobilePanelState() {
  const app = $("app");
  const toolsPanel = $("tools-panel");
  const inspector = $("inspector");
  if (!app || !toolsPanel || !inspector) return;

  if (!isMobileSidebarViewport()) {
    app.classList.remove("mobile-tools-open", "mobile-inspector-open");
    return;
  }

  const toolsOpen = toolsPanel.classList.contains("open");
  const inspectorOpen = inspector.classList.contains("open");
  app.classList.toggle("mobile-tools-open", toolsOpen);
  app.classList.toggle("mobile-inspector-open", inspectorOpen);

  if (toolsOpen || inspectorOpen) {
    closeMobileSidebar();
    closeMobileHeaderActions();
  }
}

function closeMobileUtilityPanels() {
  $("tools-panel")?.classList.remove("open");
  $("inspector")?.classList.remove("open");
  syncMobilePanelState();
}

function hasOpenBaseModal() {
  return Boolean($("modal-root")?.firstElementChild);
}

function hasOpenCropModal() {
  return Boolean($("modal-crop-root")?.firstElementChild);
}

function hasOpenMobileOverlay() {
  if (!isMobileSidebarViewport()) return false;
  const app = $("app");
  return Boolean(
    hasOpenCropModal() ||
      hasOpenBaseModal() ||
      $("mobile-chat-actions-menu")?.classList.contains("open") ||
      app?.classList.contains("mobile-sidebar-open") ||
      app?.classList.contains("mobile-tools-open") ||
      app?.classList.contains("mobile-inspector-open"),
  );
}

function armMobileBackIfNeeded() {
  if (_handlingMobilePop || !isMobileSidebarViewport() || _mobileBackArmed || !hasOpenMobileOverlay()) return;
  history.pushState({ orbMobileOverlay: true }, "");
  _mobileBackArmed = true;
}

function closeTopMobileOverlay() {
  if (!isMobileSidebarViewport()) return false;
  if (hasOpenCropModal()) {
    closeCropModal();
    return true;
  }
  if (hasOpenBaseModal()) {
    closeModal();
    return true;
  }
  if ($("mobile-chat-actions-menu")?.classList.contains("open")) {
    closeMobileHeaderActions();
    return true;
  }
  if ($("tools-panel")?.classList.contains("open") || $("inspector")?.classList.contains("open")) {
    closeMobileUtilityPanels();
    return true;
  }
  if ($("app")?.classList.contains("mobile-sidebar-open")) {
    closeMobileSidebar();
    return true;
  }
  return false;
}

function toggleMobileSidebar() {
  if (!isMobileSidebarViewport()) return;
  closeMobileUtilityPanels();
  closeMobileHeaderActions();
  $("app")?.classList.toggle("mobile-sidebar-open");
  closeBurger();
  armMobileBackIfNeeded();
}

// ── Burger menu
function toggleBurger() {
  $("burger-dropdown").classList.toggle("open");
}
function closeBurger() {
  $("burger-dropdown").classList.remove("open");
}
function triggerAttachImage() {
  $("attach-image-input").click();
}

document.addEventListener("click", (e) => {
  if (!e.target.closest("#burger-btn") && !e.target.closest("#burger-dropdown")) closeBurger();
  if (!e.target.closest("#mobile-chat-actions-toggle") && !e.target.closest("#mobile-chat-actions-menu")) {
    closeMobileHeaderActions();
  }
  if (
    isMobileSidebarViewport() &&
    $("app")?.classList.contains("mobile-sidebar-open") &&
    e.target.closest("#sidebar .btn, #sidebar .char-item, #sidebar .fragment-item")
  ) {
    setTimeout(closeMobileSidebar, 0);
  }
  if (
    isMobileSidebarViewport() &&
    $("app")?.classList.contains("mobile-sidebar-open") &&
    !e.target.closest("#sidebar") &&
    !e.target.closest("#mobile-sidebar-toggle")
  ) {
    closeMobileSidebar();
  }
  if (
    isMobileSidebarViewport() &&
    $("tools-panel")?.classList.contains("open") &&
    !e.target.closest("#tools-panel") &&
    !e.target.closest("#tools-panel-btn") &&
    !e.target.closest("#mobile-chat-actions-menu")
  ) {
    $("tools-panel").classList.remove("open");
    syncMobilePanelState();
  }
  if (
    isMobileSidebarViewport() &&
    $("inspector")?.classList.contains("open") &&
    !e.target.closest("#inspector") &&
    !e.target.closest("#inspector-toggle") &&
    !e.target.closest("#mobile-chat-actions-menu")
  ) {
    $("inspector").classList.remove("open");
    syncMobilePanelState();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMobileSidebar();
    closeMobileHeaderActions();
    closeMobileUtilityPanels();
  }
});

window.addEventListener("resize", () => {
  if (!isMobileSidebarViewport()) {
    closeMobileSidebar();
    closeMobileHeaderActions();
  }
  syncMobilePanelState();
  armMobileBackIfNeeded();
});

const toolsPanel = $("tools-panel");
const inspectorPanel = $("inspector");
if (toolsPanel && inspectorPanel) {
  const observer = new MutationObserver(() => {
    syncMobilePanelState();
    if (!_handlingMobilePop) armMobileBackIfNeeded();
  });
  observer.observe(toolsPanel, { attributes: true, attributeFilter: ["class"] });
  observer.observe(inspectorPanel, { attributes: true, attributeFilter: ["class"] });
}
syncMobilePanelState();

const modalRoot = $("modal-root");
const cropModalRoot = $("modal-crop-root");
if (modalRoot || cropModalRoot) {
  const overlayObserver = new MutationObserver(() => {
    if (!_handlingMobilePop) armMobileBackIfNeeded();
  });
  if (modalRoot) overlayObserver.observe(modalRoot, { childList: true });
  if (cropModalRoot) overlayObserver.observe(cropModalRoot, { childList: true });
}

window.addEventListener("popstate", () => {
  _mobileBackArmed = false;
  if (!isMobileSidebarViewport()) return;
  _handlingMobilePop = true;
  const closedAny = closeTopMobileOverlay();
  _handlingMobilePop = false;
  if (closedAny && hasOpenMobileOverlay()) armMobileBackIfNeeded();
});

// Attachments handling
function handleAttachmentSelect(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;

  const validation = validate.validateImageFiles(files, 10, 10 * 1024 * 1024, 20 * 1024 * 1024);
  if (!validation.valid) {
    toast(validation.error, true);
    e.target.value = "";
    return;
  }

  for (const file of files) {
    const fileValidation = validate.validateImageFile(file, 10 * 1024 * 1024, [
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/gif",
    ]);
    if (!fileValidation.valid) {
      toast(fileValidation.error, true);
      continue;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const b64 = event.target.result.split(",")[1]; // strip data:image/...;base64,
      S.attachments.push({
        b64,
        mime: file.type,
        filename: file.name,
        size: file.size,
      });
      updateAttachmentPreview();
    };
    reader.readAsDataURL(file);
  }
  e.target.value = ""; // allow re-selecting same file
}

function updateAttachmentPreview() {
  const container = $("attachment-preview");
  container.innerHTML = "";
  S.attachments.forEach((att, idx) => {
    const item = document.createElement("div");
    item.className = "attachment-item";
    const img = document.createElement("img");
    img.src = `data:${att.mime};base64,${att.b64}`;
    const info = document.createElement("div");
    info.className = "attachment-info";
    const name = document.createElement("div");
    name.className = "attachment-name";
    name.textContent = att.filename || "image";
    const size = document.createElement("div");
    size.className = "attachment-size";
    size.textContent = formatBytes(att.size);
    info.appendChild(name);
    info.appendChild(size);
    const removeBtn = document.createElement("button");
    removeBtn.className = "attachment-remove";
    removeBtn.innerHTML = "×";
    removeBtn.title = "Remove";
    removeBtn.onclick = () => {
      S.attachments.splice(idx, 1);
      updateAttachmentPreview();
    };
    item.appendChild(img);
    item.appendChild(info);
    item.appendChild(removeBtn);
    container.appendChild(item);
  });
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

// File input change listener
$("attach-image-input").addEventListener("change", handleAttachmentSelect);

// ── Input events
$("chat-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 150) + "px";
});
$("chat-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const validation = validate.validateChatInput(this.value);
    if (!validation.valid) {
      toast(validation.error, true);
      return;
    }
    sendMessage();
  }
});

// ── Expose to inline handlers
Object.assign(window, {
  // modal
  closeModal,
  switchTab,
  showConfirmModal,
  runConfirmCb,
  // theme
  applyTheme,
  // settings / user
  saveSetting,
  onHybridInput,
  showUserModal,
  saveUserProfile,
  showPersonaEditModal,
  savePersona,
  deletePersona,
  editPersona,
  activatePersona,
  // tools
  toggleToolsPanel,
  setAgentEnabled,
  toggleToolEnabled,
  toggleLengthGuard,
  saveLengthGuardConfig,
  toggleLengthGuardEnforce,
  // phrase bank
  showPhraseBankModal,
  showAddPhraseGroupModal,
  // mood fragments
  showMoodFragmentModal,
  saveMoodFragment,
  deleteMoodFragment,
  toggleMoodFragmentEnabled,
  // director fragments
  showDirectorFragmentModal,
  saveDirectorFragment,
  deleteDirectorFragment,
  toggleDirectorFragmentEnabled,
  // characters
  selectChar,
  triggerImport,
  handleImportFile,
  deleteCharacter,
  showCharCreateModal,
  createCharacter,
  showCharEditModal,
  saveCharEdit,
  saveImportedChar,
  addAltGreeting,
  triggerAvatarCrop,
  exportCharacter,
  showCharacterBrowserModal,
  setCharBrowserView,
  onCharBrowserSearch,
  setCharBrowserSort,
  toggleTagSelection,
  refreshCharacters,
  // crop modal
  closeCropModal,
  // conversations
  newConvForChar,
  selectConversation,
  deleteConversationFromModal,
  showConvHistoryModal,
  // messages
  startEdit,
  cancelEdit,
  saveEdit,
  deleteMessage,
  switchBranch,
  regenerate,
  sendMessage,
  stopGeneration,
  // inspector
  toggleInspector,
  selectReasoningPass,
  toggleReasoningPass,
  clearRefineDiff,
  // ui
  toggleSection,
  toggleMobileSidebar,
  toggleMobileHeaderActions,
  closeMobileHeaderActions,
  toggleBurger,
  closeBurger,
  triggerAttachImage,
  updateAttachmentPreview,
  showAvatarPopup,
  hideAvatarPopup,
  // state
  S,
});

// ── Smart autoscroll: disable on upward scroll, re-enable when back at bottom
function initAutoscroll() {
  const ct = $("chat-messages");
  if (!ct) return;
  const THRESHOLD = 20;
  let scrollDebounce = null;

  // Wheel: immediately cut autoscroll on any upward scroll intent
  ct.addEventListener(
    "wheel",
    (e) => {
      if (e.deltaY < 0) S.autoscrollEnabled = false;
    },
    { passive: true },
  );

  // Touch: disable on upward swipe
  let touchStartY = 0;
  ct.addEventListener(
    "touchstart",
    (e) => {
      touchStartY = e.touches[0].clientY;
    },
    { passive: true },
  );
  ct.addEventListener(
    "touchmove",
    (e) => {
      if (e.touches[0].clientY > touchStartY) S.autoscrollEnabled = false;
    },
    { passive: true },
  );

  // Re-enable only once the user has scrolled back to the bottom (debounced to
  // avoid false positives from rapid programmatic scroll events during streaming)
  ct.addEventListener("scroll", () => {
    if (S._programmaticScroll) return;
    clearTimeout(scrollDebounce);
    scrollDebounce = setTimeout(() => {
      const atBottom = ct.scrollHeight - ct.scrollTop - ct.clientHeight <= THRESHOLD;
      if (atBottom) S.autoscrollEnabled = true;
    }, 100);
  });
}

// ── Init
initTheme();
initAutoscroll();

// Load data independently to prevent failures from blocking other loads
async function initAll() {
  try {
    await loadSettings();
  } catch (e) {
    console.error("Failed to load settings:", e);
  }

  try {
    await loadDirectorFragments();
  } catch (e) {
    console.error("Failed to load director fragments:", e);
  }

  try {
    await loadMoodFragments();
  } catch (e) {
    console.error("Failed to load mood fragments:", e);
    // Show empty state but don't crash
    $("frag-list").innerHTML =
      '<div style="color:var(--text-muted);font-size:12px;padding:4px 0;">Failed to load mood fragments</div>';
  }

  // Load conversations before characters so we can filter by recent activity
  try {
    await loadConversations();
  } catch (e) {
    console.error("Failed to load conversations:", e);
  }

  try {
    await loadCharacters();
  } catch (e) {
    console.error("Failed to load characters:", e);
  }
}

// Start initialization
initAll();
