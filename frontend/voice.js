import { S } from "./state.js";
import { $, esc, toast } from "./utils.js";
import { api } from "./api.js";

const _SVG =
  'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"';
const ICON_PLAY = `<svg ${_SVG}><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
const ICON_STOP = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>`;
const ICON_REPLAY = `<svg ${_SVG}><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/></svg>`;

function clampVolume(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0.75;
  return Math.max(0, Math.min(1, n));
}

function formatTime(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  const r = String(s % 60).padStart(2, "0");
  return `${m}:${r}`;
}

async function persistVoiceSettings(payload) {
  try {
    S.settings = await api.put("/settings", payload);
  } catch (e) {
    toast("Failed to save voice setting", true);
  }
}

export function renderVoicePanel() {
  const el = $("voice-panel-content");
  if (!el) return;

  const extracted = S.ttsExtractedText || "";
  const volumePct = Math.round(clampVolume(S.ttsVolume) * 100);
  const isPlaying = !!S.speakingMsgId && !S.ttsLoading;
  const isLoading = S.ttsLoading;
  const isActive = isPlaying || isLoading;
  const duration = S.ttsDuration || 0;
  const current = S.ttsCurrentTime || 0;
  const vp = S.ttsVoiceProfile;
  const last = S.ttsLastPlayed;

  // Show playback card when active OR when we have last-played info
  const showPlayback = isActive || last;

  el.innerHTML = `
    <div class="inspector-block">
      <h4>Playback</h4>
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-secondary);margin-bottom:6px">
        <span>Volume</span><span id="voice-volume-pct" style="margin-left:auto">${volumePct}%</span>
      </div>
      <input class="voice-range" type="range" min="0" max="100" value="${volumePct}" oninput="setTtsVolumeLive(this.value)" onchange="setTtsVolume(this.value)">
    </div>

    <div class="tool-card ${S.ttsAutoSpeak ? "tool-on" : ""}">
      <div class="tool-card-header">
        <span class="tool-card-name">Auto-speak</span>
        <label class="tog" onclick="event.stopPropagation()">
          <input type="checkbox" ${S.ttsAutoSpeak ? "checked" : ""} onchange="setTtsAutoSpeak(this.checked)">
          <span class="tog-slider"></span>
        </label>
      </div>
      <div class="tool-card-desc">Automatically speak new character messages.</div>
    </div>

    ${
      vp && vp.backend
        ? `<div class="tool-card">
             <div class="tool-card-header">
               <span class="tool-card-name">Voice${vp.enabled ? "" : " (disabled)"}</span>
               ${S.activeCharId ? `<button class="btn btn-sm" onclick="openVoiceSettings()">Edit</button>` : ""}
             </div>
             <div class="tool-card-desc" style="font-family:var(--font-mono)">${esc(vp.backend)} · ${esc(vp.language || "en-US")} · ${esc(vp.voice_id || "default")}</div>
           </div>`
        : S.activeCharId
          ? `<div class="tool-card">
               <div class="tool-card-header">
                 <span class="tool-card-name">Voice</span>
                 <button class="btn btn-sm" onclick="openVoiceSettings()">Configure</button>
               </div>
               <div class="tool-card-desc">No voice configured for this character.</div>
             </div>`
          : ""
    }

    ${
      showPlayback
        ? `<div class="tool-card ${isActive ? "tool-on" : ""}" id="voice-now-playing">
             <div class="tool-card-header">
               <span class="tool-card-name">${isActive ? "Now Playing" : "Last Played"}</span>
               ${
                 isLoading
                   ? `<span style="font-size:12px;color:var(--text-secondary)">Loading…</span>`
                   : isPlaying
                     ? `<button class="btn-icon" onclick="stopSpeaking()" title="Stop">${ICON_STOP}</button>`
                     : `<button class="btn-icon" onclick="replayLastMessage()" title="Replay">${ICON_REPLAY}</button>`
               }
             </div>
             <div class="tool-card-desc" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
               ${esc(isActive ? S.ttsPlayingLabel || `Message #${S.speakingMsgId}` : last?.label || "")}
             </div>
             <div class="voice-progress-row">
               <span id="voice-time-current">${formatTime(isActive ? current : last?.duration || 0)}</span>
               <progress id="voice-progress" value="${isActive ? current : last?.duration || 0}" max="${(isActive ? duration : last?.duration) || 1}"></progress>
               <span id="voice-time-duration">${formatTime((isActive ? duration : last?.duration) || 0)}</span>
             </div>
           </div>`
        : ""
    }

    ${
      extracted
        ? `<div class="tool-card" style="cursor:pointer" onclick="this.querySelector('.script-body').style.display=this.querySelector('.script-body').style.display==='none'?'block':'none'">
             <div class="tool-card-header">
               <span class="tool-card-name">Speech Script</span>
               <span style="font-size:11px;color:var(--text-secondary)">${extracted.split("\n").length} lines</span>
             </div>
             <div class="script-body" style="display:${S.ttsDebugExpanded ? "block" : "none"}">
               <pre class="voice-debug-text">${esc(extracted)}</pre>
             </div>
           </div>`
        : ""
    }
  `;
}

