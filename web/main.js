import {
  getState, setState, loadPrefs, loadHistory, loadVideoHistory,
  saveHistoryEntry, saveVideoHistoryEntry,
} from './state.js';
import { getConfig, cancelJob, getGpu, freeGpu } from './services/api.js';
import { ENGINES, generateImage } from './services/image-gen.js';
import { generateVideo } from './services/video-gen.js';
import { friendlyError } from './services/friendly-error.js';
import {
  MODELSLAB_VIDEO_MODELS,
  STABLE_DIFFUSION_VIDEO_MODELS,
  isLocalVideoModel,
  reconcileVideoModel,
} from './services/video-model-routing.js';
import * as PromptView from './ui/prompt-view.js';
import * as GalleryView from './ui/gallery-view.js';
import * as VideoPromptView from './ui/video-prompt-view.js';
import * as VideoGalleryView from './ui/video-gallery-view.js';
import * as HistoryView from './ui/history-view.js';
import * as SettingsView from './ui/settings-view.js';
import * as TabsView from './ui/tabs-view.js';
import { showToast } from './ui/toast-view.js';

document.addEventListener('DOMContentLoaded', async () => {
  loadPrefs();
  loadHistory();
  loadVideoHistory();

  PromptView.init();
  GalleryView.init();
  VideoPromptView.init();
  VideoGalleryView.init();
  TabsView.init(() => {});
  HistoryView.init();
  SettingsView.init(onConfigChange);

  // Delegate on the stable section wrappers: the prompt panels re-render their
  // innerHTML (replacing the buttons) when ComfyUI availability changes, which
  // would orphan a handler bound directly to the button.
  document.getElementById('image-section')?.addEventListener('click', (e) => {
    if (e.target.closest('#generateBtn')) handleGenerateImage();
  });
  document.getElementById('video-section')?.addEventListener('click', (e) => {
    if (e.target.closest('#videoGenerateBtn')) handleGenerateVideo();
  });
  // ⌘/Ctrl+Enter to generate from either prompt box
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey)) return;
    if (TabsView.getActiveTab() === 'video') handleGenerateVideo();
    else handleGenerateImage();
  });

  document.getElementById('gpuFreeBtn')?.addEventListener('click', handleFreeGpu);

  await refreshConfig(true);
  // Keep checking in the background so a late-starting ComfyUI (it shares the
  // GPU and may be mid-model-load at launch) self-heals to "ready" without the
  // user touching anything.
  setInterval(() => refreshConfig(false), 7000);
  refreshGpu();
  setInterval(refreshGpu, 7000);
});

async function refreshGpu() {
  const widget = document.getElementById('gpuWidget');
  if (!widget) return;
  try {
    const gpu = await getGpu();
    if (!gpu.available) { widget.classList.remove('sm:flex'); return; }
    widget.classList.add('sm:flex');  // 'hidden' stays for small screens, like engineStatus
    const pct = Math.max(0, Math.min(100, Math.round((gpu.usedMb / gpu.totalMb) * 100)));
    const fill = document.getElementById('gpuBatteryFill');
    if (fill) {
      fill.style.width = `${Math.max(pct > 0 ? 6 : 0, pct)}%`;
      fill.style.background = pct > 85 ? '#f87171' : (pct > 60 ? '#fbbf24' : '#34d399');
    }
    const label = document.getElementById('gpuLabel');
    if (label) label.textContent = `${(gpu.usedMb / 1024).toFixed(1)}/${(gpu.totalMb / 1024).toFixed(1)} GB`;
    widget.title = `GPU-geheugen: ${pct}% in gebruik (${gpu.usedMb} MB van ${gpu.totalMb} MB)`;
  } catch {
    /* server briefly unreachable — keep the last reading */
  }
}

