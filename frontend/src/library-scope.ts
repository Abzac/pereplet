import type {Book} from './types';

export type MediaType = 'book' | 'comic';
type ClassifiedBook = Pick<Book, 'format' | 'media_type' | 'archived'>;
export interface SeriesGroup {key: string; name: string; count: number}

/** The explicit choice wins, including PDF comics and archives classified as books. */
export function mediaType(book: ClassifiedBook): MediaType {
  if (book.media_type === 'book' || book.media_type === 'comic') return book.media_type;
  return /^(cbz|cbr)$/i.test(book.format || '') ? 'comic' : 'book';
}

export function booksForView<T extends ClassifiedBook>(books: T[], view: string): T[] {
  if (view === 'archive') return books.filter(book => book.archived === true);
  const visible = books.some(book => book.archived === true) ? books.filter(book => book.archived !== true) : books;
  if (['reading', 'planned', 'read'].includes(view)) return visible;
  const wanted: MediaType = ['comics', 'comic-series'].includes(view) ? 'comic' : 'book';
  return visible.filter(book => mediaType(book) === wanted);
}

export function buildSeriesDirectory(books: Pick<Book, 'series'>[]): SeriesGroup[] {
  const counts = new Map<string, number>();
  let ungrouped = 0;
  for (const book of books) {
    if (book.series) counts.set(book.series, (counts.get(book.series) || 0) + 1);
    else ungrouped++;
  }
  return [...counts].sort(([a], [b]) => a.localeCompare(b, 'ru', {numeric: true}))
    .map(([name, count]) => ({key: name, name, count}))
    .concat(ungrouped ? [{key: '__no_series__', name: 'Без серии', count: ungrouped}] : []);
}
