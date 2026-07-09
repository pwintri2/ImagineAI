import { startVideoJob, pollJob } from './api.js';

export const VIDEO_MODELS = {
  xai: {
    id: 'xai', title: 'Grok Imagine', subtitle: 'Cloud · xAI',
    note: 'xAI text-to-video and image-to-video · up to 60s, chained + crossfaded with audio · uses your xAI quota', defaultSeconds: 5,
  },
  sdxl: {
    id: 'sdxl', title: 'Stable Diffusion Video', subtitle: 'Cloud · ModelsLab',
    note: 'Text-to-video through ModelsLab / Stable Diffusion API · uses your ModelsLab quota', defaultSeconds: 2,
  },
  'stable-diffusion-api': {
    id: 'stable-diffusion-api', title: 'Stable Diffusion Video', subtitle: 'Cloud · ModelsLab',
    note: 'Text-to-video through ModelsLab / Stable Diffusion API · uses your ModelsLab quota', defaultSeconds: 2,
  },
  'wan2.6-t2v': {
    id: 'wan2.6-t2v', title: 'wan2.6-t2v', subtitle: 'Cloud · ModelsLab',
    note: 'Text-to-video through ModelsLab with model_id wan2.6-t2v · uses your ModelsLab quota', defaultSeconds: 2,
  },
  atlas: {
    id: 'atlas', title: 'Atlas Video', subtitle: 'Cloud · Atlas Cloud',
    note: 'Wan 2.7 through Atlas Cloud · up to 60s, chained + crossfaded locally', defaultSeconds: 5,
  },
  seedance: {
    id: 'seedance', title: 'Seedance 2.0', subtitle: 'Cloud · Seedance2',
    note: 'Seedance 2.0 text-to-video · 16-30s is stitched locally', defaultSeconds: 5,
  },
  wanvideo_5b: {
    id: 'wanvideo_5b', title: 'WanVideo Long', subtitle: 'Consistent long clips',
    note: 'WanVideoWrapper · block-swap + context windows · one coherent pass up to 120s · slow but no drift', defaultSeconds: 5,
  },
  wan22_14b: {
    id: 'wan22_14b', title: 'Wan 2.2 14B', subtitle: 'Highest quality',
    note: 'Dual-model + 4-step LoRA · slower, sharper', defaultSeconds: 2,
  },
  wan22_ti2v_5b: {
    id: 'wan22_ti2v_5b', title: 'Wan 2.2 TI2V 5B', subtitle: 'Text + image',
    note: 'Hybrid text/image-to-video · lighter 5B model', defaultSeconds: 2,
  },
  wan21_1_3b: {
    id: 'wan21_1_3b', title: 'Wan 2.1 1.3B', subtitle: 'Light & quick',
    note: 'Small model · faster, lower detail', defaultSeconds: 4,
  },
};

/**
 * Generate a video. Returns { results: [{url,type}], meta, status, prompt }.
 * onProgress(job) is called on each poll tick. opts.onStart(jobId) fires once the
 * job is queued (so the caller can offer a cancel button); opts.timeoutMs caps the poll.
 */
export async function generateVideo({ prompt, model, aspect, seconds, startImage, startImages, mergeStartImages, negativePrompt, seed }, onProgress, opts = {}) {
  const images = Array.isArray(startImages) ? startImages : (startImage ? [startImage] : []);
  // Clamp to the providers' 32-bit range; larger values would lose precision in
  // the float parse and silently diverge from what the user typed.
  const parsedSeed = Math.min(Number.parseInt(seed, 10), 2147483647);
  const { jobId } = await startVideoJob({
    prompt,
    model,
    aspect,
    seconds,
    startImage: images[0]?.dataUrl || '',
    startImageName: images[0]?.name || '',
    startImages: images.map((img) => img.dataUrl),
    startImageNames: images.map((img) => img.name || ''),
    mergeStartImages: !!mergeStartImages && images.length > 1,
    // Omit when empty so the backend keeps its own defaults (random seed,
    // provider negative prompt).
    ...(negativePrompt ? { negativePrompt } : {}),
    ...(Number.isFinite(parsedSeed) && parsedSeed >= 0 ? { seed: parsedSeed } : {}),
  });
  if (opts.onStart) opts.onStart(jobId);
  const job = await pollJob(jobId, { onTick: onProgress, timeoutMs: opts.timeoutMs });
  return {
    results: job.results || [],
    meta: job.meta || {},
    status: job.status,
    modelTitle: job.meta?.modelTitle || VIDEO_MODELS[model]?.title || model,
    prompt,
  };
}