async function handleFreeGpu() {
  const btn = document.getElementById('gpuFreeBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Bezig…'; }
  try {
    const result = await freeGpu();
    showToast(result.message || 'GPU leeggemaakt.', 'success');
  } catch (err) {
    showToast(err.message || 'Kon de GPU niet leegmaken.', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Leeg GPU'; }
    // VRAM release takes a moment; refresh twice so the battery settles.
    setTimeout(refreshGpu, 1000);
    setTimeout(refreshGpu, 4000);
  }
}

let configInFlight = false;
let lastAvailKey = '';

function availabilityKey(config) {
  return JSON.stringify({
    reach: !!config.comfyReachable,
    img: config.models?.image || {},
    vid: config.models?.video || {},
    gem: !!config.geminiConfigured,
    xai: !!config.xaiConfigured,
    atlas: !!config.atlasConfigured,
    sdxl: !!(config.sdxlConfigured || config.stabilityConfigured),
    modelslab: !!config.modelslabConfigured,
    seedance: !!config.seedanceConfigured,
    sora: !!config.soraConfigured,
    eleven: !!config.elevenlabsConfigured,
  });
}

async function refreshConfig(force) {
  if (configInFlight) return;
  configInFlight = true;
  try {
    const config = await getConfig();
    applyConfig(config, force);
  } catch (e) {
    setStatus(false, 'reconnecting…');
  } finally {
    configInFlight = false;
  }
}

// `force` re-renders even if nothing changed (used for explicit user actions);
// otherwise we only re-render the prompt panels when availability actually
// changes, so a background poll never wipes text you're typing.
function applyConfig(config, force) {
  setState({ config });
  reconcileEngine(config);
  updateStatus(config);
  const key = availabilityKey(config);
  if (force || key !== lastAvailKey) {
    lastAvailKey = key;
    PromptView.captureDraft();
    VideoPromptView.captureDraft();
    PromptView.render();
    VideoPromptView.render();
  }
}

// Called by the Settings panel after the user saves/recHecks.
function onConfigChange(config) {
  applyConfig(config, true);
}

// Pick a usable default engine/model if the saved one is unavailable.
function reconcileEngine(config) {
  const s = getState();
  const localImg = !!(config.comfyReachable && config.models?.image?.zimage_turbo);
  const fluxImg = !!(config.comfyReachable && config.models?.image?.flux1_schnell_fp8);
  const gemini = !!config.geminiConfigured;
  const xai = !!config.xaiConfigured;
  const atlas = !!config.atlasConfigured;
  const sdxl = !!(config.sdxlConfigured || config.stabilityConfigured);
  const seedance = !!config.seedanceConfigured;
  let engine = s.imageEngine;
  const localFallback = localImg ? 'local' : (fluxImg ? 'flux' : '');
  if (engine === 'local' && !localImg) engine = fluxImg ? 'flux' : (xai ? 'xai' : (atlas ? 'atlas' : (seedance ? 'seedance' : (sdxl ? 'sdxl' : (gemini ? 'gemini' : engine)))));
  if (engine === 'flux' && !fluxImg) engine = localImg ? 'local' : (xai ? 'xai' : (atlas ? 'atlas' : (seedance ? 'seedance' : (sdxl ? 'sdxl' : (gemini ? 'gemini' : engine)))));
  if (engine === 'gemini' && !gemini) engine = localFallback || (xai ? 'xai' : (atlas ? 'atlas' : (seedance ? 'seedance' : (sdxl ? 'sdxl' : engine))));
  if (engine === 'xai' && !xai) engine = localFallback || (atlas ? 'atlas' : (seedance ? 'seedance' : (sdxl ? 'sdxl' : (gemini ? 'gemini' : engine))));
  if (engine === 'atlas' && !atlas) engine = localFallback || (xai ? 'xai' : (seedance ? 'seedance' : (sdxl ? 'sdxl' : (gemini ? 'gemini' : engine))));
  if (engine === 'sdxl' && !sdxl) engine = localFallback || (xai ? 'xai' : (atlas ? 'atlas' : (seedance ? 'seedance' : (gemini ? 'gemini' : engine))));
  if (engine === 'seedance' && !seedance) engine = localFallback || (xai ? 'xai' : (atlas ? 'atlas' : (sdxl ? 'sdxl' : (gemini ? 'gemini' : engine))));
  if (engine !== s.imageEngine) setState({ imageEngine: engine });

  const vModel = reconcileVideoModel(s.videoModel, config);
  if (vModel !== s.videoModel) setState({ videoModel: vModel });
}

function updateStatus(config) {
  const localImg = !!(config.comfyReachable && config.models?.image?.zimage_turbo);
  const fluxImg = !!(config.comfyReachable && config.models?.image?.flux1_schnell_fp8);
  if (localImg) setStatus(true, 'ComfyUI ready');
  else if (fluxImg) setStatus(true, 'FLUX ready');
  else if (config.xaiConfigured) setStatus(true, 'Grok ready');
  else if (config.atlasConfigured) setStatus(true, 'Atlas ready');
  else if (config.seedanceConfigured) setStatus(true, 'Seedance ready');
  else if (config.modelslabConfigured) setStatus(true, 'ModelsLab ready');
  else if (config.sdxlConfigured || config.stabilityConfigured) setStatus(true, 'SDXL ready');
  else if (config.geminiConfigured) setStatus(true, 'Gemini ready');
  else if (config.comfyReachable) setStatus(true, 'ComfyUI (no Z-Image)');
  else setStatus(false, 'ComfyUI offline');
}

function setStatus(ok, label) {
  const wrap = document.getElementById('engineStatus');
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusLabel');
  if (wrap) wrap.classList.remove('hidden');
  if (dot) dot.className = `w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`;
  if (text) text.textContent = label;
}

async function handleGenerateImage() {
  const prompt = PromptView.getPrompt();
  if (!prompt) { showToast('Describe what you want to see', 'info'); PromptView.focusPrompt(); return; }

  const s = getState();
  if (s.isGenerating) return;
  const engine = s.imageEngine;
  const localImg = !!(s.config.comfyReachable && s.config.models?.image?.zimage_turbo);
  const fluxImg = !!(s.config.comfyReachable && s.config.models?.image?.flux1_schnell_fp8);
  if (engine === 'local' && !localImg) { showToast('ComfyUI / Z-Image not available. Add a cloud key or start ComfyUI.', 'error'); return; }
  if (engine === 'flux' && !fluxImg) { showToast('ComfyUI / FLUX.1 Schnell not available. Download the FP8 checkpoint or start ComfyUI.', 'error'); return; }
  if (engine === 'gemini' && !s.config.geminiConfigured) { showToast('No Gemini key saved — open Settings to add one.', 'error'); return; }
  if (engine === 'xai' && !s.config.xaiConfigured) { showToast('No xAI key saved — open Settings to add one.', 'error'); return; }
  if (engine === 'atlas' && !s.config.atlasConfigured) { showToast('No Atlas key saved — open Settings to add one as atlas.', 'error'); return; }
  if (engine === 'seedance' && !s.config.seedanceConfigured) { showToast('No Seedance key saved — open Settings to add one as seedance.', 'error'); return; }
  if (engine === 'sdxl' && !(s.config.sdxlConfigured || s.config.stabilityConfigured)) { showToast('No ModelsLab/SDXL key saved — open Settings to add one.', 'error'); return; }
  const sourceImage = PromptView.getSourceImage();
  if (sourceImage && !['local', 'gemini', 'xai', 'atlas'].includes(engine)) {
    showToast('Reference images work with Z-Image, Gemini, Grok Imagine, or Atlas. Select one of those first.', 'info');
    return;
  }

  setState({ isGenerating: true });
  PromptView.setGenerating(true);
  const count = s.imageCount;
  const loadingLabel = sourceImage
    ? (engine === 'gemini' ? 'Asking Gemini to edit…' : (engine === 'xai' ? 'Asking Grok Imagine to edit…' : (engine === 'atlas' ? 'Asking Atlas to edit…' : 'Editing on your GPU…')))
    : (engine === 'gemini' ? 'Asking Gemini…' : (engine === 'xai' ? 'Asking Grok Imagine…' : (engine === 'atlas' ? 'Asking Atlas…' : (engine === 'seedance' ? 'Asking Seedance…' : (engine === 'sdxl' ? 'Asking ModelsLab…' : (engine === 'flux' ? 'Rendering with FLUX.1…' : 'Rendering on your GPU…'))))));
  GalleryView.renderLoading(count, { label: loadingLabel });
  const started = Date.now();

  try {
    const progressBase = sourceImage
      ? (engine === 'gemini' ? 'Gemini is editing' : (engine === 'xai' ? 'Grok Imagine is editing' : (engine === 'atlas' ? 'Atlas is editing' : 'Z-Image editing')))
      : (engine === 'gemini' ? 'Gemini is painting' : (engine === 'xai' ? 'Grok Imagine is painting' : (engine === 'atlas' ? 'Atlas is painting' : (engine === 'seedance' ? 'Seedance is rendering a still' : (engine === 'sdxl' ? 'ModelsLab is painting' : (engine === 'flux' ? 'FLUX.1 rendering' : 'Z-Image rendering'))))));
    const { results, modelTitle } = await generateImage(
      { prompt, engine, aspect: s.aspectRatio, count, steps: s.steps, sourceImage },
      (job) => GalleryView.updateStatus(progressLabel(job, started, progressBase)),
    );
    if (!results.length) throw new Error('No images were returned.');
    GalleryView.renderResults(results, { prompt });
    showToast('Image created!', 'success');
    saveHistoryEntry({ prompt, modelTitle, images: results, sourceImageName: sourceImage?.name || '', createdAt: Date.now() });
  } catch (err) {
    console.error('Image generation failed:', err);
    const message = friendlyError(err, {
      kind: 'image',
      usesLocalGpu: ['local', 'flux'].includes(engine),
      providerLabel: ENGINES[engine]?.title || engine,
    });
    GalleryView.renderError(message);
    showToast(message, 'error');
  } finally {
    setState({ isGenerating: false });
    PromptView.setGenerating(false);
  }
}

async function handleGenerateVideo() {
  const prompt = VideoPromptView.getPrompt();
  if (!prompt) { showToast('Describe the scene you want', 'info'); VideoPromptView.focusPrompt(); return; }

  const s = getState();
  if (s.isGeneratingVideo) return;
  const model = s.videoModel;
  const directorReady = !!(s.config.atlasConfigured || s.config.xaiConfigured || s.config.geminiConfigured);
  const available = model === 'xai'
    ? !!s.config.xaiConfigured
    : model === 'atlas'
      ? !!s.config.atlasConfigured
    : model === 'veo'
      ? !!s.config.geminiConfigured
    : model === 'sora'
      ? !!s.config.soraConfigured
    : model === 'director'
      ? directorReady
    : model === 'seedance'
      ? !!s.config.seedanceConfigured
    : MODELSLAB_VIDEO_MODELS.includes(model)
      ? !!s.config.modelslabConfigured
    : !!(s.config.comfyReachable && s.config.models?.video?.[model]);
  if (!available) {
    showToast(model === 'xai'
      ? 'No xAI key saved — open Settings to add one.'
      : (model === 'atlas' ? 'No Atlas key saved — open Settings to add one as atlas.'
        : (model === 'veo' ? 'No Gemini key saved — open Settings to add one to use Veo.'
          : (model === 'sora' ? 'No OpenAI key saved — open Settings to add one as sora or openai.'
            : (model === 'director' ? 'Director needs at least one cloud engine key: Atlas, xAI (Grok), or Gemini (Veo).'
              : (model === 'seedance' ? 'No Seedance key saved — open Settings to add one as seedance.'
                : (MODELSLAB_VIDEO_MODELS.includes(model) ? 'No ModelsLab or Stable Diffusion API key saved — open Settings to add one.'
                  : 'That video model is not available in ComfyUI.')))))),
    'error');
    return;
  }
  const startImages = VideoPromptView.getStartImages();
  if (startImages.length && !['wan22_ti2v_5b', 'wan22_14b', 'xai', 'atlas', 'veo', 'director'].includes(model)) {
    showToast('Start images work with Wan 2.2 TI2V 5B / 14B, Grok Imagine, Atlas, Veo, or Director. Select one of those first.', 'info');
    return;
  }
  const mergeStartImages = VideoPromptView.getMergeStartImages() && startImages.length > 1;
  if (startImages.length > 1 && !mergeStartImages && !['wan22_ti2v_5b', 'wan22_14b', 'xai'].includes(model)) {
    showToast('Only the first image is used here. Multiple images mix on Grok, become keyframes on local Wan 2.2, or flip the Merge switch to combine them into one picture.', 'info');
  }

  const seconds = videoSecondsForModel(model, s.videoSeconds);
  const isLocalModel = isLocalVideoModel(model);
  let currentJobId = null;
  setState({ isGeneratingVideo: true });
  VideoPromptView.setGenerating(true);
  VideoGalleryView.renderLoading({ modelTitle: videoModelTitle(model), showControls: isLocalModel });
  VideoGalleryView.onCancelClick(async () => {
    if (!currentJobId) return;
    VideoGalleryView.markCancelling();
    try { await cancelJob(currentJobId); } catch (e) { console.warn('Cancel failed:', e); }
  });
  const started = Date.now();
  // Long local clips render block-by-block and can run for a while; give the poll a wide window.
  const timeoutMs = Math.max(60 * 60 * 1000, seconds * 4 * 60 * 1000);

  try {
    const progressBase = model === 'xai' ? 'Grok Imagine is rendering' : (model === 'atlas' ? 'Atlas is rendering' : (model === 'veo' ? 'Gemini Veo is rendering' : (model === 'sora' ? 'Sora is rendering' : (model === 'director' ? 'Director is filming' : (model === 'seedance' ? 'Seedance is rendering' : (MODELSLAB_VIDEO_MODELS.includes(model) ? 'Stable Diffusion is rendering' : 'Wan is generating frames'))))));
    const { results, modelTitle, status } = await generateVideo(
      {
        prompt,
        model,
        aspect: s.videoAspect,
        seconds,
        startImage: startImages[0] || null,
        startImages,
        mergeStartImages,
        negativePrompt: VideoPromptView.supportsNegativePrompt(model) ? (s.videoNegativePrompt || '').trim() : '',
        seed: VideoPromptView.supportsSeed(model) ? s.videoSeed : '',
        soundtrack: s.config.elevenlabsConfigured ? (s.videoSoundtrack || '').trim() : '',
      },
      (job) => {
        VideoGalleryView.updateStatus(videoProgressLabel(job, started, progressBase));
        VideoGalleryView.updateProgress(job.meta?.progress, job.meta?.note);
      },
      { onStart: (id) => { currentJobId = id; }, timeoutMs },
    );
    if (status === 'cancelled') {
      VideoGalleryView.renderCancelled();
      showToast('Video cancelled.', 'info');
    } else {
      if (!results.length) throw new Error('No video was returned.');
      VideoGalleryView.renderResults(results, { modelTitle, prompt });
      const warning = results[0]?.soundtrackWarning
        || (results[0]?.stitchStatus !== 'segments' ? results[0]?.stitchWarning : '');
      if (warning) showToast(warning, 'info');
      showToast('Video created!', 'success');
      saveVideoHistoryEntry({ prompt, modelTitle, videos: results, createdAt: Date.now() });
    }
  } catch (err) {
    console.error('Video generation failed:', err);
    const message = friendlyError(err, {
      kind: 'video',
      usesLocalGpu: isLocalModel,
      providerLabel: videoModelTitle(model),
    });
    VideoGalleryView.renderError(message);
    showToast(message, 'error');
  } finally {
    setState({ isGeneratingVideo: false });
    VideoPromptView.setGenerating(false);
  }
}

function videoProgressLabel(job, started, base) {
  const meta = job.meta || {};
  const elapsed = Math.max(0, Math.round((Date.now() - started) / 1000));
  if (meta.phase === 'stitch' || meta.phase === 'done') {
    return `Stitching blocks together… ${elapsed}s`;
  }
  if (meta.phase === 'block' && meta.blockTotal) {
    const done = Math.round(meta.producedSeconds || 0);
    const target = Math.round(meta.targetSeconds || 0);
    const secLabel = meta.blockSeconds ? ` · ${meta.blockSeconds}s block` : '';
    return `Block ${meta.blockIndex}/${meta.blockTotal}${secLabel} · ${done}/${target}s done · ${elapsed}s`;
  }
  return progressLabel(job, started, base);
}

function videoSecondsForModel(model, seconds) {
  const parsed = Number.parseInt(seconds, 10);
  const value = Number.isFinite(parsed) ? parsed : 2;
  const cloudLong = MODELSLAB_VIDEO_MODELS.includes(model);
  const local = isLocalVideoModel(model);
  const max = model === 'director' ? 180
    : (['atlas', 'xai', 'veo', 'sora'].includes(model) ? 60
      : (model === 'seedance' ? 30 : ((cloudLong || local) ? 120 : 5)));
  return Math.max(1, Math.min(max, value));
}

function videoModelTitle(model) {
  if (model === 'xai') return 'Grok Imagine Video';
  if (model === 'atlas') return 'Atlas Video';
  if (model === 'veo') return 'Gemini Veo';
  if (model === 'sora') return 'Sora (OpenAI)';
  if (model === 'director') return 'Director';
  if (model === 'seedance') return 'Seedance 2.0 Video';
  if (STABLE_DIFFUSION_VIDEO_MODELS.includes(model)) return 'Stable Diffusion Video';
  if (model === 'wan2.6-t2v') return 'wan2.6-t2v';
  if (model === 'wan22_ti2v_5b') return 'Wan 2.2 TI2V 5B';
  if (model === 'wanvideo_5b') return 'WanVideo 5B (long)';
  if (model === 'wan22_14b') return 'Wan 2.2 14B';
  return 'Wan 2.1 1.3B';
}

function progressLabel(job, started, base) {
  const secs = Math.max(0, Math.round((Date.now() - started) / 1000));
  const state = job.status === 'queued' ? 'queued' : 'running';
  return `${base}… ${secs}s (${state})`;
}