export function refreshNowPlaying() {
  const duration = S.ttsDuration || 0;
  const current = S.ttsCurrentTime || 0;
  const progress = $("voice-progress");
  if (progress) {
    progress.value = current;
    progress.max = duration || 1;
  }
  const ct = $("voice-time-current");
  if (ct) ct.textContent = formatTime(current);
  const dt = $("voice-time-duration");
  if (dt) dt.textContent = duration ? formatTime(duration) : "--:--";
}

export function toggleVoicePanel() {
  const panel = $("voice-panel");
  const toolsPanel = $("tools-panel");
  const inspector = $("inspector");
  const btn = $("voice-panel-btn");
  const toolsBtn = $("tools-panel-btn");
  const inspectorBtn = $("inspector-toggle");
  if (!panel || !toolsPanel || !inspector || !btn) return;

  const wasOpen = panel.classList.contains("open");
  const switching = !wasOpen && (toolsPanel.classList.contains("open") || inspector.classList.contains("open"));

  if (wasOpen) {
    panel.classList.remove("open");
    btn.classList.remove("btn-active");
  } else {
    toolsPanel.classList.remove("open");
    inspector.classList.remove("open");
    toolsBtn?.classList.remove("btn-active");
    inspectorBtn?.classList.remove("btn-active");
    const open = () => {
      panel.classList.add("open");
      btn.classList.add("btn-active");
      _loadVoiceProfile();
    };
    if (switching) setTimeout(open, 180);
    else open();
  }
}

export function setTtsVolumeLive(value) {
  const pct = Math.round(clampVolume(Number(value) / 100) * 100);
  S.ttsVolume = clampVolume(Number(value) / 100);
  if (window.setCurrentTtsVolume) window.setCurrentTtsVolume(S.ttsVolume);
  const label = document.querySelector("#voice-volume-pct");
  if (label) label.textContent = `${pct}%`;
}

export async function setTtsVolume(value) {
  S.ttsVolume = clampVolume(Number(value) / 100);
  if (window.setCurrentTtsVolume) window.setCurrentTtsVolume(S.ttsVolume);
  renderVoicePanel();
  await persistVoiceSettings({ tts_volume: S.ttsVolume });
}

export async function setTtsAutoSpeak(checked) {
  S.ttsAutoSpeak = !!checked;
  renderVoicePanel();
  await persistVoiceSettings({ tts_auto_speak: S.ttsAutoSpeak ? 1 : 0 });
}

export async function openVoiceSettings() {
  if (!S.activeCharId) return;
  await window.showCharEditModal(S.activeCharId);
  // Modal is now in the DOM — click the Voice tab
  const voiceTab = document.querySelector('.tab[onclick*="ce-tvoice"]');
  if (voiceTab) voiceTab.click();
}

export function replayLastMessage() {
  if (!S.ttsLastPlayed?.msgId) return;
  window.speakMessage(S.ttsLastPlayed.msgId);
}

export async function loadVoiceProfile() {
  await _loadVoiceProfile();
}

async function _loadVoiceProfile() {
  if (!S.activeCharId) {
    S.ttsVoiceProfile = null;
    renderVoicePanel();
    return;
  }
  try {
    S.ttsVoiceProfile = await api.get("/characters/" + S.activeCharId + "/voice-profile");
  } catch {
    S.ttsVoiceProfile = null;
  }
  renderVoicePanel();
}
