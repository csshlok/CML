import { createFileRoute } from "@tanstack/react-router";
import { TimelineRoute } from "./_app.timeline";

export const Route = createFileRoute("/_app/activity")({
  component: TimelineRoute,
});
