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
const STABLE_DIFFUSION_VIDEO_MODELS = ['sdxl', 'stable-diffusion-api'];
const MODELSLAB_VIDEO_MODELS = [...STABLE_DIFFUSION_VIDEO_MODELS, 'wan2.6-t2v'];

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

const LOCAL_WAN_MODELS = ['wanvideo_5b', 'wan22_14b', 'wan22_ti2v_5b', 'wan21_1_3b'];

function maxSecondsForModel(model) {
  if (['xai', 'atlas', 'seedance'].includes(model)) return 30;
  if (MODELSLAB_VIDEO_MODELS.includes(model)) return 120;   // cloud, stitched — no local VRAM used
  if (LOCAL_WAN_MODELS.includes(model)) return 120;   // rendered in ~10s blocks, stitched together
  return 5;
}

export function init() {
  section = document.getElementById('video-prompt-section');
  if (!section) return;
  render();
  section.addEventListener('click', handleClick);
}

function modelAvailable(id) {
  const { config } = getState();
  if (id === 'xai') return !!config.xaiConfigured;
  if (id === 'atlas') return !!config.atlasConfigured;
  if (id === 'seedance') return !!config.seedanceConfigured;
  if (MODELSLAB_VIDEO_MODELS.includes(id)) return !!config.modelslabConfigured;
  return !!(config.comfyReachable && config.models?.video?.[id]);
}

function isStableDiffusionVideo(model) {
  return STABLE_DIFFUSION_VIDEO_MODELS.includes(model);
}

