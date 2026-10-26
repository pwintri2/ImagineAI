import { getState } from '../state.js';

export function kimiModelButton(kind) {
  const expanded = !!getState()[`_kimiInfo_${kind}`];
  return `<button type="button" data-kimi-info="${kind}"
    aria-expanded="${expanded}" aria-controls="kimi-${kind}-info"
    title="Kimi: geen beeld- of videogeneratie via de API"
    class="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-medium text-slate-400 hover:border-white/20 hover:text-slate-300 transition-all cursor-pointer whitespace-nowrap">☾ Kimi ⓘ</button>`;
}

export function kimiModelNote(kind) {
  const expanded = !!getState()[`_kimiInfo_${kind}`];
  return `<p id="kimi-${kind}-info" ${expanded ? '' : 'hidden'} role="status"
    class="mt-2 text-xs text-slate-300 leading-relaxed">
    Kimi kan beelden en video’s analyseren. De Kimi-API ondersteunt geen beeld- of videogeneratie.
    Kimi kan daarom niet als generator worden geselecteerd; je huidige model blijft geselecteerd.
  </p>`;
}

export function handleKimiModelClick(event, kind) {
  const button = event.target.closest(`[data-kimi-info="${kind}"]`);
  if (!button) return false;
  const expanded = button.getAttribute('aria-expanded') !== 'true';
  getState()[`_kimiInfo_${kind}`] = expanded;
  button.setAttribute('aria-expanded', String(expanded));
  document.getElementById(`kimi-${kind}-info`).hidden = !expanded;
  return true;
}
