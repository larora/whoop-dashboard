/* Inline SVG icons (24x24 stroke paths, currentColor). icon(name, size) returns an <svg> string. */
const ICONS = {
  run: '<circle cx="15" cy="4" r="2"/><path d="M13.5 8.5 10 12l3 3-2 6"/><path d="M10 12 7 10l-3 3"/><path d="m13 15 3 2 2 4"/><path d="M13.5 8.5 17 10l3-1"/>',
  dumbbell: '<path d="M6.5 6.5v11M17.5 6.5v11"/><path d="M3 9v6M21 9v6"/><path d="M6.5 12h11"/><path d="M4.5 8.5v7M19.5 8.5v7"/>',
  moon: '<path d="M21 13.5A8.5 8.5 0 0 1 10.5 3 7 7 0 1 0 21 13.5z"/>',
  flame: '<path d="M12 3s5 4.5 5 9.5a5 5 0 0 1-10 0c0-2 1-3.5 1-3.5s1 1.5 2.5 1.5C11 8 12 3 12 3z"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  lungs: '<path d="M12 4v8"/><path d="M12 12c-1 3-3 5-6 6-2 .6-3-1-3-3 0-4 2-8 5-8 2 0 3 2 4 5z"/><path d="M12 12c1 3 3 5 6 6 2 .6 3-1 3-3 0-4-2-8-5-8-2 0-3 2-4 5z"/>',
  timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  bed: '<path d="M3 18V8"/><path d="M3 14h18v4"/><path d="M3 10h6a3 3 0 0 1 3 3v1"/><path d="M12 14h6a3 3 0 0 1 3 3"/>',
  sparkle: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
};
const icon = (name, size = 18, cls = "") =>
  `<svg class="ico ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
