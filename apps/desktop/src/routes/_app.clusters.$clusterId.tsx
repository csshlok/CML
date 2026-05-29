import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useStore, expertLabel, sourceStateLabel } from "@/lib/mockStore";
import { ClusterDot, ExpertBadge } from "@/components/ClusterChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { MessageSquare } from "lucide-react";
import { ClusterMap } from "@/components/ClusterMap";

export const Route = createFileRoute("/_app/clusters/$clusterId")({
  head: () => ({ meta: [{ title: "Cluster" }] }),
  component: ClusterDetail,
});

function ClusterDetail() {
  const { clusterId } = Route.useParams();
  const navigate = useNavigate();
  const { clusters, sources, chats, renameCluster, createChat } = useStore();
  const cluster = clusters.find((c) => c.id === clusterId);
  if (!cluster) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Cluster not found.
      </div>
    );
  }
  const clusterSources = sources.filter((s) => s.clusterId === cluster.id);
  const clusterChats = chats.filter((c) => c.scopeClusterId === cluster.id);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="flex items-center gap-3">
          <ClusterDot tint={cluster.tint} size={12} />
          <Input
            defaultValue={cluster.name}
            onBlur={(e) => renameCluster(cluster.id, e.target.value)}
            className="h-9 max-w-sm border-transparent bg-transparent px-1 text-2xl font-semibold tracking-tight shadow-none focus-visible:bg-card"
          />
          <div className="ml-auto flex items-center gap-2">
            <ExpertBadge status={cluster.expert} />
            <Button
              size="sm"
              onClick={() => {
                const c = createChat(cluster.id);
                navigate({ to: "/chat/$chatId", params: { chatId: c.id } });
              }}
            >
              <MessageSquare className="mr-1.5 h-4 w-4" /> Chat with cluster
            </Button>
          </div>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{cluster.description}</p>

        <Tabs defaultValue="overview" className="mt-8">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="sources">Sources ({clusterSources.length})</TabsTrigger>
            <TabsTrigger value="chats">Chats ({clusterChats.length})</TabsTrigger>
            <TabsTrigger value="expert">Expert</TabsTrigger>
            <TabsTrigger value="map">Map</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-6 space-y-4">
            <Card title="Summary">{cluster.summary}</Card>
            <Card title="Style profile">{cluster.styleProfile}</Card>
            <Card title="Recent activity">
              <ul className="space-y-1.5 text-sm">
                {clusterChats.slice(0, 4).map((c) => (
                  <li key={c.id} className="text-muted-foreground">- {c.title}</li>
                ))}
                {clusterChats.length === 0 && (
                  <li className="text-muted-foreground">No chats yet.</li>
                )}
              </ul>
            </Card>
          </TabsContent>

          <TabsContent value="sources" className="mt-6">
            <div className="rounded-md border border-border">
              {clusterSources.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center justify-between border-b border-border px-4 py-2.5 text-sm last:border-b-0"
                >
                  <span className="truncate">{s.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {sourceStateLabel[s.state]}
                  </span>
                </div>
              ))}
              {clusterSources.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                  No sources in this cluster yet.
                </div>
              )}
            </div>
            <div className="mt-3 rounded-md border border-dashed border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
              Source picker for this cluster is pending. Add files in Mind or Sources, then accept suggested moves.
            </div>
          </TabsContent>

          <TabsContent value="chats" className="mt-6 space-y-1">
            {clusterChats.map((c) => (
              <div
                key={c.id}
                className="rounded-md border border-border bg-card px-4 py-3 text-sm"
              >
                {c.title}
              </div>
            ))}
            {clusterChats.length === 0 && (
              <p className="text-sm text-muted-foreground">No chats yet for this cluster.</p>
            )}
          </TabsContent>

          <TabsContent value="expert" className="mt-6 space-y-4">
            <Card title="Status">
              <div className="flex items-center justify-between">
                <ExpertBadge status={cluster.expert} />
                <span className="text-xs text-muted-foreground">
                  {expertLabel[cluster.expert]}
                </span>
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                {cluster.expert === "ready"
                  ? "This local expert is ready to inform answers in your voice."
                  : cluster.expert === "learning"
                  ? "This cluster is usable now. Its local expert is still learning in the background."
                  : "This local expert is being set up."}
              </p>
              <div className="mt-4 flex gap-2">
                <div className="rounded-md border border-dashed border-border bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
                  Training controls appear after the local expert queue is implemented.
                </div>
              </div>
            </Card>
            <details className="rounded-md border border-border bg-card px-4 py-3 text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                Advanced details
              </summary>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Training data</dt>
                <dd>{clusterSources.length} sources</dd>
                <dt className="text-muted-foreground">Last trained</dt>
                <dd>3 hours ago</dd>
                <dt className="text-muted-foreground">Version</dt>
                <dd>v0.4</dd>
                <dt className="text-muted-foreground">Model path</dt>
                <dd className="truncate">~/vault/experts/{cluster.id}</dd>
              </dl>
            </details>
          </TabsContent>

          <TabsContent value="map" className="mt-6">
            <div className="h-[420px] rounded-md border border-border bg-card">
              <ClusterMap focusClusterId={cluster.id} />
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs font-medium text-muted-foreground">
        {title}
      </div>
      <div className="mt-2 text-sm">{children}</div>
    </div>
  );
}
