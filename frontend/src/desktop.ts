export const desktop = !!(window as any).__TAURI__;
type SaveHook = () => Promise<unknown>;
const hooks = new Set<SaveHook>();
export function onDesktopClose(hook: SaveHook) {
  if (desktop) hooks.add(hook);
  return () => { hooks.delete(hook); };
}
export async function flushDesktopState() {
  // Finish all writers while the local server is still alive.
  const results = await Promise.all([...hooks].map(hook => hook()));
  if (results.some(result => result === false)) throw new Error('Не удалось сохранить место чтения. Повторите закрытие.');
}
export const native = () => (window as any).__TAURI__;