export function render() {
  if (!section) return;
  const s = getState();
  const wanVideoOk = modelAvailable('wanvideo_5b');
  const wan22Ok = modelAvailable('wan22_14b');
  const wanTi2vOk = modelAvailable('wan22_ti2v_5b');
  const wan21Ok = modelAvailable('wan21_1_3b');
  const xaiOk = modelAvailable('xai');
  const atlasOk = modelAvailable('atlas');
  const seedanceOk = modelAvailable('seedance');
  const stableDiffusionOk = modelAvailable('stable-diffusion-api');
  const showModelslab = !!s.config.modelslabConfigured;
  const startImages = s._draftVideoStartImages || [];
  const mergeOn = !!s._draftVideoMergeStartImages;
  const imageError = s._draftVideoStartImageError || '';
  const maxSeconds = maxSecondsForModel(s.videoModel);
  const selectedSeconds = Math.min(s.videoSeconds, maxSeconds);

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
          ${chip(`𝕏 ${VIDEO_MODELS.xai.title}`, 'xai', 'model', s.videoModel === 'xai', !xaiOk)}
          ${chip(`◆ ${VIDEO_MODELS.atlas.title}`, 'atlas', 'model', s.videoModel === 'atlas', !atlasOk)}
          ${chip(`◈ ${VIDEO_MODELS.seedance.title}`, 'seedance', 'model', s.videoModel === 'seedance', !seedanceOk)}
          ${chip(`▣ ${VIDEO_MODELS['stable-diffusion-api'].title}`, 'stable-diffusion-api', 'model', isStableDiffusionVideo(s.videoModel), !stableDiffusionOk)}
          ${showModelslab ? chip(`▣ ${VIDEO_MODELS['wan2.6-t2v'].title}`, 'wan2.6-t2v', 'model', s.videoModel === 'wan2.6-t2v', !modelAvailable('wan2.6-t2v')) : ''}
          ${chip(`🎬 ${VIDEO_MODELS.wanvideo_5b.title}`, 'wanvideo_5b', 'model', s.videoModel === 'wanvideo_5b', !wanVideoOk)}
          ${chip(`✨ ${VIDEO_MODELS.wan22_14b.title}`, 'wan22_14b', 'model', s.videoModel === 'wan22_14b', !wan22Ok)}
          ${chip(`🎞 ${VIDEO_MODELS.wan22_ti2v_5b.title}`, 'wan22_ti2v_5b', 'model', s.videoModel === 'wan22_ti2v_5b', !wanTi2vOk)}
          ${chip(`🪶 ${VIDEO_MODELS.wan21_1_3b.title}`, 'wan21_1_3b', 'model', s.videoModel === 'wan21_1_3b', !wan21Ok)}
        </div>
        <p class="text-[10px] text-slate-600">${escapeHtml(VIDEO_MODELS[s.videoModel]?.note || '')}</p>
      </div>

      <div class="space-y-2 rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <div class="flex items-center justify-between gap-3">
          <label for="videoStartImageInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Start images${startImages.length ? ` · ${startImages.length}` : ''}</label>
          ${startImages.length ? '<button id="clearStartImages" type="button" class="text-xs text-slate-400 hover:text-violet-300 transition-colors">Clear all</button>' : ''}
        </div>
        ${startImages.length ? `<div class="flex flex-wrap gap-2">
          ${startImages.map((img, i) => `
            <div class="relative">
              <img src="${escapeAttr(img.dataUrl)}" alt="${escapeAttr(img.name)}" title="${escapeAttr(img.name)}"
                class="h-16 w-16 rounded-lg object-cover border border-white/10 bg-black/30">
              <span class="absolute -top-1.5 -left-1.5 rounded-full bg-violet-600 text-white text-[9px] font-bold w-4 h-4 flex items-center justify-center shadow">${i + 1}</span>
              <button type="button" data-remove-image="${i}" aria-label="Remove image ${i + 1}"
                class="absolute -top-1.5 -right-1.5 rounded-full bg-black/70 text-white text-[11px] leading-none w-4 h-4 flex items-center justify-center hover:bg-red-500 transition-colors">×</button>
            </div>`).join('')}
        </div>` : ''}
        ${startImages.length > 1 ? `<div class="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
          <div class="min-w-0">
            <p class="text-xs font-medium text-slate-300">Merge into one picture</p>
            <p class="text-[10px] text-slate-600">Atlas combines all pictures into a single base image for the video.</p>
          </div>
          <button id="mergeStartImagesToggle" type="button" role="switch" aria-checked="${mergeOn}" aria-label="Merge start images into one picture"
            class="relative h-5 w-9 shrink-0 rounded-full transition-colors ${mergeOn ? 'bg-violet-600' : 'bg-white/15'}">
            <span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${mergeOn ? 'translate-x-4' : ''}"></span>
          </button>
        </div>` : ''}
        <input id="videoStartImageInput" type="file" multiple accept="image/png,image/jpeg,image/webp"
          class="block w-full text-xs text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-xs file:font-medium file:text-slate-200 hover:file:bg-white/15">
        <p class="text-[10px] ${imageError ? 'text-red-300' : 'text-slate-600'}">
          ${imageError ? escapeHtml(imageError) : escapeHtml(startImagesLabel(startImages))}
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
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Length: <span id="secOut" class="text-violet-300">${selectedSeconds}s</span></label>
          <input id="secRange" type="range" min="1" max="${maxSeconds}" step="1" value="${selectedSeconds}" class="range-violet w-full">
        </div>
      </div>

      <button id="videoGenerateBtn" type="button"
        class="btn-generate btn-video w-full rounded-2xl px-6 py-3.5 text-base font-semibold text-white flex items-center justify-center gap-2">
        <span id="videoBtnIcon">🎬</span><span id="videoBtnText">Create Video</span>
      </button>

      <p class="text-center text-[11px] text-slate-600">${videoHint(s, wanVideoOk || wan22Ok || wanTi2vOk || wan21Ok || xaiOk || atlasOk || seedanceOk || stableDiffusionOk)}</p>
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
  if (s.videoModel === 'xai') {
    if (!s.config.xaiConfigured) return 'Add an xAI key in Settings to generate Grok videos.';
    return 'Grok Imagine supports up to 15s per API call; 16-30s is stitched locally from multiple Grok segments.';
  }
  if (s.videoModel === 'atlas') {
    if (!s.config.atlasConfigured) return 'Add an Atlas key in Settings as atlas to generate Atlas videos.';
    return `Atlas Cloud video via ${escapeHtml(s.config.atlasVideoModel || 'alibaba/wan-2.7/text-to-video')} · 16-30s is stitched locally from multiple Wan 2.7 segments.`;
  }
  if (s.videoModel === 'seedance') {
    if (!s.config.seedanceConfigured) return 'Add a Seedance key in Settings as seedance to generate Seedance videos.';
    return `Seedance 2.0 video via ${escapeHtml(s.config.seedanceVideoModel || 'seedance-2-0')} · 16-30s is stitched locally from multiple Seedance segments.`;
  }
  if (isStableDiffusionVideo(s.videoModel)) {
    if (!s.config.modelslabConfigured) return 'Add a ModelsLab or Stable Diffusion API key in Settings to generate Stable Diffusion videos.';
    return `Stable Diffusion video via ${escapeHtml(s.config.modelslabVideoModel || 'wan2.2')} · runs in the cloud (no local VRAM) · up to 120s stitched from ~5s segments, so long clips use more API credits.`;
  }
  if (s.videoModel === 'wan2.6-t2v') return 'wan2.6-t2v runs in the cloud via ModelsLab (no local GPU/VRAM) · up to 120s stitched from ~5s segments · long clips use more API credits, and continuity is prompt-based.';
  if (!s.config.comfyReachable) return 'ComfyUI not detected — start it to generate video.';
  if (!anyModel) return 'No Wan video model found in ComfyUI.';
  if (s.videoModel === 'wanvideo_5b') {
    if (!modelAvailable('wanvideo_5b')) return 'Install the WanVideoWrapper custom node in ComfyUI to use this.';
    return 'WanVideoWrapper · block-swap streams the model through system RAM (fits 8GB) and context windows keep one coherent clip up to 120s. Slow but no drift — test a short clip first.';
  }
  if (s.videoSeconds > 10) {
    const cont = modelAvailable('wan22_ti2v_5b')
      ? 'each ~10s block seeds the next one from its last frame for a continuous flow'
      : 'blocks are joined end to end (install TI2V 5B for frame-accurate continuity)';
    return `Long clips render locally in ~10s blocks — ${cont}. Block size drops automatically if the GPU runs low; you can cancel anytime. This can take a while.`;
  }
  return 'Text-to-video runs locally on your GPU · can take a few minutes. Up to 120s renders in stitched ~10s blocks.';
}

