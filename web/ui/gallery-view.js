let galleryEl;

export function init() {
  galleryEl = document.getElementById('gallery');
  if (galleryEl) renderEmpty();
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

export function renderResults(images) {
  if (!galleryEl) return;
  const cols = Math.min(images.length, 4);
  const gridCols = cols > 2 ? 'md:grid-cols-4' : cols > 1 ? 'md:grid-cols-2' : 'md:grid-cols-1';
  galleryEl.innerHTML = `
    <div class="grid grid-cols-2 ${gridCols} gap-3 fade-in">
      ${images.map((img, i) => `
        <div class="image-card group relative rounded-2xl overflow-hidden border border-white/10 bg-white/5">
          <img src="${img.url}" alt="Generated image ${i + 1}" class="w-full aspect-square object-cover" loading="lazy" />
          <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-3">
            <a href="${img.url}" download="imagineai-${Date.now()}-${i + 1}.png" class="flex-1 text-center px-3 py-2 rounded-xl bg-white/20 backdrop-blur text-white text-xs font-medium hover:bg-white/30 transition">⬇ Download</a>
          </div>
        </div>
      `).join('')}
    </div>
  `;
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

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
