import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/activity")({
  component: () => <Navigate to="/timeline" replace />,
});
