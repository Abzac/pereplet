export type SpeechParagraph = {id: string; text: string};
export type SpeechWordPosition = {id: string; offset: number; word: string};

// Match the whitespace collapsed by the Python book parser, including NBSP.
const whitespace = /[\s\u001c-\u001f\u0085]/u;
const excluded = 'a,img,svg,button,input,textarea,select,script,style,[aria-hidden="true"]';
const hitTolerance = .75;

function normalizedText(source: string): {text: string; offsets: number[]} {
 let text = '';
 const offsets: number[] = [];
 let space = -1;
 for (let index = 0; index < source.length; index++) {
  if (whitespace.test(source[index])) {
   if (text && space < 0) space = index;
   continue;
  }
  if (space >= 0) { text += ' '; offsets.push(space); space = -1; }
  text += source[index]; offsets.push(index);
 }
 return {text, offsets};
}

/** Map a DOM text character to the parser's text; offsets use UTF-16, like String.slice. */
export function speechOffsetInCanonical(rendered: string, canonical: string, offset: number): number | null {
 if (!Number.isInteger(offset) || offset < 0 || offset >= rendered.length) return null;
 const source = normalizedText(rendered);
 const target = normalizedText(canonical);
 if (source.text !== target.text) return null;
 const index = source.offsets.indexOf(offset);
 return index < 0 ? null : target.offsets[index];
}

/** Return a fresh queue beginning at the selected word, preserving punctuation and all later text. */
export function sliceSpeechFromPosition<T extends SpeechParagraph>(paragraphs: T[], id: string, offset: number): T[] {
 const index = paragraphs.findIndex(paragraph => paragraph.id === id);
 if (index < 0 || !Number.isInteger(offset) || offset < 0 || offset > paragraphs[index].text.length) return [];
 const result = paragraphs.slice(index).map(paragraph => ({...paragraph}));
 result[0].text = result[0].text.slice(offset);
 if (!result[0].text) result.shift();
 return result;
}

type CaretDocument = Document & {
 caretPositionFromPoint?: (x: number, y: number) => {offsetNode: Node; offset: number} | null;
 caretRangeFromPoint?: (x: number, y: number) => Range | null;
};
type TextSpan = {node: Text; start: number; end: number};

function caretAtPoint(document: CaretDocument, x: number, y: number): {node: Node; offset: number} | null {
 const caret = document.caretPositionFromPoint?.(x, y);
 if (caret) return {node: caret.offsetNode, offset: caret.offset};
 const range = document.caretRangeFromPoint?.(x, y);
 return range ? {node: range.startContainer, offset: range.startOffset} : null;
}

/** Only return a word whose actual laid-out text is under the pointer (never the nearest paragraph). */
export function wordHitAtPoint(root: HTMLElement, paragraphs: SpeechParagraph[], x: number, y: number): SpeechWordPosition | null {
 if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
 const document = root.ownerDocument as CaretDocument;
 const target = document.elementFromPoint(x, y);
 if (!target || !root.contains(target) || target.closest(excluded)) return null;
 const caret = caretAtPoint(document, x, y);
 if (!caret || !root.contains(caret.node)) return null;
 const caretElement = caret.node.nodeType === 1 ? caret.node as Element : caret.node.parentElement;
 if (!caretElement || caretElement.closest(excluded)) return null;

 // Inline elements may carry their own unrelated IDs; find a known paragraph ancestor.
 const byId = new Map(paragraphs.map(paragraph => [paragraph.id, paragraph]));
 let element: Element | null = caretElement;
 while (element && root.contains(element)) {
  const paragraph = byId.get(element.id);
  if (paragraph) {
   const hit = hitInParagraph(document, element, paragraph, caret, x, y);
   if (hit) return hit;
  }
  if (element === root) break;
  element = element.parentElement;
 }
 return null;
}

function hitInParagraph(document: Document, element: Element, paragraph: SpeechParagraph,
 caret: {node: Node; offset: number}, x: number, y: number): SpeechWordPosition | null {
 const spans: TextSpan[] = [];
 let rendered = '', searchable = '';
 const walker = document.createTreeWalker(element, 4 /* SHOW_TEXT */);
 let node: Node | null;
 while ((node = walker.nextNode())) {
  const text = node as Text;
  spans.push({node: text, start: rendered.length, end: rendered.length + text.data.length});
  rendered += text.data;
  // Keep anchor text in the offset map, but don't turn a footnote into part of a word.
  searchable += text.parentElement?.closest(excluded) ? ' '.repeat(text.data.length) : text.data;
 }
 if (!spans.length) return null;
 const prefix = document.createRange();
 prefix.selectNodeContents(element);
 prefix.setEnd(caret.node, caret.offset);
 const caretOffset = prefix.toString().length;
 const words = /[\p{L}\p{N}\p{M}]+(?:['’\-\u2010\u2011\u00ad][\p{L}\p{N}\p{M}]+)*/gu;
 for (const match of searchable.matchAll(words)) {
  const start = match.index!;
  const end = start + match[0].length;
  if (caretOffset < start || caretOffset > end) continue;
  const first = spans.find(span => start >= span.start && start < span.end);
  const last = spans.find(span => end > span.start && end <= span.end);
  if (!first || !last) continue;
  const range = document.createRange();
  range.setStart(first.node, start - first.start);
  range.setEnd(last.node, end - last.start);
  const containsPoint = Array.from(range.getClientRects()).some(rect => rect.width > 0 && rect.height > 0
   && x >= rect.left - hitTolerance && x <= rect.right + hitTolerance
   && y >= rect.top - hitTolerance && y <= rect.bottom + hitTolerance);
  if (!containsPoint) continue;
  const offset = speechOffsetInCanonical(rendered, paragraph.text, start);
  return offset === null ? null : {id: paragraph.id, offset, word: match[0]};
 }
 return null;
}
