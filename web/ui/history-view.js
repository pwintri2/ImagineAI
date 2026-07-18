import { getState, subscribe, clearHistory as clearImages, clearVideoHistory } from '../state.js';
import { ensureVideoMp4 } from '../services/api.js';
import {
  editionFromSearch,
  videoMediaType,
  videoPlaybackCandidates,
} from '../services/video-playback.js';
import { showToast } from './toast-view.js';

let panelEl, listEl, isOpen = false;
let historyTab = 'images';

export function init() {
  panelEl = document.getElementById('history-panel');
  listEl = document.getElementById('historyList');

  document.getElementById('historyToggle')?.addEventListener('click', toggle);
  document.getElementById('closeHistoryBtn')?.addEventListener('click', close);
  document.getElementById('historyOverlay')?.addEventListener('click', close);
  document.getElementById('clearHistoryBtn')?.addEventListener('click', handleClear);
  listEl?.addEventListener('click', handleListClick);

  document.getElementById('historyTabs')?.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-history-tab]');
    if (!tab) return;
    historyTab = tab.dataset.historyTab;
    document.querySelectorAll('[data-history-tab]').forEach((b) => {
      const active = b.dataset.historyTab === historyTab;
      b.classList.toggle('tab-active', active);
      b.classList.toggle('border-transparent', !active);
      b.classList.toggle('text-slate-400', !active);
    });
    render();
  });

  subscribe(() => { if (isOpen) render(); });
}

export function open() { isOpen = true; panelEl?.classList.remove('hidden'); animate(); render(); }
function close() { isOpen = false; panelEl?.classList.add('hidden'); }
function toggle() { isOpen ? close() : open(); }

function animate() {
  if (!panelEl) return;
  const inner = panelEl.querySelector('.relative');
  if (!inner) return;
  inner.classList.remove('slide-in-right');
  void inner.offsetWidth;
  inner.classList.add('slide-in-right');
}

function handleClear() {
  const label = historyTab === 'images' ? 'Clear all image history' : 'Clear all video history';
  if (confirm(label + '?')) {
    if (historyTab === 'images') clearImages();
    else clearVideoHistory();
  }
}

async function handleListClick(e) {
  const btn = e.target.closest('[data-save-history-video]');
  if (!btn) return;
  const rawName = btn.dataset.name || 'imagineai-video';
  const originalUrl = btn.dataset.url || '';
  if (!originalUrl) return;
  if (btn.dataset.convertMp4 === 'true') {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Making MP4…';
    try {
      const result = await ensureVideoMp4(originalUrl);
      const mp4Url = result.mp4Url || '';
      if (!mp4Url) throw new Error('No MP4 was returned.');
      btn.dataset.url = mp4Url;
      delete btn.dataset.convertMp4;
      btn.dataset.fallbackExt = '.mp4';
      btn.textContent = 'Save MP4';
      downloadMedia(mp4Url, rawName, '.mp4');
      showToast('MP4 ready', 'success');
    } catch (err) {
      console.warn('Could not create MP4 from history item:', err);
      showToast('Could not make an MP4; saving the original video.', 'info');
      downloadMedia(originalUrl, rawName, btn.dataset.fallbackExt || extensionFromUrl(originalUrl, '.webm'));
      btn.textContent = originalLabel;
    } finally {
      btn.disabled = false;
    }
    return;
  }
  downloadMedia(originalUrl, rawName, btn.dataset.fallbackExt || '.mp4');
}

function render() {
  if (!listEl) return;
  const { history, videoHistory } = getState();
  const countEl = document.getElementById('historyCount');
  if (historyTab === 'images') renderImages(history, countEl);
  else renderVideos(videoHistory, countEl);
}

function renderImages(history, countEl) {
  if (countEl) countEl.textContent = history.length ? `${history.length} generations` : '';
  if (!history.length) { listEl.innerHTML = empty('🖼️', 'No image history yet', 'Your generated images appear here.'); return; }
  listEl.innerHTML = history.map((entry, i) => `
    <div class="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 space-y-2 fade-in" style="animation-delay:${Math.min(i, 10) * 40}ms">
      <p class="text-xs text-slate-300 line-clamp-2 px-0.5">${esc(entry.prompt)}</p>
      <div class="grid ${entry.images.length > 1 ? 'grid-cols-2' : 'grid-cols-1'} gap-1.5">
        ${entry.images.slice(0, 4).map((img) => `<img src="${img.url}" alt="" class="rounded-lg w-full aspect-square object-cover" loading="lazy" />`).join('')}
      </div>
      <div class="flex items-center justify-between px-0.5">
        <span class="text-[10px] text-slate-600">${esc(entry.modelTitle)}</span>
        <span class="text-[10px] text-slate-600">${fmtTime(entry.createdAt)}</span>
      </div>
    </div>
  `).join('');
}

