import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Keeps a scrollable container pinned to the bottom while new content streams in, unless the
 * user scrolls up. `deps` should change whenever content changes.
 */
export function useAutoScroll(deps, resetKey) {
  const ref = useRef(null);
  const pinned = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    pinned.current = atBottom;
    setShowJump(!atBottom);
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = ref.current;
    if (!el) return;
    pinned.current = true;
    setShowJump(false);
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  }, []);

  // Jump straight to the bottom when a different conversation is opened.
  useEffect(() => {
    pinned.current = true;
    requestAnimationFrame(() => scrollToBottom(false));
  }, [resetKey, scrollToBottom]);

  useEffect(() => {
    if (pinned.current) {
      const el = ref.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ref, onScroll, showJump, scrollToBottom };
}
