// Small inline line-icons (stroke=currentColor) replacing the emoji that
// were reported as looking childish. Kept as plain SVG strings - no icon
// library needed for a handful of glyphs.
const wrap = (paths: string) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const iconVideo = wrap(
  `<rect x="2.5" y="5.5" width="13" height="13" rx="2"/><path d="M15.5 10.2l5-3v9.6l-5-3z"/>`
);

export const iconDrive = wrap(
  `<path d="M12 3l9 15H3z"/><path d="M8.2 13.5h7.6"/>`
);

export const iconTemplate = wrap(
  `<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/>`
);

export const iconNodes = wrap(
  `<circle cx="5" cy="6" r="2.3"/><circle cx="5" cy="18" r="2.3"/><circle cx="18" cy="12" r="2.3"/><path d="M7.2 7l8.7 4"/><path d="M7.2 17l8.7-4"/>`
);

export const iconFolder = wrap(
  `<path d="M3 6.5a1.5 1.5 0 0 1 1.5-1.5h4.6l1.8 2H19.5A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z"/>`
);

export const iconFilm = wrap(
  `<rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="M2.5 8.5h19M2.5 15.5h19M8 4.5v15M16 4.5v15"/>`
);

export const iconClose = wrap(`<path d="M5 5l14 14M19 5L5 19"/>`);
export const iconUndo = wrap(`<path d="M7 8L3 12l4 4"/><path d="M3 12h11a6 6 0 0 1 0 12h-2"/>`);
export const iconReset = wrap(`<path d="M4 12a8 8 0 1 1 2.5 5.8"/><path d="M4 17v-5h5"/>`);
export const iconPlay = wrap(`<path d="M6 4.5v15l13-7.5z"/>`);
export const iconPause = wrap(`<rect x="5" y="4" width="5" height="16" rx="1"/><rect x="14" y="4" width="5" height="16" rx="1"/>`);
