let galleryEl;

export function init() {
  galleryEl = document.getElementById('video-gallery');
  if (galleryEl) renderEmpty();
  galleryEl?.addEventListener('click', handleClick);
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
  const baseName = defaultBaseName(meta.prompt, 'imagineai-video');
  const downloadUrl = video.mp4Url || video.url;
  const downloadExt = extensionFromUrl(downloadUrl, video.mp4Url ? '.mp4' : '.webm');
  const segments = segmentList(video);
  const segmentFallback = video.stitchStatus === 'segments' && segments.length > 1;
  galleryEl.innerHTML = `
    <div class="fade-in space-y-4">
      <div class="video-card group relative rounded-2xl overflow-hidden border border-white/10 bg-white/5 aspect-video">
        <video id="generatedVideo" controls loop muted playsinline class="w-full h-full object-contain bg-black" preload="auto">
          ${sourceTag(video.url)}
          ${video.mp4Url && video.mp4Url !== video.url ? sourceTag(video.mp4Url, 'video/mp4') : ''}
        </video>
      </div>
      <p id="videoPlaybackError" class="hidden rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200"></p>
      <div class="space-y-2 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <label class="block text-[10px] font-semibold uppercase tracking-wider text-slate-500" for="videoFileName">File name</label>
        <div class="flex gap-2">
          <input id="videoFileName" type="text" value="${escapeAttr(baseName)}"
            class="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          <button type="button" data-save-video data-url="${escapeAttr(downloadUrl)}" data-ext="${escapeAttr(downloadExt)}"
            class="shrink-0 rounded-lg border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-white/15">Save</button>
        </div>
      </div>
      ${segmentFallback ? renderSegmentFallback(segments, baseName, video.stitchWarning) : ''}
      <div class="flex items-center gap-2 text-[11px] text-slate-600 justify-center">
        <span>${escapeHtml(meta.modelTitle || '')}</span>
      </div>
    </div>
  `;
  wireVideoFallback(video);
}

function wireVideoFallback(video) {
  const el = document.getElementById('generatedVideo');
  const errorEl = document.getElementById('videoPlaybackError');
  if (!el || !errorEl) return;
  let triedFallback = false;

  el.addEventListener('loadeddata', () => {
    errorEl.classList.add('hidden');
    errorEl.textContent = '';
  });

  el.addEventListener('error', () => {
    if (!triedFallback && video.mp4Url && video.mp4Url !== video.url) {
      triedFallback = true;
      while (el.firstChild) el.removeChild(el.firstChild);
      const source = document.createElement('source');
      source.src = video.mp4Url;
      source.type = 'video/mp4';
      el.appendChild(source);
      el.load();
      return;
    }
    errorEl.textContent = 'Embedded playback failed. The file is still available with Save.';
    errorEl.classList.remove('hidden');
  }, true);
}

function handleClick(e) {
  const btn = e.target.closest('[data-save-video]');
  if (!btn) return;
  const input = document.getElementById('videoFileName');
  downloadMedia(btn.dataset.url || '', btn.dataset.name || input?.value || 'imagineai-video', btn.dataset.ext || '.mp4');
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

function sourceTag(url, forcedType = '') {
  if (!url) return '';
  const type = forcedType || mediaTypeFromUrl(url);
  return `<source src="${escapeAttr(url)}"${type ? ` type="${escapeAttr(type)}"` : ''}>`;
}

function segmentList(video) {
  return Array.isArray(video?.segments) ? video.segments.filter((segment) => segment?.url || segment?.mp4Url) : [];
}

function renderSegmentFallback(segments, baseName, warning) {
  const items = segments.map((segment, index) => {
    const url = segment.mp4Url || segment.url;
    const ext = extensionFromUrl(url, segment.mp4Url ? '.mp4' : '.webm');
    const name = `${baseName}-part-${index + 1}`;
    return `
      <div class="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
        <span class="text-xs text-slate-300">Part ${index + 1}</span>
        <button type="button" data-save-video data-url="${escapeAttr(url)}" data-ext="${escapeAttr(ext)}" data-name="${escapeAttr(name)}"
          class="rounded-lg border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-white/15">Save</button>
      </div>
    `;
  }).join('');
  return `
    <div class="space-y-2 rounded-xl border border-amber-400/20 bg-amber-400/10 p-3">
      <p class="text-xs text-amber-100">${escapeHtml(warning || 'Local stitching is unavailable. The generated segments are available separately.')}</p>
      <div class="space-y-2">${items}</div>
    </div>
  `;
}

function mediaTypeFromUrl(url) {
  const ext = extensionFromUrl(url, '');
  if (ext === '.webm') return 'video/webm';
  if (ext === '.mp4') return 'video/mp4';
  if (ext === '.mov') return 'video/quicktime';
  return '';
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
  const safeExt = ext && ext.startsWith('.') ? ext : '.mp4';
  return /\.[a-z0-9]{2,5}$/i.test(base) ? base : `${base}${safeExt}`;
}

function safeFileBase(value) {
  const base = String(value || '').trim()
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/[^A-Za-z0-9._ -]+/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^[. ]+|[. ]+$/g, '');
  return base.slice(0, 120) || 'imagineai-video';
}

function defaultBaseName(prompt, fallback) {
  const words = String(prompt || '').toLowerCase().match(/[a-z0-9]+/g) || [];
  return words.slice(0, 5).join('-') || fallback;
}

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }
