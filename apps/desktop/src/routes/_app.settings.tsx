import { createFileRoute } from "@tanstack/react-router";
import { useStore } from "@/lib/mockStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/settings")({
  head: () => ({ meta: [{ title: "Settings" }] }),
  component: SettingsView,
});

function SettingsView() {
  const { vaultPath, setVault } = useStore();
  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="font-serif text-3xl">Settings</h1>
      <section className="mt-8 rounded-md border border-border bg-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Vault location
        </div>
        <div className="mt-2 flex gap-2">
          <Input
            defaultValue={vaultPath ?? ""}
            onBlur={(e) => setVault(e.target.value)}
          />
          <Button variant="outline">Browse</Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Your vault stays on this device. Move it any time.
        </p>
      </section>

      <section className="mt-6 rounded-md border border-border bg-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Shortcuts</div>
        <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Command palette</dt><dd>Ctrl/Cmd K</dd>
          <dt className="text-muted-foreground">New chat</dt><dd>Ctrl/Cmd N</dd>
          <dt className="text-muted-foreground">New cluster</dt><dd>Ctrl/Cmd Shift N</dd>
          <dt className="text-muted-foreground">Add link</dt><dd>Ctrl/Cmd L</dd>
          <dt className="text-muted-foreground">Open vault</dt><dd>Ctrl/Cmd O</dd>
          <dt className="text-muted-foreground">Send message</dt><dd>Ctrl/Cmd Enter</dd>
        </dl>
      </section>

      <section className="mt-6 rounded-md border border-border bg-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Advanced</div>
        <p className="mt-2 text-sm text-muted-foreground">
          Power-user details like training logs and expert versions appear here.
        </p>
      </section>
    </div>
  );
}
