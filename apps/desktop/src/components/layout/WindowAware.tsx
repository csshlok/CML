import type { HTMLAttributes } from "react";

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
  return <header className={cn("vault-window-aware", className)} {...props} />;
}

export function WindowAwareToolbar({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("vault-window-aware", className)}
      role="toolbar"
      {...props}
    />
  );
}
