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

    const schedule = () => {
      if (cancelled) return;
      timer = window.setTimeout(run, document.hidden ? intervalMs * 4 : intervalMs);
    };
    const run = async () => {
      if (cancelled || document.hidden) {
        schedule();
        return;
      }
      await taskRef.current();
      schedule();
    };
    const onVisibility = () => {
      if (!document.hidden) void run();
    };

    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, intervalMs]);
}
