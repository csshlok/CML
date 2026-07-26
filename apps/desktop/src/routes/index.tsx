import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: async () => {
    if (typeof window === "undefined") throw redirect({ to: "/onboarding" });
    const state = await window.cmlDesktop?.getSetupState?.();
    if (state?.phase !== "complete") throw redirect({ to: "/onboarding" });
    throw redirect({ to: "/home" });
  },
});
