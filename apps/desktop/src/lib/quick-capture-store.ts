import { create } from "zustand";

export type QuickCaptureMode = "artifact" | "turn";

interface QuickCaptureDialogState {
  open: boolean;
  mode: QuickCaptureMode;
  seedFromClipboard: boolean;
  openDialog: (options?: { mode?: QuickCaptureMode; seedFromClipboard?: boolean }) => void;
  closeDialog: () => void;
}

export const useQuickCaptureDialog = create<QuickCaptureDialogState>((set) => ({
  open: false,
  mode: "artifact",
  seedFromClipboard: false,
  openDialog: (options) =>
    set({
      open: true,
      mode: options?.mode ?? "artifact",
      seedFromClipboard: Boolean(options?.seedFromClipboard),
    }),
  closeDialog: () =>
    set({
      open: false,
      seedFromClipboard: false,
    }),
}));
