import type { LocalModelRecord, ModelRuntimeStatus } from "@/lib/backend";

export function isModelRuntimeReady(
  model: LocalModelRecord | null | undefined,
  runtime: ModelRuntimeStatus | null | undefined,
) {
  return Boolean(
    model?.active_chat &&
      runtime?.available &&
      (runtime.state === "ready" || runtime.state === "busy") &&
      runtime.model === model.id,
  );
}

export function modelReadinessLabel(
  model: LocalModelRecord,
  runtime: ModelRuntimeStatus | null | undefined,
) {
  if (isModelRuntimeReady(model, runtime)) return "Ready for chat";
  if (model.active_chat && runtime?.state === "starting") return "Starting chat model";
  if (model.active_chat) return "Chat model needs attention";
  if (model.compatibility?.chat_role_accepted) return "Compatible — select Use for chat";
  return "Not compatible with chat";
}
