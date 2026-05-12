import { api, getVoiceProfile } from "./api.js";
import { S } from "./state.js";
import { toast } from "./utils.js";

function clampVolume(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0.75;
  return Math.max(0, Math.min(1, n));
}

async function persistVoiceSettings(payload) {
  try {
    S.settings = await api.put("/settings", payload);
  } catch {
    toast("Failed to save voice setting", true);
  }
}

export function refreshTtsBar() {
  const bar = document.getElementById("tts-status");
  if (!bar) return;
  const isPlaying = !!S.speakingMsgId && !S.ttsLoading;
  const isLoading = S.ttsLoading;
  const isActive = isPlaying || isLoading;
  if (!isActive) {
    bar.classList.add("hidden");
    bar.classList.remove("tts-loading");
    return;
  }
  bar.classList.remove("hidden");
  if (isLoading) {
    bar.classList.add("tts-loading");
  } else {
    bar.classList.remove("tts-loading");
  }
  const progress = bar.querySelector(".tts-progress");
  if (isPlaying && S.ttsDuration > 0) {
    const pct = Math.min(100, ((S.ttsCurrentTime || 0) / S.ttsDuration) * 100);
    // Skip transition when jumping backwards (chunk boundary reset)
    if (pct < (progress._lastPct || 0) - 5) {
      progress.style.transition = "none";
      progress.style.width = pct + "%";
      // Force reflow so the no-transition takes effect before we restore it
      progress.offsetHeight; // eslint-disable-line no-unused-expressions
      progress.style.transition = "";
    } else {
      progress.style.width = pct + "%";
    }
    progress._lastPct = pct;
  } else {
    progress._lastPct = 0;
    progress.style.width = "0%";
  }
  const text = bar.querySelector(".tts-text");
  if (text) {
    const chunkInfo =
      S.speakingChunkTotal != null && S.speakingChunkIdx != null
        ? ` (${S.speakingChunkIdx + 1}/${S.speakingChunkTotal})`
        : "";
    text.textContent = isLoading ? `Generating speech${chunkInfo}…` : `Speaking${chunkInfo}…`;
  }
}

export function setTtsVolumeLive(value) {
  const pct = Math.round(clampVolume(Number(value) / 100) * 100);
  S.ttsVolume = clampVolume(Number(value) / 100);
  if (window.setCurrentTtsVolume) window.setCurrentTtsVolume(S.ttsVolume);
  const volLabel = document.getElementById("tts-volume-pct");
  if (volLabel) volLabel.textContent = pct + "%";
}

export async function setTtsVolume(value) {
  S.ttsVolume = clampVolume(Number(value) / 100);
  if (window.setCurrentTtsVolume) window.setCurrentTtsVolume(S.ttsVolume);
  await persistVoiceSettings({ tts_volume: S.ttsVolume });
}

export async function setTtsAutoSpeak(checked) {
  S.ttsAutoSpeak = !!checked;
  await persistVoiceSettings({ tts_auto_speak: S.ttsAutoSpeak ? 1 : 0 });
}

export async function loadVoiceProfile() {
  await _loadVoiceProfile();
}

async function _loadVoiceProfile() {
  if (!S.activeCharId) {
    S.ttsVoiceProfile = null;
    return;
  }
  try {
    S.ttsVoiceProfile = await getVoiceProfile(S.activeCharId);
  } catch {
    S.ttsVoiceProfile = null;
  }
}
