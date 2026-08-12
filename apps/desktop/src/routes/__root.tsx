import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  useRouterState,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { BrandLogo, VAULT_OPENING_WORDMARK } from "@/components/BrandLogo";
import { NotificationViewport } from "@/components/product/Notifications";
import { WindowChrome } from "@/components/WindowChrome";

import appCss from "../styles.css?url";

function NotFoundComponent() {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <div className="flex min-h-full items-center justify-center bg-background px-6 py-12">
      <main className="w-full max-w-md" aria-labelledby="not-found-title">
        <BrandLogo className="h-auto w-[180px] select-none" />
        <h1
          id="not-found-title"
          ref={headingRef}
          tabIndex={-1}
          className="mt-10 text-2xl font-semibold tracking-tight text-foreground focus:outline-none"
        >
          Page not found
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This page may have moved. Return to Home to keep working.
        </p>
        <div className="mt-7">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Return home
          </Link>
        </div>
      </main>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <div className="flex min-h-full items-center justify-center bg-background px-6 py-12">
      <main className="w-full max-w-md" aria-labelledby="route-error-title">
        <BrandLogo className="h-auto w-[180px] select-none" />
        <h1
          id="route-error-title"
          ref={headingRef}
          tabIndex={-1}
          className="mt-10 text-2xl font-semibold tracking-tight text-foreground focus:outline-none"
        >
          This page did not open
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Try again. If it still does not open, return to Home.
        </p>
        <div className="mt-7 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Return home
          </a>
        </div>
      </main>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Vault" },
      { name: "description", content: "Local-first AI memory for your device" },
      { name: "author", content: "Vault" },
      { property: "og:title", content: "Vault" },
      { property: "og:description", content: "Local-first AI memory for your device" },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "twitter:site", content: "@vault" },
    ],
    links: [
      {
        rel: "icon",
        href: VAULT_OPENING_WORDMARK,
        type: "image/svg+xml",
      },
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  const pathname = useRouterState({ select: (router) => router.location.pathname });
  const [hasDesktopChrome, setHasDesktopChrome] = useState(false);

  useEffect(() => {
    void window.cmlDesktop?.notifyRendererReady?.(pathname);
  }, [pathname]);

  useEffect(() => {
    const auditChrome = import.meta.env.DEV
      && new URLSearchParams(window.location.search).get("desktopChromeAudit") === "1";
    setHasDesktopChrome(Boolean(window.cmlDesktop?.windowControls) || auditChrome);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <div className={hasDesktopChrome ? "vault-desktop-frame" : "h-screen"}>
        {hasDesktopChrome ? <WindowChrome /> : null}
        <div className={hasDesktopChrome ? "vault-desktop-content" : "h-full min-h-0"}>
          <Outlet />
        </div>
      </div>
      <NotificationViewport />
    </QueryClientProvider>
  );
}
