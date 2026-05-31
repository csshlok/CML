import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    if (typeof window !== "undefined") {
      const seen = window.localStorage.getItem("ctx.onboarded");
      if (!seen) throw redirect({ to: "/onboarding" });
    }
    throw redirect({ to: "/search" });
  },
});
