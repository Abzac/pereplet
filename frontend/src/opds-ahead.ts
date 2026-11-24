import type {OpdsCache} from './opds-cache';
import {OpdsPages} from './opds-paging';

/** Prepares only the actual next two feeds. Visible pages/history stay untouched. */
export class OpdsAhead {
 private scope: string | null = null;
 private visible: OpdsPages | null = null;
 private controller: AbortController | null = null;
 private generation = 0;
 private revision = 0;
 private running = false;
 private closed = false;

 constructor(private readonly cache: Pick<OpdsCache, 'prepare'>) {}

 /** scope must capture catalog, initial request URL and search query. */
 warm(scope: string, pages: OpdsPages): void {
  if (this.closed) return;
  if (scope !== this.scope) {
   this.clear();
   this.scope = scope;
  }
  if (!pages.canAutoAppend) {this.clear();return;}
  // Never append to the caller's section just because a response arrived.
  this.visible = OpdsPages.restore(pages.snapshot());
  this.revision++;
  if (this.running) return;
  this.controller ||= new AbortController();
  this.running = true;
  void this.run(this.generation, this.controller.signal);
 }

 clear(): void {
  this.generation++;
  this.controller?.abort();
  this.controller = null;
  this.visible = null;
  this.scope = null;
  this.running = false;
 }

 dispose(): void {this.closed = true;this.clear();}

 private async run(generation: number, signal: AbortSignal): Promise<void> {
  try {
   while (!signal.aborted && generation === this.generation && this.visible) {
    const revision = this.revision, shadow = OpdsPages.restore(this.visible.snapshot());
    for (let depth = 0; depth < 2 && shadow.canAutoAppend; depth++) {
     const next = shadow.feed.next!;
     // Pagination URLs already contain the provider's query. Never inspect
     // category/navigation/acquisition links or invent a next page number.
     const feed = await this.cache.prepare(next, '', signal);
     if (signal.aborted || generation !== this.generation) return;
     if (revision !== this.revision) break;
     if (!shadow.append(next, feed)) return;
    }
    // If the user appended a prepared page during this request, replenish from
    // the new visible tail without aborting an already useful pending fetch.
    if (revision === this.revision) return;
   }
  } catch {
   // Speculation is optional. Foreground get() can retry a failed request;
   // neither errors nor malformed pagination start a background retry loop.
  } finally {
   if (generation === this.generation) this.running = false;
  }
 }
}
