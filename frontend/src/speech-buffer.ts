/** A bounded, sequential preparation queue. Playback itself does not occupy the loader. */
type Entry<T> = {
  index: number;
  generation: number;
  order: number;
  foreground: boolean;
  state: 'queued' | 'loading' | 'ready' | 'error' | 'evicted';
  cancelled: boolean;
  value?: T;
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
};

export class SpeechBufferCancelled extends Error {
  constructor() {
    super('Speech preparation was cancelled');
    this.name = 'AbortError';
  }
}

export class SpeechBuffer<T> {
  private readonly entries = new Map<number, Entry<T>>();
  private readonly maxItems: number;
  private active: Entry<T> | null = null;
  private generation = 0;
  private order = 0;
  private closed = false;
  private readonly maxWeight: number;
  private readonly weight: (value: T) => number;
  private budgetFull = false;
  private windowKey = '';

  constructor(
    private readonly loader: (index: number) => Promise<T>,
    private readonly release: (value: T) => void,
    options: {maxItems?: number; maxWeight?: number; weight?: (value: T) => number} = {},
  ) {
    this.maxItems = options.maxItems ?? 6;
    this.maxWeight = options.maxWeight ?? Infinity;
    this.weight = options.weight ?? (() => 0);
    if (!Number.isInteger(this.maxItems) || this.maxItems < 1) {
      throw new RangeError('maxItems must be a positive integer');
    }
  }

  /** Includes ready values, remembered errors, and queued/in-flight requests. */
  get size(): number { return this.entries.size; }
  get retainedWeight(): number {
    return [...this.entries.values()].reduce((sum, entry) => sum + (entry.state === 'ready' ? this.valueWeight(entry.value as T) : 0), 0);
  }

  get pendingCount(): number {
    return [...this.entries.values()].filter(entry => entry.state === 'queued' || entry.state === 'loading').length;
  }

  /** Transfer a prepared fragment between chapter buffers without decoding it again. */
  take(index: number): T | undefined {
    const entry = this.entries.get(index);
    if (entry?.state !== 'ready') return undefined;
    this.entries.delete(index);entry.cancelled = true;
    const value = entry.value;entry.value = undefined;
    return value;
  }

  seed(index: number, value: T): void {
    this.checkIndex(index);
    if (this.closed) { this.safeRelease(value); return; }
    const old = this.entries.get(index);if (old) this.remove(old);
    if (!this.makeRoom(index, true)) { this.safeRelease(value); return; }
    const entry = this.create(index, true);entry.state = 'ready';entry.value = value;entry.resolve(value);
    this.trimWeight();
  }

  /** Reuses the same promise, including an already-running prefetch. */
  ensure(index: number): Promise<T> {
    this.checkIndex(index);
    if (this.closed) return this.rejected(new SpeechBufferCancelled());
    let entry = this.entries.get(index);
    if (entry?.state === 'evicted') { this.remove(entry); entry = undefined; }
    if (!entry) {
      if (!this.makeRoom(index, true)) {
        return this.rejected(new RangeError('Speech buffer is full; release previous items with retainFrom()'));
      }
      entry = this.create(index, true);
    } else if (!entry.foreground) {
      entry.foreground = true;
      entry.order = this.order++;
    }
    this.pump();
    return entry.promise;
  }

  /** Best effort: nearer paragraphs take precedence over farther background items. */
  prefetch(start: number, endExclusive: number): void {
    this.checkIndex(start);
    this.checkIndex(endExclusive);
    if (this.closed) return;
    // A larger requested range must not allocate an unbounded queue.
    const end = Math.min(endExclusive, start + this.maxItems);
    for (let index = start; index < end; index++) {
      if (this.entries.has(index)) continue;
      if (!this.makeRoom(index, false)) break;
      this.create(index, false);
    }
    this.pump();
  }

  /** Reprioritize one visible window without discarding already prepared neighbours. */
  setWindow(current: number, upcoming: number[], previous: number[] = []): void {
    this.checkIndex(current);
    if (this.closed) return;
    const wanted = [...new Set([current, ...upcoming])].slice(0, this.maxItems);
    wanted.forEach(index => this.checkIndex(index));
    const retained = [...new Set([...wanted, ...previous])].slice(0, this.maxItems);
    const key = JSON.stringify([current, wanted, retained]);
    if (key !== this.windowKey) { this.windowKey = key; this.budgetFull = false; }
    const ranks = new Map(retained.map((index, rank) => [index, rank]));
    for (const entry of this.entries.values()) {
      if (!ranks.has(entry.index) || (!wanted.includes(entry.index) && entry.state === 'queued')) this.remove(entry);
      else { entry.foreground = entry.index === current; entry.order = ranks.get(entry.index)!; }
    }
    for (const index of wanted) {
      if (!this.entries.has(index)) this.create(index, index === current).order = ranks.get(index)!;
    }
    this.trimWeight();
    this.pump();
  }

