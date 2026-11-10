/** Optional, dependency-free motion lifecycle for case-specific UI.
 * Commit business state and final DOM first; never await motion to save/unlock.
 * Keyframes and visual design belong to the actual case, not this helper.
 */
export function createBusinessMotion(root) {
  if (!root?.ownerDocument) throw new TypeError('A live UI root is required');
  const doc = root.ownerDocument, win = doc.defaultView;
  const preference = win.matchMedia('(prefers-reduced-motion: reduce)');
  const active = new Map();
  let disposed = false;
  function cancel(element) {
    const animation = active.get(element);
    active.delete(element);
    animation?.cancel();
  }
  function cancelAll() {
    for (const element of [...active.keys()]) cancel(element);
  }
  function onPreference() { if (preference.matches) cancelAll(); }
  function onVisibility() { if (doc.hidden) cancelAll(); }
  preference.addEventListener('change', onPreference);
  doc.addEventListener('visibilitychange', onVisibility);
  return {
    play(element, keyframes, options = {}) {
      cancel(element);
      if (disposed || !root.contains(element) || !element.isConnected || doc.hidden || preference.matches)
        return Promise.resolve(false);
      const duration = options.duration ?? 180;
      if (!Number.isFinite(duration) || duration < 0) throw new TypeError('Motion duration must be finite and nonnegative');
      if (!element.animate || duration === 0) return Promise.resolve(false);
      // Only a transient overlay: the already-committed DOM supplies final state.
      const animation = element.animate(keyframes, {easing:'ease-out', ...options, duration, iterations:1, fill:'none'});
      active.set(element, animation);
      return animation.finished.then(() => true, () => false).finally(() => {
        if (active.get(element) === animation) active.delete(element);
      });
    },
    cancel,
    dispose() {
      disposed = true;
      cancelAll();
      preference.removeEventListener('change', onPreference);
      doc.removeEventListener('visibilitychange', onVisibility);
    },
  };
}
