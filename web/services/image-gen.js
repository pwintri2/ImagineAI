import { startImageJob, pollJob } from './api.js';

export const ENGINES = {
  local: { id: 'local', title: 'Z-Image Turbo', subtitle: 'Local · ComfyUI', note: 'Fast local GPU render' },
  gemini: { id: 'gemini', title: 'Gemini', subtitle: 'Cloud · Google', note: 'Needs an API key' },
  xai: { id: 'xai', title: 'Grok Imagine', subtitle: 'Cloud · xAI', note: 'Needs an xAI API key' },
  atlas: { id: 'atlas', title: 'Atlas', subtitle: 'Cloud · Atlas Cloud', note: 'Needs an Atlas API key' },
  sdxl: { id: 'sdxl', title: 'ModelsLab SDXL', subtitle: 'Cloud · ModelsLab', note: 'Needs a ModelsLab key' },
};

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
