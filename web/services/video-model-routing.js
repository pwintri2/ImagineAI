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

export function isLocalVideoModel(model) {
  return LOCAL_VIDEO_MODELS.includes(model);
}

// Keep this as the single availability contract for both the rendered chips and
// the background config refresh. Cloud models are exposed as provider flags;
// only local Wan models live in config.models.video.
export function isVideoModelAvailable(model, config = {}) {
  if (!model) return false;
  if (model === 'xai') return !!config.xaiConfigured;
  if (model === 'atlas') return !!config.atlasConfigured;
  if (model === 'gemini' || model === 'veo') return !!config.geminiConfigured;
  if (model === 'sora') return !!config.soraConfigured;
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
    'sora',
    'seedance',
    'stable-diffusion-api',
  ];
  return fallbacks.find((model) => isVideoModelAvailable(model, config)) || '';
}
