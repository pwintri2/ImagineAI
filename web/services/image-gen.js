import { startImageJob, pollJob } from './api.js';

export const ENGINES = {
  local: { id: 'local', title: 'Z-Image Turbo', subtitle: 'Local · ComfyUI', note: 'Fast local GPU render' },
  flux: { id: 'flux', title: 'FLUX.1 Schnell', subtitle: 'Local · ComfyUI', note: 'Q4 or FP8 · 4-step local render' },
  gemini: { id: 'gemini', title: 'Gemini Image', subtitle: 'Cloud · Google Gemini', note: 'Uses your Gemini API key' },
  xai: { id: 'xai', title: 'Grok Imagine', subtitle: 'Cloud · xAI', note: 'Needs an xAI API key' },
  atlas: { id: 'atlas', title: 'Atlas', subtitle: 'Cloud · Atlas Cloud', note: 'Needs an Atlas API key' },
  sdxl: { id: 'sdxl', title: 'ModelsLab SDXL', subtitle: 'Cloud · ModelsLab', note: 'Needs a ModelsLab key' },
  seedance: { id: 'seedance', title: 'Seedance Still', subtitle: 'Cloud · Seevio', note: 'Uses the Seevio key and return_last_frame' },
};

export function isSeedanceStillAvailable(config = {}) {
  return !!config.seevioConfigured;
}

/**
 * Generate image(s). Returns { results: [{url,type}], meta, prompt }.
 * onProgress(job) is called on each poll tick.
 */
export async function generateImage({ prompt, engine, aspect, count, steps, sourceImage }, onProgress) {
  const { jobId } = await startImageJob({
    prompt,
    engine,
    aspect,
    count,
    steps,
    sourceImage: sourceImage?.dataUrl || '',
    sourceImageName: sourceImage?.name || '',
  });
  const job = await pollJob(jobId, { onTick: onProgress });
  return {
    results: job.results || [],
    meta: job.meta || {},
    modelTitle: job.meta?.modelTitle || ENGINES[engine]?.title || engine,
    prompt,
  };
}
