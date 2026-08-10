import { create } from "zustand";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { createChatSession, listClustersPage, listSourcesPage, listVaults, useBackendGeneration, type ClusterRecord, type SourceRecord } from "@/lib/backend";
import { MessageSquare, Layers, Files, Globe2, Settings, Plus, FolderOpen, Cable, HeartPulse, LockKeyhole } from "lucide-react";

interface PaletteState {
  open: boolean;
  setOpen: (v: boolean | ((o: boolean) => boolean)) => void;
}

export const useCommandPalette = create<PaletteState>((set, get) => ({
  open: false,
  setOpen: (v) =>
    set({ open: typeof v === "function" ? (v as (o: boolean) => boolean)(get().open) : v }),
}));

export function CommandPalette({
  open,
  onOpenChange,
  onLock,
  onOpenHealth,
  lockAvailable,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onLock: () => Promise<void>;
  onOpenHealth: () => Promise<void>;
  lockAvailable: boolean;
}) {
  const navigate = useNavigate();
  const backendGeneration = useBackendGeneration();
  const [clusters, setClusters] = useState<ClusterRecord[]>([]);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [query, setQuery] = useState("");
  const requestSequence = useRef(0);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    let cancelled = false;
    const sequence = ++requestSequence.current;
    const controller = new AbortController();
    async function load() {
      try {
        const vault = (await listVaults())[0] ?? null;
        if (!vault) {
          if (!cancelled) {
            setClusters([]);
            setSources([]);
          }
          return;
        }
        const [clusterResult, sourceResult] = await Promise.allSettled([
          listClustersPage(vault.id, { limit: 20, query, signal: controller.signal }),
          listSourcesPage(vault.id, { limit: 20, query, signal: controller.signal }),
        ]);
        if (!cancelled && sequence === requestSequence.current) {
          setClusters(clusterResult.status === "fulfilled" ? clusterResult.value.items : []);
          setSources(sourceResult.status === "fulfilled" ? sourceResult.value.items : []);
        }
      } catch {
        if (!cancelled) {
          setClusters([]);
          setSources([]);
        }
      }
    }
    const timer = window.setTimeout(() => void load(), query ? 180 : 0);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [backendGeneration, open, query]);

  const go = (fn: () => void | Promise<void>) => {
    void fn();
    onOpenChange(false);
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Type a command or search..."
      />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() =>
              go(async () => {
                try {
                  const vault = (await listVaults())[0];
                  if (vault) {
                    const session = await createChatSession({ vault_id: vault.id, title: "New chat" });
                    navigate({ to: "/chat/$chatId", params: { chatId: session.id } });
                    return;
                  }
                } catch {
                  // Fall back to the chat index if backend chat creation is unavailable.
                }
                navigate({ to: "/chat" });
              })
            }
          >
            <Plus className="mr-2 h-4 w-4" /> New chat
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/clusters" }))}>
            <Layers className="mr-2 h-4 w-4" /> Open clusters
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/sources" }))}>
            <Plus className="mr-2 h-4 w-4" /> Add a source
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/settings", search: { section: "storage" } }))}>
            <FolderOpen className="mr-2 h-4 w-4" /> Library settings
          </CommandItem>
          <CommandItem onSelect={() => go(onOpenHealth)}>
            <HeartPulse className="mr-2 h-4 w-4" />
            Health status
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+Shift+H</span>
          </CommandItem>
          {lockAvailable ? (
            <CommandItem onSelect={() => go(onLock)}>
              <LockKeyhole className="mr-2 h-4 w-4" />
              Lock library
              <span className="ml-auto text-xs text-muted-foreground">Ctrl+L</span>
            </CommandItem>
          ) : null}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Go to">
          <CommandItem onSelect={() => go(() => navigate({ to: "/chat" }))}>
            <MessageSquare className="mr-2 h-4 w-4" /> Chat
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/clusters" }))}>
            <Layers className="mr-2 h-4 w-4" /> Clusters
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/sources" }))}>
            <Files className="mr-2 h-4 w-4" /> Sources
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/map" }))}>
            <Globe2 className="mr-2 h-4 w-4" /> Map
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/bridge" }))}>
            <Cable className="mr-2 h-4 w-4" /> Bridge
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/settings" }))}>
            <Settings className="mr-2 h-4 w-4" /> Settings
          </CommandItem>
        </CommandGroup>
        {clusters.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Clusters">
              {clusters.map((c) => (
                <CommandItem
                  key={c.id}
                  onSelect={() =>
                    go(() =>
                      navigate({ to: "/clusters/$clusterId", params: { clusterId: c.id } }),
                    )
                  }
                >
                  <span
                    className="mr-2 h-2.5 w-2.5 rounded-full"
                style={{ background: `var(--cluster-${c.color})` }}
                  />
                  {c.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        {sources.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Sources">
              {sources.map((s) => (
                <CommandItem
                  key={s.id}
                  onSelect={() => go(() => navigate({ to: "/sources", search: { source: s.id } }))}
                >
                  <Files className="mr-2 h-4 w-4" />
                  {s.title}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
