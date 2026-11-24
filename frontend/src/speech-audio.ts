export type PreparedSpeech = {audio: HTMLAudioElement; url: string; bytes: number};

/** Release both the decoded media and its object URL. Safe to call more than once. */
export function releaseSpeechAudio(item: PreparedSpeech): void {
  const {audio, url} = item;
  audio.onended = null;
  audio.onerror = null;
  audio.ontimeupdate = null;
  try { audio.pause(); } catch { /* continue releasing the source */ }
  try { audio.removeAttribute('src'); } catch { /* still revoke the URL */ }
  try { audio.load(); } catch { /* a detached media element can reject load */ }
  URL.revokeObjectURL(url);
}

/** Fetch and decode before returning, so playback can start without another network wait. */
export async function prepareSpeechAudio(url: string, signal: AbortSignal): Promise<PreparedSpeech> {
  const controller = new AbortController();
  const cancelled = () => signal.reason ?? new DOMException('Озвучка остановлена', 'AbortError');
  const forwardAbort = () => controller.abort(cancelled());
  signal.addEventListener('abort', forwardAbort, {once: true});
  if (signal.aborted) forwardAbort();
  const timeoutError = new Error('Не удалось подготовить озвучку за 15 секунд');
  const timer = setTimeout(() => controller.abort(timeoutError), 15_000);
  let item: PreparedSpeech | undefined;
  let objectUrl: string | undefined;

  try {
    controller.signal.throwIfAborted();
    const response = await fetch(url, {signal: controller.signal});
    if (!response.ok) throw new Error(`Не удалось загрузить озвучку (HTTP ${response.status})`);
    const blob = await response.blob();
    controller.signal.throwIfAborted();
    objectUrl = URL.createObjectURL(blob);
    const audio = new Audio();
    // Piper returns PCM WAV: allow for the retained blob and decoded float samples.
    item = {audio, url: objectUrl, bytes: (Number(blob.size) || 0) * 3};
    audio.preload = 'auto';

    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const cleanup = () => {
        audio.removeEventListener('canplay', ready);
        audio.removeEventListener('error', failed);
        controller.signal.removeEventListener('abort', aborted);
      };
      const finish = (error?: unknown) => {
        if (settled) return;
        settled = true;
        cleanup();
        if (error === undefined) resolve(); else reject(error);
      };
      const ready = () => finish();
      const failed = () => finish(new Error('Браузер не смог прочитать аудио озвучки'));
      const aborted = () => finish(controller.signal.reason);
      audio.addEventListener('canplay', ready, {once: true});
      audio.addEventListener('error', failed, {once: true});
      controller.signal.addEventListener('abort', aborted, {once: true});
      if (controller.signal.aborted) { aborted(); return; }
      try {
        audio.src = objectUrl!;
        audio.load();
        if (audio.readyState >= 3) ready();
      } catch (error) { finish(error); }
    });
    // Abort may arrive just after canplay resolves but before this continuation.
    controller.signal.throwIfAborted();
    return item;
  } catch (error) {
    if (item) releaseSpeechAudio(item);
    else if (objectUrl) URL.revokeObjectURL(objectUrl);
    throw controller.signal.aborted ? controller.signal.reason : error;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', forwardAbort);
  }
}
