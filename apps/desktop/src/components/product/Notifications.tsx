import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type NotificationTone = "info" | "success" | "error";

type NotificationInput = {
  title: string;
  description?: string;
  tone?: NotificationTone;
  actionLabel?: string;
  onAction?: () => void;
};

type NotificationRecord = NotificationInput & {
  id: number;
};

const notificationEvent = "vault:notify";
const notificationFadeAfterMs = 5000;
const notificationRemoveAfterMs = 5500;
let notificationId = 0;

export function notify(input: NotificationInput) {
  window.dispatchEvent(
    new CustomEvent<NotificationRecord>(notificationEvent, {
      detail: { ...input, id: ++notificationId },
    }),
  );
}

export function NotificationViewport() {
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [leavingIds, setLeavingIds] = useState<Set<number>>(() => new Set());
  const timersRef = useRef(
    new Map<number, { fade: number; remove: number }>(),
  );

  const dismiss = useCallback((id: number) => {
    const timers = timersRef.current.get(id);
    if (timers) {
      window.clearTimeout(timers.fade);
      window.clearTimeout(timers.remove);
      timersRef.current.delete(id);
    }
    setNotifications((current) => current.filter((item) => item.id !== id));
    setLeavingIds((current) => {
      if (!current.has(id)) return current;
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  useEffect(() => {
    const onNotification = (event: Event) => {
      const notification = (event as CustomEvent<NotificationRecord>).detail;
      setNotifications((current) => [...current.slice(-2), notification]);
      const fade = window.setTimeout(() => {
        setLeavingIds((current) => new Set(current).add(notification.id));
      }, notificationFadeAfterMs);
      const remove = window.setTimeout(
        () => dismiss(notification.id),
        notificationRemoveAfterMs,
      );
      timersRef.current.set(notification.id, { fade, remove });
    };
    window.addEventListener(notificationEvent, onNotification);
    const timers = timersRef.current;
    return () => {
      window.removeEventListener(notificationEvent, onNotification);
      for (const timer of timers.values()) {
        window.clearTimeout(timer.fade);
        window.clearTimeout(timer.remove);
      }
      timers.clear();
    };
  }, [dismiss]);

  if (notifications.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-4 bottom-5 z-[100] flex flex-col items-center gap-2"
      aria-label="Notifications"
    >
      {notifications.map((notification) => {
        const tone = notification.tone ?? "info";
        const Icon =
          tone === "error" ? AlertCircle : tone === "success" ? CheckCircle2 : Info;
        return (
          <div
            key={notification.id}
            role={tone === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-md px-4 py-3 text-sm transition-[opacity,transform] duration-500 ease-out motion-reduce:transition-none",
              leavingIds.has(notification.id) &&
                "translate-y-1 opacity-0 motion-reduce:translate-y-0",
              tone === "error" && "bg-destructive text-destructive-foreground",
              tone === "success" &&
                "bg-[var(--status-ready)] text-[var(--status-ready-foreground,#fff)]",
              tone === "info" && "bg-foreground text-background",
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="break-words font-medium">{notification.title}</div>
              {notification.description && (
                <div className="mt-0.5 text-xs leading-5 opacity-85">
                  {notification.description}
                </div>
              )}
              {notification.actionLabel && notification.onAction ? (
                <button
                  type="button"
                  className="mt-2 text-xs font-medium underline underline-offset-2"
                  onClick={() => {
                    notification.onAction?.();
                    dismiss(notification.id);
                  }}
                >
                  {notification.actionLabel}
                </button>
              ) : null}
            </div>
            <button
              type="button"
              className="-mr-1 rounded-sm p-1 opacity-70 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
              aria-label="Dismiss notification"
              onClick={() => dismiss(notification.id)}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
