import type {Book} from './types';

export const CONTINUE_CARD_WIDTH = 270;
export const CONTINUE_CARD_GAP = 16;

export function continueCapacity(width: number): number {
  return Math.max(1, Math.floor((Math.max(0, width) + CONTINUE_CARD_GAP) / (CONTINUE_CARD_WIDTH + CONTINUE_CARD_GAP)));
}

/** This row is the reading queue, not a history of every opened or planned book. */
export function continueReading<T extends Pick<Book, 'status' | 'progress' | 'last_opened'>>(books: T[]): T[] {
  const opened = (book: T) => Date.parse(book.last_opened || '') || 0;
  // Position 100% may be a jump to the end, and is not evidence of completion.
  return books.filter(book => book.status === 'reading')
    .sort((a, b) => opened(b) - opened(a));
}
