import { useLayoutEffect, useRef, type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function PageSurface({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("vault-page-surface", className)} {...props} />;
}

export function PageHeader({
  className,
  ...props
}: HTMLAttributes<HTMLElement>) {
  const ref = useWindowControlExclusion<HTMLElement>();
  return <header ref={ref} className={cn("vault-window-aware", className)} {...props} />;
}

export function WindowAwareToolbar({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  const ref = useWindowControlExclusion<HTMLDivElement>();
  return (
    <div
      ref={ref}
      className={cn("vault-window-aware", className)}
      role="toolbar"
      {...props}
    />
  );
}

function useWindowControlExclusion<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useLayoutEffect(() => {
    const container = ref.current;
    if (!container) return;
    let frame = 0;
    const shifted = new Set<HTMLElement>();

    const measure = () => {
      frame = 0;
      const safeZone = document.querySelector<HTMLElement>("[data-window-control-safe-zone]");
      if (!safeZone) {
        for (const child of shifted) child.style.removeProperty("--vault-window-collision-inset");
        shifted.clear();
        return;
      }
      const safe = safeZone.getBoundingClientRect();
      const nextShifted = new Set<HTMLElement>();
      for (const value of Array.from(container.children)) {
        if (!(value instanceof HTMLElement)) continue;
        const currentInset = Number.parseFloat(
          value.style.getPropertyValue("--vault-window-collision-inset") || "0",
        );
        const rect = value.getBoundingClientRect();
        const baseline = {
          left: rect.left + currentInset,
          right: rect.right + currentInset,
        };
        const intersectsVertically = rect.top < safe.bottom && rect.bottom > safe.top;
        const intersectsHorizontally = baseline.right > safe.left && baseline.left < safe.right;
        const inset =
          intersectsVertically && intersectsHorizontally
            ? Math.max(0, Math.ceil(baseline.right - safe.left + 12))
            : 0;
        if (inset > 0) {
          value.style.setProperty("--vault-window-collision-inset", `${inset}px`);
          nextShifted.add(value);
        } else {
          value.style.removeProperty("--vault-window-collision-inset");
        }
      }
      for (const child of shifted) {
        if (!nextShifted.has(child)) child.style.removeProperty("--vault-window-collision-inset");
      }
      shifted.clear();
      for (const child of nextShifted) shifted.add(child);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    const resizeObserver =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    resizeObserver?.observe(container);
    const mutationObserver = new MutationObserver(schedule);
    mutationObserver.observe(container, { childList: true, subtree: true });
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      window.removeEventListener("resize", schedule);
      mutationObserver.disconnect();
      resizeObserver?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      for (const child of shifted) child.style.removeProperty("--vault-window-collision-inset");
    };
  }, []);

  return ref;
}