function renderVideos(videoHistory, countEl) {
  if (countEl) countEl.textContent = videoHistory.length ? `${videoHistory.length} videos` : '';
  if (!videoHistory.length) { listEl.innerHTML = empty('🎬', 'No video history yet', 'Your generated videos appear here.'); return; }
  listEl.innerHTML = videoHistory.map((entry, i) => {
    const video = entry.videos?.[0];
    const target = historyVideoSaveTarget(video);
    const fileBase = historyVideoFileBase(entry, `imagineai-video-${i + 1}`);
    return `
      <div class="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 space-y-2 fade-in" style="animation-delay:${Math.min(i, 10) * 40}ms">
        <p class="text-xs text-slate-300 line-clamp-2 px-0.5">${esc(entry.prompt)}</p>
        <div class="rounded-lg overflow-hidden bg-black">
          <video preload="metadata" class="w-full aspect-video object-contain" muted loop playsinline onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0;">
            ${historyVideoSources(video)}
          </video>
        </div>
        <div class="flex items-center justify-between gap-2 px-0.5">
          <div class="min-w-0">
            <p class="truncate text-[10px] text-violet-400/80">${esc(entry.modelTitle)}</p>
            <p class="text-[10px] text-slate-600">${fmtTime(entry.createdAt)}</p>
          </div>
          ${target ? `
            <button type="button" data-save-history-video data-url="${attr(target.url)}" data-name="${attr(fileBase)}"
              data-fallback-ext="${attr(target.fallbackExt)}"${target.convertMp4 ? ' data-convert-mp4="true"' : ''}
              class="shrink-0 rounded-lg border border-white/10 bg-white/10 px-2.5 py-1 text-[10px] font-medium text-white transition hover:bg-white/15 disabled:cursor-wait disabled:opacity-60">${esc(target.label)}</button>
          ` : `
            <span class="shrink-0 text-[10px] text-slate-600">No video</span>
          `}
        </div>
      </div>
    `;
  }).join('');
}

export function historyVideoMp4Url(video) {
  const mp4Url = typeof video?.mp4Url === 'string' ? video.mp4Url.trim() : '';
  if (mp4Url) return mp4Url;
  const url = typeof video?.url === 'string' ? video.url.trim() : '';
  return extensionFromUrl(url, '') === '.mp4' ? url : '';
}

export function historyVideoSaveTarget(video) {
  const mp4Url = historyVideoMp4Url(video);
  if (mp4Url) return { url: mp4Url, label: 'Save MP4', fallbackExt: '.mp4', convertMp4: false };
  const url = typeof video?.url === 'string' ? video.url.trim() : '';
  if (!url) return null;
  const ext = extensionFromUrl(url, '.mp4');
  return {
    url,
    label: ext === '.webm' ? 'Save MP4' : `Save ${ext.replace('.', '').toUpperCase()}`,
    fallbackExt: ext,
    convertMp4: ext !== '.mp4',
  };
}

export function historyVideoFileBase(entry, fallback = 'imagineai-video') {
  const prompt = String(entry?.prompt || '').toLowerCase();
  const words = prompt.match(/[a-z0-9]+/g) || [];
  return safeFileBase(words.slice(0, 5).join('-') || fallback || 'imagineai-video');
}

function historyVideoSources(video) {
  return videoPlaybackCandidates(video, editionFromSearch(window.location.search))
    .map((url) => {
      const type = videoMediaType(url);
      return `<source src="${attr(url)}"${type ? ` type="${attr(type)}"` : ''}>`;
    })
    .join('');
}

function empty(icon, title, hint) {
  return `<div class="text-center py-10"><div class="text-4xl mb-3 opacity-20">${icon}</div><p class="text-xs text-slate-500">${title}</p><p class="text-[11px] text-slate-600 mt-1">${hint}</p></div>`;
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = Date.now() - ts;
  if (d < 60000) return 'just now';
  if (d < 3600000) return `${Math.floor(d / 60000)}m ago`;
  if (d < 86400000) return `${Math.floor(d / 3600000)}h ago`;
  return new Date(ts).toLocaleDateString();
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
    const origin = globalThis.window?.location?.origin || 'http://localhost';
    const u = new URL(url, origin);
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

function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function attr(s) { return esc(s).replace(/"/g, '&quot;'); }
