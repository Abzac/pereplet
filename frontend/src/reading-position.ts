type Section = {length?: number};

function weights(sections: Section[], count: number): number[] {
 return Array.from({length: Math.max(1, sections.length || count || 1)}, (_, index) => {
  const size = Number(sections[index]?.length);
  return Number.isFinite(size) && size > 0 ? size : 1;
 });
}

/** Approximate position from chapter text lengths; no whole-book layout is required. */
export function positionInBook(sections: Section[], count: number, chapter: number, ratio: number): number {
 const sizes = weights(sections, count), index = Math.max(0, Math.min(sizes.length - 1, chapter));
 const total = sizes.reduce((sum, size) => sum + size, 0);
 return (sizes.slice(0, index).reduce((sum, size) => sum + size, 0) + sizes[index] * Math.max(0, Math.min(1, ratio || 0))) / total;
}

export function locateInBook(sections: Section[], count: number, fraction: number): {chapter: number; ratio: number; end: boolean} {
 const sizes = weights(sections, count), part = Math.max(0, Math.min(1, Number(fraction) || 0));
 if (part === 1) return {chapter: sizes.length - 1, ratio: 1, end: true};
 let offset = part * sizes.reduce((sum, size) => sum + size, 0);
 for (let chapter = 0; chapter < sizes.length; chapter++) {
  if (offset < sizes[chapter]) return {chapter, ratio: offset / sizes[chapter], end: false};
  offset -= sizes[chapter];
 }
 return {chapter: sizes.length - 1, ratio: 1, end: true};
}
