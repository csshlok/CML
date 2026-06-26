declare module "@/lib/bridge-presentation.js" {
  import type { BridgeCaptureResponse } from "@/lib/backend";

  export function describeBridgeCaptureResult(result: BridgeCaptureResponse): string;
  export function describeBridgeReviewDecision(review: Record<string, unknown>, approved: boolean): string;
}

declare module "@/lib/quick-capture.js" {
  import type { BridgeArtifactCapturePayload, BridgeExternalTurnPayload } from "@/lib/backend";

  export type QuickCaptureMode = "artifact" | "turn";
  export type QuickCaptureDraft = {
    mode: QuickCaptureMode;
    vaultId: string;
    clusterId: string;
    clientName: string;
    title: string;
    prompt: string;
    response: string;
  };

  export function createQuickCaptureDraft(mode?: QuickCaptureMode): QuickCaptureDraft;
  export function applyClipboardTextToDraft(
    draft: QuickCaptureDraft,
    clipboardText: string,
  ): QuickCaptureDraft;
  export function canSubmitQuickCapture(draft: QuickCaptureDraft): boolean;
  export function buildQuickCaptureSubmission(
    draft: QuickCaptureDraft,
  ):
    | { kind: "turn"; payload: BridgeExternalTurnPayload }
    | { kind: "artifact"; payload: BridgeArtifactCapturePayload };
}

declare module "@/lib/chat-presentation" {
  export function analysisModeLabel(intent: string, coverageLedger?: Record<string, unknown> | null): string;
  export function describeCoverage(coverageLedger?: Record<string, unknown> | null): string | null;
  export function describePartialFailure(mode?: string | null): string | null;
  export function statusToneForPartialFailure(mode?: string | null): "neutral" | "critical" | "warning" | "muted";
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
