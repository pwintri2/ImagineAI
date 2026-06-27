import { getState, setState } from '../state.js';
import { ENGINES } from '../services/image-gen.js';

const SUGGESTIONS = [
  'a cozy cabin in snowy mountains at golden hour, cinematic',
  'a neon-lit cyberpunk street market at night, rain reflections',
  'a watercolor painting of cherry blossoms over a quiet river',
  'a photorealistic red fox wearing tiny round glasses, studio light',
];
const RATIOS = [
  { key: 'square', label: '1:1' },
  { key: 'landscape', label: '4:3' },
  { key: 'portrait', label: '3:4' },
  { key: 'wide', label: '16:9' },
  { key: 'tall', label: '9:16' },
];

let promptInput;
let sourceImageInput;
let section;

function chip(label, value, group, active, disabled = false) {
  const base = disabled
    ? 'border-white/5 text-slate-600 opacity-50 cursor-not-allowed'
    : active
      ? 'chip-active'
      : 'border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-300';
  return `<button type="button" ${disabled ? 'disabled' : ''} class="chip px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${disabled ? '' : 'cursor-pointer'} whitespace-nowrap ${base}" data-group="${group}" data-value="${value}">${label}</button>`;
}

export function init() {
  section = document.getElementById('prompt-section');
  if (!section) return;
  render();
  section.addEventListener('click', handleClick);
}

function engineAvailable(engineId) {
  const { config } = getState();
  if (engineId === 'local') return !!(config.comfyReachable && config.models?.image?.zimage_turbo);
  if (engineId === 'gemini') return !!config.geminiConfigured;
  if (engineId === 'xai') return !!config.xaiConfigured;
  if (engineId === 'atlas') return !!config.atlasConfigured;
  if (engineId === 'sdxl') return !!(config.sdxlConfigured || config.stabilityConfigured);
  if (engineId === 'seedance') return !!config.seedanceConfigured;
  return false;
}

