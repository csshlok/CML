import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";
import { SourceImportProvider } from "@/components/product/SourceImportProgress";

export const Route = createFileRoute("/_app")({
  component: AppRoute,
});

function AppRoute() {
  return (
    <SourceImportProvider>
      <AppShell />
    </SourceImportProvider>
  );
}
