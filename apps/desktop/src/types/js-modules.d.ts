declare module "@/lib/bridge-presentation.js" {
  import type { BridgeCaptureResponse } from "@/lib/backend";

  export function describeBridgeCaptureResult(result: BridgeCaptureResponse): string;
  export function describeBridgeReviewDecision(review: Record<string, unknown>, approved: boolean): string;
}

declare module "@/lib/chat-presentation" {
  export type ChatInlineMarkdownToken = {
    type: "text" | "strong";
    content: string;
  };

  export function analysisModeLabel(intent: string, coverageLedger?: Record<string, unknown> | null): string;
  export function describeCoverage(coverageLedger?: Record<string, unknown> | null): string | null;
  export function describePartialFailure(mode?: string | null): string | null;
  export function statusToneForPartialFailure(mode?: string | null): "neutral" | "critical" | "warning" | "muted";
  export function tokenizeChatInlineMarkdown(value?: string | null): ChatInlineMarkdownToken[];
}

declare module "@/lib/chat-presentation.js" {
  export * from "@/lib/chat-presentation";
}

declare module "@/lib/extension-presentation.js" {
  export function buildExtensionSetupText(payload: {
    backendUrl: string | null;
    apiPrefix?: string;
    token: string;
    vaultId?: string;
    clusterId?: string;
    vaultPath?: string;
    clientName?: string;
    browser?: string;
  }): string;
  export function describeExtensionScope(
    allowedVaultIds: string[],
    vaultNamesById: Map<string, string>,
  ): string;
}

declare module "d3-force-3d" {
  export function forceCollide<Node = unknown>(radius?: number | ((node: Node) => number)): {
    radius(value: number | ((node: Node) => number)): unknown;
    strength(value: number): unknown;
  };
}
