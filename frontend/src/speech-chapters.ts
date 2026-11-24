import {splitSpeech} from './speech';
import type {SpeechPart} from './speech';

export type SpeechChapter<T> = {index: number; chapter: T; parts: SpeechPart[]};

/** One bounded, sequential scan: empty chapters never restart or loop. */
export async function nextSpeechChapter<T extends {paragraphs?: SpeechPart[]}>(
  from: number, count: number, fetchChapter: (index: number) => Promise<T>, signal: AbortSignal,
): Promise<SpeechChapter<T> | null> {
  for (let index = from + 1; index < count; index++) {
    signal.throwIfAborted();
    const chapter = await fetchChapter(index);signal.throwIfAborted();
    const parts = splitSpeech(chapter.paragraphs || []);
    if (parts.length) return {index, chapter, parts};
  }
  return null;
}

export class SpeechBookEnd extends Error {
  constructor() { super('Книга озвучена.');this.name = 'SpeechBookEnd'; }
}
