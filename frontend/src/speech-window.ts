type Part = {id: string};

/** Visible paragraphs, then three following paragraphs; split fragments keep their order. */
export function speechWindow(parts: Part[], visibleIds: string[], current: number, following = 3): number[] {
  const visible = new Set(visibleIds);
  const indices = parts.flatMap((part, index) => visible.has(part.id) ? [index] : []);
  if (!indices.length && parts[current]) indices.push(current);
  const last = indices.at(-1) ?? current;
  const extraIds = new Set<string>();
  for (let index = last + 1; index < parts.length; index++) {
    const id = parts[index].id;
    if (!visible.has(id) && id !== parts[last]?.id && !extraIds.has(id)) {
      if (extraIds.size >= following) break;
      extraIds.add(id);
    }
    indices.push(index);
  }
  // The immediate continuation is useful first, then the earlier visible text.
  return [...indices.filter(index => index > current), ...indices.filter(index => index < current)];
}

export function speechCacheLimit(mode: unknown): number {
  return (mode === 'small' ? 16 : 32) * 1024 * 1024;
}
