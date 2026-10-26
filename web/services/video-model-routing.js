export const STABLE_DIFFUSION_VIDEO_MODELS = Object.freeze(['sdxl', 'stable-diffusion-api']);
export const MODELSLAB_VIDEO_MODELS = Object.freeze([
  ...STABLE_DIFFUSION_VIDEO_MODELS,
  'wan2.6-t2v',
]);
export const LOCAL_VIDEO_MODELS = Object.freeze([
  'wanvideo_5b',
  'wan22_14b',
  'wan22_ti2v_5b',
  'wan21_1_3b',
]);
export const SORA_RETIREMENT_MESSAGE = 'OpenAI retired the Sora API on September 24, 2026. Choose another video model.';

export function seedanceService(config = {}) {
  return config.seedanceService === 'byteplus' ? 'byteplus' : 'seevio';
}

export function seedanceProviderLabel(config = {}) {
  return seedanceService(config) === 'byteplus' ? 'BytePlus ModelArk' : 'Seevio';
}

export function seedanceVideoTitle(config = {}) {
  return `Seedance · ${seedanceProviderLabel(config)}`;
}

export function supportsVideoStartImage(model, config = {}) {
  if (model === 'seedance') return seedanceService(config) === 'byteplus';
  return ['wan22_ti2v_5b', 'wan22_14b', 'xai', 'atlas', 'gemini', 'veo', 'director'].includes(model);
}

export function isLocalVideoModel(model) {
  return LOCAL_VIDEO_MODELS.includes(model);
}

export function isGeminiOmniVideoModel(model, config = {}) {
  return ['gemini', 'veo'].includes(model)
    && (config.veoVideoModel || 'gemini-omni-1.1-flash').startsWith('gemini-omni-');
}

export function isAtlasWan3VideoModel(model, config = {}) {
  return model === 'atlas'
    && /\/wan-3\.0(?:-prime)?\//i.test(config.atlasVideoModel || 'alibaba/wan-3.0/text-to-video');
}

export function videoAspectForModel(model, aspect, config = {}) {
  if (isGeminiOmniVideoModel(model, config)) return ['tall', 'portrait'].includes(aspect) ? 'tall' : 'wide';
  return aspect;
}

export function videoDurationLimits(model) {
  if (model === 'gemini' || model === 'veo') return { min: 4, max: 60, step: 2 };
  if (model === 'seedance') return { min: 4, max: 30, step: 1 };
  const max = model === 'director' ? 180
    : (['atlas', 'xai', 'sora'].includes(model) ? 60
      : (MODELSLAB_VIDEO_MODELS.includes(model) || isLocalVideoModel(model) ? 120 : 5));
  return { min: 1, max, step: 1 };
}

export function videoSecondsForModel(model, seconds) {
  const { min, max, step } = videoDurationLimits(model);
  const parsed = Number.parseInt(seconds, 10);
  const value = Number.isFinite(parsed) ? parsed : 2;
  const clamped = Math.max(min, Math.min(max, value));
  // Google's 4/6/8-second segments can only produce even totals; match the
  // server's downward rounding so the displayed length is the requested length.
  return min + Math.floor((clamped - min) / step) * step;
}

// Keep this as the single availability contract for both the rendered chips and
// the background config refresh. Cloud models are exposed as provider flags;
// only local Wan models live in config.models.video.
export function isVideoModelAvailable(model, config = {}) {
  if (!model) return false;
  if (model === 'xai') return !!config.xaiConfigured;
  if (model === 'atlas') return !!config.atlasConfigured;
  if (model === 'gemini' || model === 'veo') return !!config.geminiConfigured;
  // A saved key (including config from an older server) cannot restore a retired API.
  if (model === 'sora') return false;
  if (model === 'seedance') return !!config.seedanceConfigured;
  if (model === 'director') {
    return !!(config.atlasConfigured || config.xaiConfigured || config.geminiConfigured);
  }
  if (MODELSLAB_VIDEO_MODELS.includes(model)) return !!config.modelslabConfigured;
  return !!(config.comfyReachable && config.models?.video?.[model]);
}

export function reconcileVideoModel(selectedModel, config = {}) {
  if (isVideoModelAvailable(selectedModel, config)) return selectedModel;

  // Preserve the established local-first fallback order, then use a configured
  // cloud provider. Director is never selected implicitly.
  const fallbacks = [
    'wan22_14b',
    'wan22_ti2v_5b',
    'wan21_1_3b',
    'wanvideo_5b',
    'xai',
    'atlas',
    'gemini',
    'veo',
    'seedance',
    'stable-diffusion-api',
  ];
  return fallbacks.find((model) => isVideoModelAvailable(model, config)) || '';
}
