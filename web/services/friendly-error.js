const OUT_OF_MEMORY_RE = /out of memory|exceed allowed memory|allocation on device|cuda out of memory/i;

function truncate(message, maxLength = 240) {
  return message.length > maxLength ? `${message.slice(0, maxLength)}…` : message;
}

export function friendlyError(err, { kind = 'generation', usesLocalGpu = false, providerLabel = '' } = {}) {
  const message = err?.message || String(err);

  if (OUT_OF_MEMORY_RE.test(message)) {
    if (usesLocalGpu) {
      return 'The GPU ran out of memory. Free VRAM first (unload other ComfyUI models or stop Ollama/LLM models), pick a smaller ratio, or switch to the lighter Wan 2.2 TI2V 5B, then try again.';
    }
    if (providerLabel) {
      return `${providerLabel} reported a cloud-side memory or capacity failure. This did not use your computer's GPU. Try again; if it keeps happening, reduce the request or retry later.`;
    }
    return truncate(message);
  }

  if (/timed out/i.test(message)) {
    if (kind === 'video') return 'Video generation timed out. Try a shorter video or another model.';
    if (kind === 'image') return 'Image generation timed out. Try again, request fewer images, or use another engine.';
    return 'Generation timed out. Try again with a smaller request.';
  }
  if (usesLocalGpu && /not reachable|offline|ComfyUI is not/i.test(message)) {
    return 'ComfyUI is not reachable. Start it or check the URL in Settings.';
  }
  return truncate(message);
}
