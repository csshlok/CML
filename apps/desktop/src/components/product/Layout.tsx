import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function ProductSection({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn("overflow-hidden rounded-md border border-border bg-card", className)}
      {...props}
    >
      {children}
    </section>
  );
}

export function ProductSectionHeader({
  title,
  description,
  action,
  meta,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex min-h-16 flex-col gap-3 border-b border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 className="break-words text-base font-semibold">{title}</h2>
          {meta}
        </div>
        {description ? (
          <p className="mt-1 max-w-[70ch] text-sm leading-5 text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

export function ProductSectionStack({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("space-y-8", className)} {...props}>
      {children}
    </div>
  );
}
