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
import { useStore } from "@/lib/mockStore";
import { MessageSquare, Layers, Files, Globe2, Settings, Plus, Link2, FolderOpen, Cable } from "lucide-react";

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
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const navigate = useNavigate();
  const { clusters, sources, createChat } = useStore();

  const go = (fn: () => void) => {
    fn();
    onOpenChange(false);
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() =>
              go(() => {
                const c = createChat(null);
                navigate({ to: "/chat/$chatId", params: { chatId: c.id } });
              })
            }
          >
            <Plus className="mr-2 h-4 w-4" /> New chat
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/clusters" }))}>
            <Layers className="mr-2 h-4 w-4" /> New cluster
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/sources" }))}>
            <Link2 className="mr-2 h-4 w-4" /> Add link
          </CommandItem>
          <CommandItem onSelect={() => go(() => navigate({ to: "/settings" }))}>
            <FolderOpen className="mr-2 h-4 w-4" /> Open vault
          </CommandItem>
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
                    style={{ background: `var(--cluster-${c.tint})` }}
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
              {sources.slice(0, 6).map((s) => (
                <CommandItem
                  key={s.id}
                  onSelect={() => go(() => navigate({ to: "/sources" }))}
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
