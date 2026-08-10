import { useEffect, useRef } from "react";

export function useVisiblePolling(
  task: (signal?: AbortSignal) => void | Promise<void>,
  intervalMs: number,
  enabled = true,
  onError?: (error: unknown) => void,
  restartKey?: unknown,
) {
  const taskRef = useRef(task);
  const errorRef = useRef(onError);
  taskRef.current = task;
  errorRef.current = onError;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: number | null = null;
    let running = false;
    let rerunRequested = false;
    let consecutiveFailures = 0;
    let controller: AbortController | null = null;

    const schedule = () => {
      if (cancelled) return;
      if (timer !== null) window.clearTimeout(timer);
      const backoff = Math.min(8, 2 ** consecutiveFailures);
      timer = window.setTimeout(run, (document.hidden ? intervalMs * 4 : intervalMs) * backoff);
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
      controller = new AbortController();
      try {
        await taskRef.current(controller.signal);
        consecutiveFailures = 0;
      } catch (error) {
        consecutiveFailures += 1;
        errorRef.current?.(error);
        window.dispatchEvent(new CustomEvent("vault:poll-error", { detail: { error } }));
      } finally {
        controller = null;
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
      controller?.abort();
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled, intervalMs, restartKey]);
}
