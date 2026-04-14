import { $ } from './utils.js';

export function showModal(html) {
  $('modal-root').innerHTML =
    `<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
       <div class="modal">${html}</div>
     </div>`;
}

export function closeModal() {
  $('modal-root').innerHTML = '';
}

export function switchTab(tab, contentId) {
  tab.parentElement.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  tab.classList.add('active');
  tab.closest('.modal').querySelectorAll('.tab-content').forEach(x => x.classList.remove('active'));
  $(contentId).classList.add('active');
}

export function showConfirmModal({ title, message, confirmText = 'Confirm', confirmClass = 'btn-danger', extraHtml = '' }, onConfirm) {
  window._confirmCb = onConfirm;
  showModal(`
    <h2>${title}</h2>
    <p>${message}</p>
    ${extraHtml}
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn ${confirmClass}" onclick="runConfirmCb()">${confirmText}</button>
    </div>`);
}

export function runConfirmCb() {
  const cb = window._confirmCb;
  window._confirmCb = null;
  if (cb) cb();
  closeModal();
}