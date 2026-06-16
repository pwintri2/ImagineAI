let galleryEl;

export function init() {
  galleryEl = document.getElementById('gallery');
  if (galleryEl) renderEmpty();
  galleryEl?.addEventListener('click', handleClick);
}

export function renderLoading(count, meta = {}) {
  if (!galleryEl) return;
  const cols = Math.min(count, 4);
  const gridCols = cols > 2 ? 'md:grid-cols-4' : cols > 1 ? 'md:grid-cols-2' : 'md:grid-cols-1';
  galleryEl.innerHTML = `
    <div class="grid grid-cols-2 ${gridCols} gap-3 fade-in">
      ${Array.from({ length: count }, () => `<div class="skeleton rounded-2xl aspect-square"></div>`).join('')}
    </div>
    <p class="text-center text-xs text-slate-500 mt-4" id="galleryStatus">${meta.label || 'Creating your image…'}</p>
  `;
}

export function updateStatus(text) {
  const el = document.getElementById('galleryStatus');
  if (el) el.textContent = text;
}

export function renderResults(images, meta = {}) {
  if (!galleryEl) return;
  const cols = Math.min(images.length, 4);
  const gridCols = cols > 2 ? 'md:grid-cols-4' : cols > 1 ? 'md:grid-cols-2' : 'md:grid-cols-1';
  const baseName = defaultBaseName(meta.prompt, 'imagineai-image');
  galleryEl.innerHTML = `
    <div class="grid grid-cols-2 ${gridCols} gap-3 fade-in">
      ${images.map((img, i) => `
        <div class="image-card overflow-hidden rounded-2xl border border-white/10 bg-white/5">
          <img src="${escapeAttr(img.url)}" alt="Generated image ${i + 1}" class="w-full aspect-square object-cover" loading="lazy" />
          <div class="space-y-2 border-t border-white/10 bg-black/20 p-2">
            <label class="block text-[10px] font-semibold uppercase tracking-wider text-slate-500" for="imageName${i}">File name</label>
            <div class="flex gap-2">
              <input id="imageName${i}" type="text" value="${escapeAttr(images.length > 1 ? `${baseName}-${i + 1}` : baseName)}"
                class="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
              <button type="button" data-save-image="${i}" data-url="${escapeAttr(img.url)}"
                class="shrink-0 rounded-lg border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-white/15">Save</button>
            </div>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function handleClick(e) {
  const btn = e.target.closest('[data-save-image]');
  if (!btn) return;
  const index = Number(btn.dataset.saveImage || 0);
  const input = document.getElementById(`imageName${index}`);
  const ext = extensionFromUrl(btn.dataset.url || '', '.png');
  downloadMedia(btn.dataset.url || '', input?.value || `imagineai-image-${index + 1}`, ext);
}

export function renderError(message) {
  if (!galleryEl) return;
  galleryEl.innerHTML = `
    <div class="fade-in text-center py-12">
      <div class="text-4xl mb-3">😕</div>
      <p class="text-sm text-slate-400 max-w-md mx-auto break-words">${escapeHtml(message || 'Something went wrong.')}</p>
    </div>
  `;
}

function renderEmpty() {
  if (!galleryEl) return;
  galleryEl.innerHTML = `
    <div class="text-center py-16">
      <div class="text-6xl mb-4 opacity-20">🎨</div>
      <p class="text-sm text-slate-500">No images yet</p>
      <p class="text-xs text-slate-600 mt-1">Type a prompt above and hit Generate.</p>
    </div>
  `;
}

function downloadMedia(url, rawName, fallbackExt) {
  const filename = ensureExtension(safeFileBase(rawName), fallbackExt);
  const href = withDownloadName(url, filename);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function withDownloadName(url, filename) {
  const u = new URL(url, window.location.origin);
  u.searchParams.set('downloadName', filename);
  return `${u.pathname}${u.search}`;
}

function extensionFromUrl(url, fallback) {
  try {
    const u = new URL(url, window.location.origin);
    const candidate = u.searchParams.get('name') || u.searchParams.get('filename') || u.pathname;
    const match = String(candidate).match(/\.([a-z0-9]{2,5})$/i);
    return match ? `.${match[1].toLowerCase()}` : fallback;
  } catch {
    return fallback;
  }
}

function ensureExtension(base, ext) {
  const safeExt = ext && ext.startsWith('.') ? ext : '.png';
  return /\.[a-z0-9]{2,5}$/i.test(base) ? base : `${base}${safeExt}`;
}

function safeFileBase(value) {
  const base = String(value || '').trim()
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/[^A-Za-z0-9._ -]+/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^[. ]+|[. ]+$/g, '');
  return base.slice(0, 120) || 'imagineai-image';
}

function defaultBaseName(prompt, fallback) {
  const words = String(prompt || '').toLowerCase().match(/[a-z0-9]+/g) || [];
  return words.slice(0, 5).join('-') || fallback;
}

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }
