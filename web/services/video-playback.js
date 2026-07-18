export function videoPlaybackCandidates(video, edition = '') {
  const previewUrl = typeof video?.url === 'string' ? video.url : '';
  const mp4Url = typeof video?.mp4Url === 'string' ? video.mp4Url : '';
  const prefersMp4 = String(edition).toLowerCase() === 'macos';
  const ordered = prefersMp4 ? [mp4Url, previewUrl] : [previewUrl, mp4Url];
  return ordered.filter((url, index) => url && ordered.indexOf(url) === index);
}

export function editionFromSearch(search = '') {
  try {
    return new URLSearchParams(search).get('edition') || '';
  } catch {
    return '';
  }
}

export function videoMediaType(url) {
  let candidate = '';
  try {
    const parsed = new URL(url, 'http://localhost');
    candidate = parsed.searchParams.get('name') || parsed.searchParams.get('filename') || parsed.pathname;
  } catch {
    candidate = String(url || '');
  }
  const ext = String(candidate).match(/\.([a-z0-9]{2,5})$/i)?.[1]?.toLowerCase();
  if (ext === 'webm') return 'video/webm';
  if (ext === 'mp4') return 'video/mp4';
  if (ext === 'mov') return 'video/quicktime';
  return '';
}