  /** Call when playback advances. The current paragraph remains available. */
  retainFrom(index: number): void {
    this.checkIndex(index);
    for (const entry of this.entries.values()) {
      if (entry.index < index) this.remove(entry);
    }
    this.pump();
  }

  /** Invalidates pending work; late values are released instead of being cached. */
  clear(): void {
    this.generation++;
    for (const entry of this.entries.values()) this.remove(entry);
    this.windowKey = ''; this.budgetFull = false;
    // Do not reset active: even an obsolete loader must finish before another starts.
  }

  dispose(): void {
    this.closed = true;
    this.clear();
  }

  private checkIndex(index: number): void {
    if (!Number.isSafeInteger(index) || index < 0) throw new RangeError('Paragraph index must be a nonnegative integer');
  }

  private rejected(error: unknown): Promise<T> {
    const promise = Promise.reject<T>(error);
    void promise.catch(() => {});
    return promise;
  }

  private create(index: number, foreground: boolean): Entry<T> {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    // Prefetch may fail long before ensure() reaches it. Keep that error for ensure,
    // while making the background promise handled immediately.
    void promise.catch(() => {});
    const entry: Entry<T> = {
      index, generation: this.generation, order: this.order++, foreground,
      state: 'queued', cancelled: false, promise, resolve, reject,
    };
    this.entries.set(index, entry);
    return entry;
  }

  private makeRoom(index: number, foreground: boolean): boolean {
    if (this.entries.size < this.maxItems) return true;
    const candidates = [...this.entries.values()]
      .filter(entry => !entry.foreground && entry.state !== 'loading')
      .sort((a, b) => b.index - a.index);
    const victim = candidates[0];
    if (!victim || (!foreground && victim.index <= index)) return false;
    this.remove(victim);
    return true;
  }

  private remove(entry: Entry<T>): void {
    this.entries.delete(entry.index);
    entry.cancelled = true;
    if (entry.state === 'ready') this.safeRelease(entry.value as T);
    entry.value = undefined;
    entry.reject(new SpeechBufferCancelled());
  }

  private safeRelease(value: T): void {
    // Cleanup must not prevent the next item or leave the queue permanently busy.
    try { this.release(value); } catch { /* best effort cleanup */ }
  }

  private valueWeight(value: T): number {
    const size = this.weight(value);
    return Number.isFinite(size) && size > 0 ? size : 0;
  }

  private trimWeight(): void {
    for (const entry of [...this.entries.values()].filter(entry => entry.state === 'ready' && !entry.foreground).sort((a, b) => b.order - a.order)) {
      if (this.retainedWeight <= this.maxWeight) break;
      this.budgetFull = true;
      this.safeRelease(entry.value as T); entry.value = undefined; entry.state = 'evicted';
      // A placeholder prevents repeatedly synthesizing the same over-budget prefetch.
    }
    if (this.retainedWeight > this.maxWeight) this.budgetFull = true;
  }

  private pump(): void {
    if (this.active || this.closed) return;
    const next = [...this.entries.values()]
      .filter(entry => entry.state === 'queued' && (entry.foreground || !this.budgetFull))
      .sort((a, b) => Number(b.foreground) - Number(a.foreground)
        || a.order - b.order)[0];
    if (!next) return;
    this.active = next;
    next.state = 'loading';
    void this.run(next);
  }

  private async run(entry: Entry<T>): Promise<void> {
    try {
      const value = await this.loader(entry.index);
      if (entry.cancelled || entry.generation !== this.generation || this.entries.get(entry.index) !== entry) {
        this.safeRelease(value);
      } else {
        entry.value = value;
        entry.state = 'ready';
        entry.resolve(value);
        this.trimWeight();
      }
    } catch (error) {
      if (!entry.cancelled && entry.generation === this.generation) {
        entry.state = 'error';
        entry.reject(error);
      }
    } finally {
      this.active = null;
      this.pump();
    }
  }
}