export function render() {
  if (!section) return;
  const s = getState();
  const localOk = engineAvailable('local');
  const geminiOk = engineAvailable('gemini');
  const xaiOk = engineAvailable('xai');
  const atlasOk = engineAvailable('atlas');
  const sdxlOk = engineAvailable('sdxl');
  const seedanceOk = engineAvailable('seedance');
  const selectedImage = s._draftImageSourceImage;
  const imageError = s._draftImageSourceImageError || '';

  section.innerHTML = `
    <div class="space-y-4">
      <div class="relative">
        <textarea id="promptInput" rows="3"
          class="w-full rounded-2xl border border-white/10 bg-white/5 px-5 py-4 pr-14 text-base text-slate-100 placeholder-slate-500 transition-all focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30 resize-none leading-relaxed"
          placeholder="Describe your image… e.g. a cozy cabin in snowy mountains at sunset">${escapeAttr(s._draftPrompt || '')}</textarea>
        <div class="absolute right-3 bottom-3 text-[10px] text-slate-600 pointer-events-none">⌘↵</div>
      </div>

      <div id="suggestions" class="flex flex-wrap gap-2">
        <span class="text-xs text-slate-500 self-center mr-1">Try:</span>
        ${SUGGESTIONS.map((text, i) =>
          `<button type="button" class="suggestion-chip px-3 py-1 rounded-full border border-white/10 text-xs text-slate-400 hover:border-violet-500/40 hover:text-violet-300 transition-all cursor-pointer" data-index="${i}">${escapeHtml(shorten(text))}</button>`
        ).join('')}
      </div>

      <div class="space-y-2 rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <div class="flex items-center justify-between gap-3">
          <label for="imageSourceInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Reference image</label>
          ${selectedImage ? '<button id="clearSourceImage" type="button" class="text-xs text-slate-400 hover:text-violet-300 transition-colors">Remove</button>' : ''}
        </div>
        <input id="imageSourceInput" type="file" accept="image/png,image/jpeg,image/webp"
          class="block w-full text-xs text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-xs file:font-medium file:text-slate-200 hover:file:bg-white/15">
        ${selectedImage ? `
          <div class="flex items-center gap-3">
            <img src="${escapeAttr(selectedImage.dataUrl)}" alt="" class="h-14 w-14 shrink-0 rounded-lg object-cover border border-white/10">
            <p class="min-w-0 text-[10px] ${imageError ? 'text-red-300' : 'text-slate-600'}">${imageError ? escapeHtml(imageError) : escapeHtml(sourceImageLabel(selectedImage))}</p>
          </div>
        ` : `
          <p class="text-[10px] ${imageError ? 'text-red-300' : 'text-slate-600'}">${imageError ? escapeHtml(imageError) : escapeHtml(sourceImageLabel(selectedImage))}</p>
        `}
      </div>

      <div class="flex flex-wrap items-end gap-4">
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Engine</label>
          <div id="engineChips" class="flex flex-wrap gap-1.5">
            ${chip(`⚡ ${ENGINES.local.title}`, 'local', 'engine', s.imageEngine === 'local', !localOk)}
            ${chip(`☁ ${ENGINES.gemini.title}`, 'gemini', 'engine', s.imageEngine === 'gemini', !geminiOk)}
            ${chip(`𝕏 ${ENGINES.xai.title}`, 'xai', 'engine', s.imageEngine === 'xai', !xaiOk)}
            ${chip(`◆ ${ENGINES.atlas.title}`, 'atlas', 'engine', s.imageEngine === 'atlas', !atlasOk)}
            ${chip(`▣ ${ENGINES.sdxl.title}`, 'sdxl', 'engine', s.imageEngine === 'sdxl', !sdxlOk)}
            ${chip(`◈ ${ENGINES.seedance.title}`, 'seedance', 'engine', s.imageEngine === 'seedance', !seedanceOk)}
          </div>
        </div>
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Ratio</label>
          <div id="ratioChips" class="flex gap-1.5">
            ${RATIOS.map((r) => chip(r.label, r.key, 'ratio', s.aspectRatio === r.key)).join('')}
          </div>
        </div>
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Images</label>
          <div id="countBtns" class="flex gap-1.5">
            ${[1, 2, 3, 4].map((n) => chip(String(n), String(n), 'count', s.imageCount === n)).join('')}
          </div>
        </div>
      </div>

      <details class="group">
        <summary class="text-[10px] font-semibold uppercase tracking-wider text-slate-500 cursor-pointer hover:text-slate-400 transition flex items-center gap-1 select-none">
          <span class="group-open:rotate-90 transition-transform text-[8px]">▶</span> Advanced (local)
        </summary>
        <div class="mt-3 flex items-center gap-3">
          <label class="text-xs text-slate-400 w-20">Steps: <span id="stepsOut" class="text-violet-300 font-medium">${s.steps}</span></label>
          <input id="stepsRange" type="range" min="4" max="20" value="${s.steps}" class="range-violet flex-1">
        </div>
        <p class="text-[10px] text-slate-600 mt-1">Z-Image Turbo is tuned for ~8 steps. Higher = slower, not always better.</p>
      </details>

      <button id="generateBtn" type="button"
        class="btn-generate w-full rounded-2xl px-6 py-3.5 text-base font-semibold text-white flex items-center justify-center gap-2">
        <span id="btnIcon">✨</span><span id="btnText">Generate</span>
      </button>

      <p id="engineHint" class="text-center text-[11px] text-slate-600">${engineHint(s)}</p>
    </div>
  `;

  promptInput = document.getElementById('promptInput');
  sourceImageInput = document.getElementById('imageSourceInput');
  const range = document.getElementById('stepsRange');
  range?.addEventListener('input', () => {
    document.getElementById('stepsOut').textContent = range.value;
    setState({ steps: parseInt(range.value, 10) });
  });
  sourceImageInput?.addEventListener('change', handleSourceImageChange);
}

