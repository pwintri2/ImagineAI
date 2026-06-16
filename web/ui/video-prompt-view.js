import { getState, setState } from '../state.js';
import { VIDEO_MODELS } from '../services/video-gen.js';

const SUGGESTIONS = [
  'a paper boat drifting down a rain-soaked street, slow dolly shot',
  'golden autumn leaves swirling in a gust of wind over a park bench',
  'a neon koi fish swimming through dark water, bioluminescent trails',
  'time-lapse of clouds rushing over a mountain ridge at sunset',
];
const RATIOS = [
  { key: 'wide', label: '16:9' },
  { key: 'landscape', label: '4:3' },
  { key: 'square', label: '1:1' },
  { key: 'portrait', label: '3:4' },
  { key: 'tall', label: '9:16' },
];

let section;
let promptInput;
let startImageInput;

function chip(label, value, group, active, disabled = false) {
  const base = disabled
    ? 'border-white/5 text-slate-600 opacity-50 cursor-not-allowed'
    : active
      ? 'chip-active'
      : 'border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-300';
  return `<button type="button" ${disabled ? 'disabled' : ''} class="vchip px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${disabled ? '' : 'cursor-pointer'} whitespace-nowrap ${base}" data-group="${group}" data-value="${value}">${label}</button>`;
}

export function init() {
  section = document.getElementById('video-prompt-section');
  if (!section) return;
  render();
  section.addEventListener('click', handleClick);
}

function modelAvailable(id) {
  const { config } = getState();
  return !!(config.comfyReachable && config.models?.video?.[id]);
}

export function render() {
  if (!section) return;
  const s = getState();
  const wan22Ok = modelAvailable('wan22_14b');
  const wanTi2vOk = modelAvailable('wan22_ti2v_5b');
  const wan21Ok = modelAvailable('wan21_1_3b');
  const selectedImage = s._draftVideoStartImage;
  const imageError = s._draftVideoStartImageError || '';

  section.innerHTML = `
    <div class="space-y-4">
      <div class="relative">
        <textarea id="videoPromptInput" rows="3"
          class="w-full rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-base text-slate-100 placeholder-slate-500 transition-all focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30 resize-none leading-relaxed"
          placeholder="Describe the scene and its motion… e.g. a paper boat drifting down a rainy street">${escapeHtml(s._draftVideoPrompt || '')}</textarea>
      </div>

      <div id="vsuggestions" class="flex flex-wrap gap-2">
        <span class="text-xs text-slate-500 self-center mr-1">Try:</span>
        ${SUGGESTIONS.map((t, i) => `<button type="button" class="vsuggestion-chip px-3 py-1 rounded-full border border-white/10 text-xs text-slate-400 hover:border-violet-500/40 hover:text-violet-300 transition-all cursor-pointer" data-index="${i}">${escapeHtml(shorten(t))}</button>`).join('')}
      </div>

      <div class="space-y-1.5">
        <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Model</label>
        <div id="modelChips" class="flex flex-wrap gap-1.5">
          ${chip(`✨ ${VIDEO_MODELS.wan22_14b.title}`, 'wan22_14b', 'model', s.videoModel === 'wan22_14b', !wan22Ok)}
          ${chip(`🎞 ${VIDEO_MODELS.wan22_ti2v_5b.title}`, 'wan22_ti2v_5b', 'model', s.videoModel === 'wan22_ti2v_5b', !wanTi2vOk)}
          ${chip(`🪶 ${VIDEO_MODELS.wan21_1_3b.title}`, 'wan21_1_3b', 'model', s.videoModel === 'wan21_1_3b', !wan21Ok)}
        </div>
        <p class="text-[10px] text-slate-600">${escapeHtml(VIDEO_MODELS[s.videoModel]?.note || '')}</p>
      </div>

      <div class="space-y-2 rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <div class="flex items-center justify-between gap-3">
          <label for="videoStartImageInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Start image</label>
          ${selectedImage ? '<button id="clearStartImage" type="button" class="text-xs text-slate-400 hover:text-violet-300 transition-colors">Remove</button>' : ''}
        </div>
        <input id="videoStartImageInput" type="file" accept="image/png,image/jpeg,image/webp"
          class="block w-full text-xs text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-xs file:font-medium file:text-slate-200 hover:file:bg-white/15">
        <p class="text-[10px] ${imageError ? 'text-red-300' : 'text-slate-600'}">
          ${imageError ? escapeHtml(imageError) : escapeHtml(startImageLabel(selectedImage))}
        </p>
      </div>

      <div class="flex flex-wrap items-end gap-4">
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Ratio</label>
          <div id="vratioChips" class="flex gap-1.5">
            ${RATIOS.map((r) => chip(r.label, r.key, 'vratio', s.videoAspect === r.key)).join('')}
          </div>
        </div>
        <div class="space-y-1.5 flex-1 min-w-[160px]">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Length: <span id="secOut" class="text-violet-300">${s.videoSeconds}s</span></label>
          <input id="secRange" type="range" min="1" max="5" step="1" value="${s.videoSeconds}" class="range-violet w-full">
        </div>
      </div>

      <button id="videoGenerateBtn" type="button"
        class="btn-generate btn-video w-full rounded-2xl px-6 py-3.5 text-base font-semibold text-white flex items-center justify-center gap-2">
        <span id="videoBtnIcon">🎬</span><span id="videoBtnText">Create Video</span>
      </button>

      <p class="text-center text-[11px] text-slate-600">${videoHint(s, wan22Ok || wanTi2vOk || wan21Ok)}</p>
    </div>
  `;

  promptInput = document.getElementById('videoPromptInput');
  startImageInput = document.getElementById('videoStartImageInput');
  const range = document.getElementById('secRange');
  range?.addEventListener('input', () => {
    document.getElementById('secOut').textContent = `${range.value}s`;
    setState({ videoSeconds: parseInt(range.value, 10) });
  });
  startImageInput?.addEventListener('change', handleStartImageChange);
}

