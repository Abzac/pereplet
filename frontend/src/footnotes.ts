export type Footnote = {anchor: string; chapter: number; title: string; html: string; text: string};

/** Old imports have no EPUB/FB2 semantics, so retain conventional note markers. */
export function isFootnoteReference(link: HTMLAnchorElement): boolean {
  if (!(link.getAttribute('href') || '').startsWith('#')) return false;
  const semantics = `${link.getAttribute('role') || ''} ${link.getAttribute('epub:type') || ''}`.split(/\s+/);
  if (semantics.some(value => value === 'doc-noteref' || value === 'noteref') || link.hasAttribute('data-note-ref')) return true;
  const label = (link.textContent || '').trim();
  return /^(?:\[\s*\d{1,5}[a-zа-я]?\s*\]|\(\s*\d{1,5}[a-zа-я]?\s*\)|\d{1,5}[a-zа-я]?|[*†‡]{1,3})$/i.test(label);
}
