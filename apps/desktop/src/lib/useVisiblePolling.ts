import { useEffect, useRef } from "react";

export function useVisiblePolling(
  task: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
) {
  const taskRef = useRef(task);
  taskRef.current = task;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: number | null = null;
    let running = false;
    let rerunRequested = false;

    const schedule = () => {
      if (cancelled) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(run, document.hidden ? intervalMs * 4 : intervalMs);
    };
    const run = async () => {
      if (running) {
        rerunRequested = true;
        return;
      }
      if (cancelled || document.hidden) {
        schedule();
        return;
      }
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
      running = true;
      try {
        await taskRef.current();
      } finally {
        running = false;
        if (rerunRequested) {
          rerunRequested = false;
          void run();
        } else {
          schedule();
        }
      }
    };
    const onVisibility = () => {
      if (!document.hidden) void run();
    };
    const onFocus = () => {
      if (!document.hidden) void run();
    };

    void run();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled, intervalMs]);
}
