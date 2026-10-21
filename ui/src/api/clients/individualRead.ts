/** Share only concurrent reads of the same resource within one client generation.
 * Each caller still validates the actual response; errors are never suppressed.
 */
export function individualRead<T>(
  generation: () => number,
  read: (path: string) => Promise<T>,
) {
  const pending = new Map<string, Promise<T>>();
  return (path: string): Promise<T> => {
    const current = generation(),
      key = `${current}:${path}`;
    const existing = pending.get(key);
    if (existing) return existing;
    const promise = (async () => {
      const value = await read(path);
      if (generation() !== current)
        throw new Error("The individual run read is stale.");
      return value;
    })();
    pending.set(key, promise);
    void promise.then(
      () => {
        if (pending.get(key) === promise) pending.delete(key);
      },
      () => {
        if (pending.get(key) === promise) pending.delete(key);
      },
    );
    return promise;
  };
}
