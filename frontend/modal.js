import { $ } from './utils.js';

// ── Crop modal state
let _cs = null; // { img, scale, onConfirm, cx, cy, csize, drag }

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

// ── Image crop modal
// Opens a file picker; on selection shows a canvas crop editor in #modal-crop-root
// (a separate overlay so it stacks above the character create/edit modal).
// onConfirm receives { b64, mime } where the cropped image is 400×400 PNG.

export function showCropModal(onConfirm) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = () => {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => _openCropEditor(ev.target.result, onConfirm);
    reader.readAsDataURL(file);
  };
  input.click();
}

function _openCropEditor(dataUrl, onConfirm) {
  const root = $('modal-crop-root');
  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal" style="align-items:center;gap:12px">
        <h2>Crop Avatar</h2>
        <canvas id="crop-canvas"></canvas>
        <div style="font-size:11px;color:var(--text-muted)">Drag to move &middot; Drag corners to resize</div>
        <div class="modal-actions" style="width:100%;margin-top:0">
          <button class="btn" onclick="closeCropModal()">Cancel</button>
          <button class="btn btn-accent" onclick="confirmCrop()">Use Image</button>
        </div>
      </div>
    </div>`;

  const img = new Image();
  img.onload = () => {
    const MAX = 480;
    const scale = Math.min(MAX / img.naturalWidth, MAX / img.naturalHeight, 1);
    const canvas = $('crop-canvas');
    canvas.width  = Math.round(img.naturalWidth  * scale);
    canvas.height = Math.round(img.naturalHeight * scale);

    const size = Math.round(Math.min(canvas.width, canvas.height) * 0.85);
    _cs = {
      img, scale, onConfirm,
      cx: Math.round((canvas.width  - size) / 2),
      cy: Math.round((canvas.height - size) / 2),
      csize: size,
      drag: null,
    };
    _drawCrop(canvas);
    _attachCropEvents(canvas);
  };
  img.src = dataUrl;

  window.confirmCrop = () => _confirmCrop($('crop-canvas'));
}

function _drawCrop(canvas) {
  if (!_cs) return;
  const { img, cx, cy, csize } = _cs;
  const W = canvas.width, H = canvas.height;
  const ctx = canvas.getContext('2d');

  ctx.drawImage(img, 0, 0, W, H);

  // Dark vignette outside the crop box (four rectangles around it)
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(0, 0, W, cy);
  ctx.fillRect(0, cy + csize, W, H - cy - csize);
  ctx.fillRect(0, cy, cx, csize);
  ctx.fillRect(cx + csize, cy, W - cx - csize, csize);

  // Rule-of-thirds lines
  ctx.strokeStyle = 'rgba(255,255,255,0.25)';
  ctx.lineWidth = 0.5;
  for (let i = 1; i < 3; i++) {
    const gx = cx + (csize * i) / 3;
    const gy = cy + (csize * i) / 3;
    ctx.beginPath(); ctx.moveTo(gx, cy); ctx.lineTo(gx, cy + csize); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx, gy); ctx.lineTo(cx + csize, gy); ctx.stroke();
  }

  // Crop border
  ctx.strokeStyle = 'rgba(255,255,255,0.9)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(cx + 0.75, cy + 0.75, csize - 1.5, csize - 1.5);

  // Corner handles
  const hs = 8;
  ctx.fillStyle = 'white';
  [[cx, cy], [cx + csize, cy], [cx, cy + csize], [cx + csize, cy + csize]].forEach(([hx, hy]) => {
    ctx.fillRect(hx - hs / 2, hy - hs / 2, hs, hs);
  });
}

function _attachCropEvents(canvas) {
  const toLocal = e => {
    const r = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return { x: src.clientX - r.left, y: src.clientY - r.top };
  };

  const onStart = e => {
    e.preventDefault();
    if (!_cs) return;
    const { x, y } = toLocal(e);
    const { cx, cy, csize } = _cs;
    const hs = 14; // hit-test radius for corner handles

    // Corner order: TL, TR, BL, BR — anchor = opposite corner
    const corners = [
      [cx,        cy,        cx + csize, cy + csize],
      [cx + csize,cy,        cx,         cy + csize],
      [cx,        cy + csize,cx + csize, cy        ],
      [cx + csize,cy + csize,cx,         cy        ],
    ];
    for (const [hx, hy, ax, ay] of corners) {
      if (Math.abs(x - hx) < hs && Math.abs(y - hy) < hs) {
        _cs.drag = { mode: 'corner', ax, ay };
        return;
      }
    }
    if (x >= cx && x <= cx + csize && y >= cy && y <= cy + csize) {
      _cs.drag = { mode: 'move', ox: x - cx, oy: y - cy };
    }
  };

  const onMove = e => {
    e.preventDefault();
    if (!_cs?.drag) return;
    const { x, y } = toLocal(e);
    const { drag } = _cs;
    const W = canvas.width, H = canvas.height;

    if (drag.mode === 'move') {
      _cs.cx = Math.max(0, Math.min(W - _cs.csize, x - drag.ox));
      _cs.cy = Math.max(0, Math.min(H - _cs.csize, y - drag.oy));
    } else {
      // Keep the anchor corner fixed; derive square size from mouse distance
      const { ax, ay } = drag;
      const dx = Math.abs(x - ax);
      const dy = Math.abs(y - ay);
      let sz = Math.max(40, Math.max(dx, dy));
      let nx = x < ax ? ax - sz : ax;
      let ny = y < ay ? ay - sz : ay;
      // Clamp to canvas bounds
      if (nx < 0) { sz = Math.min(sz, ax); nx = 0; }
      if (ny < 0) { sz = Math.min(sz, ay); ny = 0; }
      sz = Math.min(sz, W - nx, H - ny);
      _cs.cx = nx; _cs.cy = ny; _cs.csize = Math.max(40, sz);
    }
    _drawCrop(canvas);
  };

  const onEnd = () => { if (_cs) _cs.drag = null; };

  canvas.addEventListener('mousedown',  onStart);
  canvas.addEventListener('mousemove',  onMove);
  canvas.addEventListener('mouseup',    onEnd);
  canvas.addEventListener('touchstart', onStart, { passive: false });
  canvas.addEventListener('touchmove',  onMove,  { passive: false });
  canvas.addEventListener('touchend',   onEnd);
}

function _confirmCrop(canvas) {
  if (!_cs) return;
  const { img, cx, cy, csize, scale, onConfirm } = _cs;
  const out = document.createElement('canvas');
  out.width = out.height = 400;
  // Map display-space crop back to image-space source region
  const sx = cx / scale, sy = cy / scale, ss = csize / scale;
  out.getContext('2d').drawImage(img, sx, sy, ss, ss, 0, 0, 400, 400);
  const b64 = out.toDataURL('image/png').split(',')[1];
  closeCropModal();
  onConfirm({ b64, mime: 'image/png' });
}

export function closeCropModal() {
  const root = $('modal-crop-root');
  if (root) root.innerHTML = '';
  _cs = null;
}