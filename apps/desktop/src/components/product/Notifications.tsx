import { useEffect, useState } from "react";
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

  useEffect(() => {
    const onNotification = (event: Event) => {
      const notification = (event as CustomEvent<NotificationRecord>).detail;
      setNotifications((current) => [...current.slice(-2), notification]);
      window.setTimeout(() => {
        setNotifications((current) => current.filter((item) => item.id !== notification.id));
      }, 5500);
    };
    window.addEventListener(notificationEvent, onNotification);
    return () => window.removeEventListener(notificationEvent, onNotification);
  }, []);

  if (notifications.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-[min(24rem,calc(100vw-2.5rem))] flex-col gap-2"
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
              "pointer-events-auto flex items-start gap-3 rounded-md px-4 py-3 text-sm",
              tone === "error" && "bg-destructive text-destructive-foreground",
              tone === "success" &&
                "bg-[var(--status-ready)] text-[var(--status-ready-foreground,#fff)]",
              tone === "info" && "bg-foreground text-background",
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{notification.title}</div>
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
                    setNotifications((current) =>
                      current.filter((item) => item.id !== notification.id),
                    );
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
              onClick={() =>
                setNotifications((current) =>
                  current.filter((item) => item.id !== notification.id),
                )
              }
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
