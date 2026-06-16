let galleryEl;

export function init() {
  galleryEl = document.getElementById('video-gallery');
  if (galleryEl) renderEmpty();
}

export function renderLoading(meta = {}) {
  if (!galleryEl) return;
  galleryEl.innerHTML = `
    <div class="fade-in">
      <div class="skeleton rounded-2xl aspect-video"></div>
      <p class="text-center text-xs text-slate-500 mt-4" id="videoStatus">Crafting your video…</p>
      <p class="text-center text-[11px] text-slate-600 mt-1">${escapeHtml(meta.modelTitle || '')}</p>
    </div>
  `;
}

export function updateStatus(text) {
  const el = document.getElementById('videoStatus');
  if (el) el.textContent = text;
}

export function renderResults(videos, meta = {}) {
  if (!galleryEl) return;
  const video = videos[0];
  if (!video) { renderError('No video was produced.'); return; }
  galleryEl.innerHTML = `
    <div class="fade-in space-y-4">
      <div class="video-card group relative rounded-2xl overflow-hidden border border-white/10 bg-white/5 aspect-video">
        <video src="${video.url}" controls loop autoplay muted playsinline class="w-full h-full object-contain bg-black" preload="metadata"></video>
      </div>
      <div class="flex gap-2">
        <a href="${video.mp4Url || video.url}" download="imagineai-video-${Date.now()}.${video.mp4Url ? 'mp4' : 'webm'}" class="flex-1 text-center px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-white text-xs font-medium transition-all">⬇ Download</a>
      </div>
      <div class="flex items-center gap-2 text-[11px] text-slate-600 justify-center">
        <span>${escapeHtml(meta.modelTitle || '')}</span>
      </div>
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
      <div class="text-6xl mb-4 opacity-20">🎬</div>
      <p class="text-sm text-slate-500">No videos yet</p>
      <p class="text-xs text-slate-600 mt-1">Describe a scene and hit Create Video.</p>
    </div>
  `;
}

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
