// Direction Notes panel: the conversation's accumulated direction notes on the
// active branch, grouped by the fragment that authored them, with edit/delete.
// Mirrors the Inspector's right-rail panel -- the model authors notes during a
// turn; the user curates them here.
import { api } from "./api.js";
import { closeModal, showConfirmModal, showModal } from "./modal.js";
import { closeUtilityPanel, isUtilityPanelOpen, openUtilityPanel } from "./panels.js";
import { S } from "./state.js";
import { $, convUrl, esc, toast } from "./utils.js";

// Last fetched notes, so the edit modal can seed its textarea by id without escaping round-trips.
let notes = [];

export function toggleDirectionNotesPanel() {
  if (isUtilityPanelOpen("direction-notes-panel")) {
    closeUtilityPanel("direction-notes-panel", "direction-notes-panel-btn");
  } else {
    openUtilityPanel("direction-notes-panel", "direction-notes-panel-btn", renderDirectionNotesPanel);
  }
}

function renderRows() {
  const el = $("direction-notes-panel-content");
  if (!el) return;
  if (!notes.length) {
    el.innerHTML = `<div class="notes-empty">No direction notes on this branch yet. The director records them when Direction Notes is on.</div>`;
    return;
  }
  // Turn order (the route returns oldest-first by id, which equals turn order on a
  // branch); within a turn, fragment order. Each note carries its fragment's label so
  // the source is obvious without bucketing notes away from their chronology.
  el.innerHTML = notes
    .map(
      (n) => `<div class="notes-row">
      <div class="notes-row-meta">
        <span class="notes-row-frag">${esc(n.interactive_fragment_label || "(unnamed)")}</span>
        <span class="notes-row-turn">Turn ${n.turn_index}</span>
      </div>
      <div class="notes-row-content">${esc(n.content)}</div>
      <div class="notes-row-actions">
        <button class="btn btn-sm" onclick="editDirectionNote(${n.id})">Edit</button>
        <button class="btn btn-sm btn-danger" onclick="deleteDirectionNote(${n.id})">Delete</button>
      </div>
    </div>`,
    )
    .join("");
}

export async function renderDirectionNotesPanel() {
  const el = $("direction-notes-panel-content");
  if (!el) return;
  if (!S.activeConvId) {
    el.innerHTML = `<div class="notes-empty">No conversation selected.</div>`;
    return;
  }
  try {
    notes = await api.get(convUrl(S.activeConvId, "direction-notes"));
  } catch (e) {
    el.innerHTML = `<div class="notes-empty">${esc(e.message)}</div>`;
    return;
  }
  renderRows();
}

// Regenerating message msgId replaces it with a new sibling, so msgId (and any of
// its descendants) leaves the active branch along with the notes recorded on it.
// The new branch only commits when the stream ends, so reflect the drop right away
// from the cached set -- keep only notes whose authoring message precedes msgId on
// the active path. afterStream refetches the committed state once the reply lands.
export function optimisticDropDirectionNotesFrom(msgId) {
  if (!isUtilityPanelOpen("direction-notes-panel")) return;
  const path = S.messages.map((m) => m.id);
  const cut = path.indexOf(msgId);
  if (cut < 0) return;
  const surviving = new Set(path.slice(0, cut));
  notes = notes.filter((n) => surviving.has(n.message_id));
  renderRows();
}

export function editDirectionNote(fid) {
  const note = notes.find((n) => n.id === fid);
  showModal(`
    <h2>Edit Direction Note</h2>
    <div class="field"><label>Note</label>
      <textarea id="direction-note-content" rows="5">${esc(note ? note.content : "")}</textarea></div>
    <div class="modal-actions">
      <div style="flex:1"></div>
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-accent" onclick="saveDirectionNote(${fid})">Save</button>
    </div>`);
}

export async function saveDirectionNote(fid) {
  const content = document.getElementById("direction-note-content").value.trim();
  if (!content) {
    toast("Note cannot be empty", true);
    return;
  }
  try {
    await api.put(convUrl(S.activeConvId, "direction-notes", fid), { content });
    closeModal();
    await renderDirectionNotesPanel();
    toast("Note saved");
  } catch (e) {
    toast(e.message, true);
  }
}

export function deleteDirectionNote(fid) {
  showConfirmModal(
    { title: "Delete Direction Note", message: "Delete this direction note?", confirmText: "Delete" },
    async () => {
      try {
        await api.del(convUrl(S.activeConvId, "direction-notes", fid));
        await renderDirectionNotesPanel();
        toast("Note deleted");
      } catch (e) {
        toast(e.message, true);
      }
    },
  );
}