function handleClick(e) {
  const c = e.target.closest('.vchip');
  if (c && !c.disabled) {
    const { group, value } = c.dataset;
    if (group === 'model') setState({ videoModel: value, videoSeconds: Math.min(getState().videoSeconds, maxSecondsForModel(value)) });
    else if (group === 'vratio') setState({ videoAspect: value });
    rememberDraft();
    render();
    promptInput?.focus();
    return;
  }
  const removeBtn = e.target.closest('[data-remove-image]');
  if (removeBtn) {
    const idx = parseInt(removeBtn.dataset.removeImage, 10);
    const images = getState()._draftVideoStartImages || [];
    if (Number.isInteger(idx) && idx >= 0 && idx < images.length) images.splice(idx, 1);
    getState()._draftVideoStartImageError = '';
    render();
    return;
  }
  if (e.target.closest('#mergeStartImagesToggle')) {
    getState()._draftVideoMergeStartImages = !getState()._draftVideoMergeStartImages;
    rememberDraft();
    render();
    return;
  }
  if (e.target.closest('#clearStartImages')) {
    getState()._draftVideoStartImages = [];
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

const MAX_START_IMAGES = 8;
const START_IMAGE_MODELS = ['wan22_ti2v_5b', 'wan22_14b', 'xai', 'atlas'];

async function handleStartImageChange() {
  const files = Array.from(startImageInput?.files || []);
  const s = getState();
  if (!files.length) return;
  s._draftVideoStartImages = s._draftVideoStartImages || [];
  let error = '';
  for (const file of files) {
    if (s._draftVideoStartImages.length >= MAX_START_IMAGES) { error = `Up to ${MAX_START_IMAGES} images.`; break; }
    if (!file.type.startsWith('image/')) { error = 'Choose PNG, JPG, or WebP images.'; continue; }
    if (file.size > 24 * 1024 * 1024) { error = `${file.name} is over 24 MB.`; continue; }
    // eslint-disable-next-line no-await-in-loop
    s._draftVideoStartImages.push({ dataUrl: await readFileAsDataURL(file), name: file.name, size: file.size });
  }
  s._draftVideoStartImageError = error;
  if (startImageInput) startImageInput.value = ''; // let the same file be picked again later
  // Point at a model that supports start images if the current one doesn't.
  if (s._draftVideoStartImages.length && !START_IMAGE_MODELS.includes(s.videoModel)) {
    if (modelAvailable('wan22_ti2v_5b')) setState({ videoModel: 'wan22_ti2v_5b' });
    else if (modelAvailable('xai')) setState({ videoModel: 'xai' });
    else if (modelAvailable('atlas')) setState({ videoModel: 'atlas' });
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

function startImagesLabel(images) {
  if (!images.length) {
    return 'Optional. Add one or more images. Grok mixes multiple images into one clip; local Wan 2.2 TI2V/14B travels through them as keyframes; Atlas uses the first only.';
  }
  if (images.length === 1) return `1 start frame · ${formatBytes(images[0].size)}`;
  return `${images.length} images · Grok blends them; local Wan uses them as keyframes in order.`;
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
export function getStartImages() { return getState()._draftVideoStartImages || []; }
export function getMergeStartImages() { return !!getState()._draftVideoMergeStartImages; }
export function getStartImage() { return (getState()._draftVideoStartImages || [])[0] || null; }
export function focusPrompt() { promptInput?.focus(); }

function shorten(t) { return t.length > 30 ? t.slice(0, 28) + '…' : t; }
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }
