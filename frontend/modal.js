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