import { useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, LoaderCircle, LockKeyhole, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export function StatusLabel({
  tone = "neutral",
  children,
}: {
  tone?: "ready" | "warning" | "error" | "info" | "neutral";
  children: ReactNode;
}) {
  const dot = {
    ready: "bg-[var(--status-ready)]",
    warning: "bg-[var(--status-warn)]",
    error: "bg-[var(--status-error)]",
    info: "bg-[var(--status-info)]",
    neutral: "bg-[var(--status-muted)]",
  }[tone];
  return (
    <span className="inline-flex min-h-6 items-center gap-1.5 rounded-full bg-[var(--status-muted-bg)] px-2 text-xs text-[var(--text-body)]">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {children}
    </span>
  );
}

export function SkeletonRegion({ lines = 4, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`animate-pulse space-y-3 ${className}`} aria-label="Loading" role="status">
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="h-3 rounded bg-[var(--bg-secondary)]"
          style={{ width: `${Math.max(42, 100 - index * 13)}%` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-5 py-12 text-center">
      {icon ? <div className="mb-4 text-[var(--text-muted)]">{icon}</div> : null}
      <h2 className="text-base font-semibold text-[var(--text-primary)]">{title}</h2>
      <p className="mt-2 max-w-[52ch] text-sm leading-6 text-[var(--text-muted)]">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function DegradedState({
  title = "Vault is temporarily unavailable",
  description = "Your local library service is not responding. Your data is still on this device.",
  onRetry,
  action,
  compact = false,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={`rounded-md border border-[var(--border-default)] bg-[var(--status-warn-bg)] ${compact ? "p-3" : "p-5"}`}
      role="status"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-warn-ink)]" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-[var(--text-primary)]">{title}</div>
          <p className="mt-1 text-sm leading-5 text-[var(--text-body)]">{description}</p>
          {onRetry || action ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {onRetry ? (
                <Button size="sm" variant="outline" onClick={onRetry}>
                  <RefreshCw className="h-3.5 w-3.5" /> Try again
                </Button>
              ) : null}
              {action}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ConfirmAction({
  children,
  title,
  description,
  confirmLabel,
  onConfirm,
  destructive = true,
  disabled = false,
}: {
  children: ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void | Promise<void>;
  destructive?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setPending(true);
    setError("");
    try {
      await onConfirm();
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The action could not be completed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (pending) return;
        setOpen(nextOpen);
        if (!nextOpen) setError("");
      }}
    >
      <AlertDialogTrigger asChild disabled={disabled}>
        {children}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {error ? <p className="mr-auto text-sm text-destructive" role="alert">{error}</p> : null}
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={destructive ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : ""}
            disabled={pending}
            onClick={(event) => {
              event.preventDefault();
              void confirm();
            }}
          >
            {pending ? <><LoaderCircle className="h-4 w-4 animate-spin" /> Working…</> : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function AsyncActionLabel({
  busy,
  done,
  idle,
}: {
  busy: boolean;
  done?: boolean;
  idle: ReactNode;
}) {
  if (busy) return <><LoaderCircle className="h-4 w-4 animate-spin" /> Working…</>;
  if (done) return <><CheckCircle2 className="h-4 w-4" /> Done</>;
  return <>{idle}</>;
}

export function LockedState({
  onUnlock,
  onOpenRecovery,
}: {
  onUnlock: (passphrase: string) => Promise<void>;
  onOpenRecovery: () => void;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!passphrase || pending) return;
    setPending(true);
    setError("");
    try {
      await onUnlock(passphrase);
      setPassphrase("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That passphrase did not unlock this library.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center px-5 py-10">
      <section className="w-full max-w-sm" aria-labelledby="locked-library-title">
        <LockKeyhole className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <h2 id="locked-library-title" className="mt-4 text-xl font-semibold">Library locked</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Enter your passphrase to continue.
        </p>
        <form
          className="mt-6"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label htmlFor="vault-inline-passphrase" className="text-sm font-medium">Passphrase</label>
          <input
            id="vault-inline-passphrase"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={passphrase}
            disabled={pending}
            onChange={(event) => {
              setPassphrase(event.target.value);
              if (error) setError("");
            }}
            className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          />
          {error ? <p className="mt-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!passphrase || pending}>
              {pending ? <><LoaderCircle className="h-4 w-4 animate-spin" /> Unlocking...</> : "Unlock"}
            </Button>
            <Button type="button" variant="ghost" onClick={onOpenRecovery}>
              Reset or recover
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function AppStatusAnnouncer({ message }: { message: string | null | undefined }) {
  return (
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {message ?? ""}
    </div>
  );
}