function engineHint(s) {
  if (s.imageEngine === 'gemini') return `Cloud render via ${escapeHtml(s.config.geminiModel || 'Gemini')} · uses your Google API quota`;
  if (s.imageEngine === 'xai') return `Cloud render via ${escapeHtml(s.config.xaiImageModel || 'Grok Imagine')} · uses your xAI quota`;
  if (s.imageEngine === 'atlas') return `Cloud render via ${escapeHtml(s.config.atlasImageModel || 'seedream-3.0')} · uses your Atlas quota`;
  if (s.imageEngine === 'sdxl') return `Cloud render via ${escapeHtml(s.config.modelslabImageModel || 'sdxl')} · uses your ModelsLab quota`;
  if (s.imageEngine === 'seedance') return `Seedance still via ${escapeHtml(s.config.seedanceVideoModel || 'seedance-2-0')} return_last_frame · uses Seedance video credits`;
  if (!s.config.comfyReachable) return 'ComfyUI not detected — start it, or switch to a cloud engine in Settings.';
  return 'Runs locally on your GPU · free';
}

function handleClick(e) {
  const c = e.target.closest('.chip');
  if (c && !c.disabled) {
    const { group, value } = c.dataset;
    if (group === 'engine') setState({ imageEngine: value });
    else if (group === 'ratio') setState({ aspectRatio: value });
    else if (group === 'count') setState({ imageCount: parseInt(value, 10) });
    rememberDraft();
    render();
    promptInput?.focus();
    return;
  }
  if (e.target.closest('#clearSourceImage')) {
    getState()._draftImageSourceImage = null;
    getState()._draftImageSourceImageError = '';
    render();
    return;
  }
  const sug = e.target.closest('.suggestion-chip');
  if (sug && promptInput) {
    promptInput.value = SUGGESTIONS[parseInt(sug.dataset.index, 10)] || '';
    promptInput.focus();
  }
}

function rememberDraft() {
  if (promptInput) getState()._draftPrompt = promptInput.value;
}

async function handleSourceImageChange() {
  const file = sourceImageInput?.files?.[0];
  const s = getState();
  if (!file) {
    s._draftImageSourceImage = null;
    s._draftImageSourceImageError = '';
    render();
    return;
  }
  if (!file.type.startsWith('image/')) {
    s._draftImageSourceImage = null;
    s._draftImageSourceImageError = 'Choose a PNG, JPG, or WebP image.';
    render();
    return;
  }
  if (file.size > 24 * 1024 * 1024) {
    s._draftImageSourceImage = null;
    s._draftImageSourceImageError = 'Choose an image under 24 MB.';
    render();
    return;
  }

  s._draftImageSourceImage = {
    dataUrl: await readFileAsDataURL(file),
    name: file.name,
    size: file.size,
  };
  s._draftImageSourceImageError = '';
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

function sourceImageLabel(image) {
  if (!image) return 'Optional. Edit or restyle an uploaded image with Z-Image, Gemini, or Grok Imagine.';
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
  const btn = document.getElementById('generateBtn');
  const icon = document.getElementById('btnIcon');
  const text = document.getElementById('btnText');
  if (!btn) return;
  btn.disabled = isLoading;
  if (isLoading) {
    icon.innerHTML = '<span class="spinner"></span>';
    text.textContent = 'Generating…';
  } else {
    icon.textContent = '✨';
    text.textContent = 'Generate';
  }
}

export function getPrompt() { return promptInput?.value?.trim() || ''; }
export function getSourceImage() { return getState()._draftImageSourceImage || null; }
export function focusPrompt() { promptInput?.focus(); }

function shorten(t) { return t.length > 34 ? t.slice(0, 32) + '…' : t; }
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function escapeAttr(s) { return escapeHtml(s); }
