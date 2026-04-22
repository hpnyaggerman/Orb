import { $ } from "./utils.js";
import { closeModal, closeCropModal } from "./modal.js";

const MOBILE_SIDEBAR_BREAKPOINT = 900;
let _mobileBackArmed = false;
let _handlingMobilePop = false;
let _closeBurger = () => {};

function isMobileSidebarViewport() {
  return window.matchMedia(`(max-width: ${MOBILE_SIDEBAR_BREAKPOINT}px)`).matches;
}

function closeMobileSidebar() {
  $("app")?.classList.remove("mobile-sidebar-open");
}

export function toggleMobileHeaderActions() {
  if (!isMobileSidebarViewport()) return;
  $("mobile-chat-actions-menu")?.classList.toggle("open");
  _closeBurger();
  armMobileBackIfNeeded();
}

export function closeMobileHeaderActions() {
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

export function toggleMobileSidebar() {
  if (!isMobileSidebarViewport()) return;
  closeMobileUtilityPanels();
  closeMobileHeaderActions();
  $("app")?.classList.toggle("mobile-sidebar-open");
  _closeBurger();
  armMobileBackIfNeeded();
}

/**
 * @param {{ closeBurger: () => void }} deps
 */
export function initMobileUi(deps) {
  _closeBurger = deps.closeBurger;

  document.addEventListener("click", (e) => {
    const path = typeof e.composedPath === "function" ? e.composedPath() : [];
    const target = e.target instanceof Element ? e.target : null;
    const inPath = (id) => path.some((node) => node instanceof Element && node.id === id);
    const inSelector = (selector) => Boolean(target?.closest(selector));

    const clickedBurgerBtn = inPath("burger-btn") || inSelector("#burger-btn");
    const clickedBurgerDropdown = inPath("burger-dropdown") || inSelector("#burger-dropdown");
    const clickedMobileActionsToggle =
      inPath("mobile-chat-actions-toggle") || inSelector("#mobile-chat-actions-toggle");
    const clickedMobileActionsMenu = inPath("mobile-chat-actions-menu") || inSelector("#mobile-chat-actions-menu");
    const clickedSidebar = inPath("sidebar") || inSelector("#sidebar");
    const clickedSidebarToggle = inPath("mobile-sidebar-toggle") || inSelector("#mobile-sidebar-toggle");
    const clickedToolsPanel = inPath("tools-panel") || inSelector("#tools-panel");
    const clickedToolsBtn = inPath("tools-panel-btn") || inSelector("#tools-panel-btn");
    const clickedInspectorPanel = inPath("inspector") || inSelector("#inspector");
    const clickedInspectorBtn = inPath("inspector-toggle") || inSelector("#inspector-toggle");
    const clickedSidebarAction = inSelector("#sidebar .btn, #sidebar .char-item, #sidebar .fragment-item");

    if (!clickedBurgerBtn && !clickedBurgerDropdown) _closeBurger();
    if (!clickedMobileActionsToggle && !clickedMobileActionsMenu) {
      closeMobileHeaderActions();
    }
    if (
      isMobileSidebarViewport() &&
      $("app")?.classList.contains("mobile-sidebar-open") &&
      clickedSidebarAction
    ) {
      setTimeout(closeMobileSidebar, 0);
    }
    if (
      isMobileSidebarViewport() &&
      $("app")?.classList.contains("mobile-sidebar-open") &&
      !clickedSidebar &&
      !clickedSidebarToggle
    ) {
      closeMobileSidebar();
    }
    if (
      isMobileSidebarViewport() &&
      $("tools-panel")?.classList.contains("open") &&
      !clickedToolsPanel &&
      !clickedToolsBtn &&
      !clickedMobileActionsMenu
    ) {
      $("tools-panel").classList.remove("open");
      syncMobilePanelState();
    }
    if (
      isMobileSidebarViewport() &&
      $("inspector")?.classList.contains("open") &&
      !clickedInspectorPanel &&
      !clickedInspectorBtn &&
      !clickedMobileActionsMenu
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
}
