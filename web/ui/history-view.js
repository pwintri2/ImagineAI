import { getState, subscribe, clearHistory as clearImages, clearVideoHistory } from '../state.js';

let panelEl, listEl, isOpen = false;
let historyTab = 'images';

export function init() {
  panelEl = document.getElementById('history-panel');
  listEl = document.getElementById('historyList');

  document.getElementById('historyToggle')?.addEventListener('click', toggle);
  document.getElementById('closeHistoryBtn')?.addEventListener('click', close);
  document.getElementById('historyOverlay')?.addEventListener('click', close);
  document.getElementById('clearHistoryBtn')?.addEventListener('click', handleClear);

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
  listEl.innerHTML = videoHistory.map((entry, i) => `
    <div class="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 space-y-2 fade-in" style="animation-delay:${Math.min(i, 10) * 40}ms">
      <p class="text-xs text-slate-300 line-clamp-2 px-0.5">${esc(entry.prompt)}</p>
      <div class="rounded-lg overflow-hidden bg-black">
        <video src="${entry.videos[0]?.url}" preload="metadata" class="w-full aspect-video object-contain" muted loop playsinline onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0;"></video>
      </div>
      <div class="flex items-center justify-between px-0.5">
        <span class="text-[10px] text-violet-400/80">${esc(entry.modelTitle)}</span>
        <span class="text-[10px] text-slate-600">${fmtTime(entry.createdAt)}</span>
      </div>
    </div>
  `).join('');
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

function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