function videoHint(s, anyModel) {
  if (!s.config.comfyReachable) return 'ComfyUI not detected — start it to generate video.';
  if (!anyModel) return 'No Wan video model found in ComfyUI.';
  return 'Text-to-video runs locally on your GPU · can take a few minutes.';
}

function handleClick(e) {
  const c = e.target.closest('.vchip');
  if (c && !c.disabled) {
    const { group, value } = c.dataset;
    if (group === 'model') setState({ videoModel: value });
    else if (group === 'vratio') setState({ videoAspect: value });
    rememberDraft();
    render();
    promptInput?.focus();
    return;
  }
  if (e.target.closest('#clearStartImage')) {
    getState()._draftVideoStartImage = null;
    getState()._draftVideoStartImageError = '';
    render();
    return;
  }
  const sug = e.target.closest('.vsuggestion-chip');
  if (sug && promptInput) {
    promptInput.value = SUGGESTIONS[parseInt(sug.dataset.index, 10)] || '';
    promptInput.focus();
  }
}

function rememberDraft() {
  if (promptInput) getState()._draftVideoPrompt = promptInput.value;
}

async function handleStartImageChange() {
  const file = startImageInput?.files?.[0];
  const s = getState();
  if (!file) {
    s._draftVideoStartImage = null;
    s._draftVideoStartImageError = '';
    render();
    return;
  }
  if (!file.type.startsWith('image/')) {
    s._draftVideoStartImage = null;
    s._draftVideoStartImageError = 'Choose a PNG, JPG, or WebP image.';
    render();
    return;
  }
  if (file.size > 24 * 1024 * 1024) {
    s._draftVideoStartImage = null;
    s._draftVideoStartImageError = 'Choose an image under 24 MB.';
    render();
    return;
  }

  s._draftVideoStartImage = {
    dataUrl: await readFileAsDataURL(file),
    name: file.name,
    size: file.size,
  };
  s._draftVideoStartImageError = '';
  if (s.videoModel !== 'wan22_ti2v_5b' && modelAvailable('wan22_ti2v_5b')) {
    setState({ videoModel: 'wan22_ti2v_5b' });
  }
  render();
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('Could not read image.'));
    reader.readAsDataURL(file);
  });
}

function startImageLabel(image) {
  if (!image) return 'Optional. Add one to animate a still image with Wan 2.2 TI2V 5B.';
  return `Selected: ${image.name} · ${formatBytes(image.size)}`;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Save in-progress text so a re-render (e.g. background config refresh) keeps it.
export function captureDraft() { rememberDraft(); }

export function setGenerating(isLoading) {
  const btn = document.getElementById('videoGenerateBtn');
  const icon = document.getElementById('videoBtnIcon');
  const text = document.getElementById('videoBtnText');
  if (!btn) return;
  btn.disabled = isLoading;
  if (isLoading) {
    icon.innerHTML = '<span class="spinner"></span>';
    text.textContent = 'Creating video…';
  } else {
    icon.textContent = '🎬';
    text.textContent = 'Create Video';
  }
}

export function getPrompt() { return promptInput?.value?.trim() || ''; }
export function getStartImage() { return getState()._draftVideoStartImage || null; }
export function focusPrompt() { promptInput?.focus(); }

function shorten(t) { return t.length > 30 ? t.slice(0, 28) + '…' : t; }
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
