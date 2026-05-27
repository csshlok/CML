import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    // mock store starts without vault — but redirect to onboarding once,
    // otherwise straight to chat
    if (typeof window !== "undefined") {
      const seen = window.localStorage.getItem("ctx.onboarded");
      if (!seen) throw redirect({ to: "/onboarding" });
    }
    throw redirect({ to: "/chat" });
  },
});
