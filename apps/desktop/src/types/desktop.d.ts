export {};

declare global {
  type DesktopSetupPhase =
    | "fresh"
    | "profile_complete"
    | "vault_prepared"
    | "vault_committed"
    | "models_complete"
    | "memory_complete"
    | "complete"
    | "recovery";

  interface DesktopSetupState {
    schema_version: 1;
    phase: DesktopSetupPhase;
    profile: { display_name: string };
    vault: { id: string; name: string; path: string };
    chat_setup: { status: string; model_id: string };
    memory_setup: { status: string; model_id: string };
    tour: { status: "pending" | "completed" | "skipped"; step: number; version: 1 };
    updated_at: string;
  }

  interface DesktopWindowState {
    maximized: boolean;
    fullScreen: boolean;
  }

  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      windowControls: {
        getState: () => Promise<DesktopWindowState>;
        minimize: () => Promise<boolean>;
        toggleMaximize: () => Promise<DesktopWindowState>;
        close: () => Promise<boolean>;
        onStateChanged: (listener: (state: DesktopWindowState) => void) => () => void;
      };
      openPath: (targetPath: string) => Promise<boolean>;
      openExternal: (url: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      selectSourceFolders: () => Promise<string[]>;
      selectEmbeddingFolder: () => Promise<string | null>;
      selectModelFolder: () => Promise<string | null>;
      selectModelCheckpoint: () => Promise<string | null>;
      selectVaultFolder: () => Promise<string | null>;
      prepareActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      setActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      moveActiveVaultFolder: (targetPath: string) => Promise<{
        backend_url: string | null;
        path: string;
        old_copy_removed: boolean;
      } | null>;
      clearActiveVaultFolder: () => Promise<string | null>;
      selectCoverImage: () => Promise<string | null>;
      getBackendUrl: () => Promise<string | null>;
      getBackendToken: () => Promise<string | null>;
      getSetupState: () => Promise<DesktopSetupState>;
      updateSetupState: (patch: Partial<DesktopSetupState>) => Promise<DesktopSetupState>;
      resetAppSetup: () => Promise<DesktopSetupState>;
      finalizeActiveVaultDeletion: () => Promise<{ deleted: boolean; path: string }>;
      notifyRendererReady: (detail?: string) => Promise<boolean>;
      onBackendUrlChanged: (listener: (nextUrl: string | null) => void) => () => void;
      copyText: (value: string) => Promise<boolean>;
      openVaultAnyway: () => Promise<string | null>;
      listSupportedFiles: (targetPaths: string[]) => Promise<string[]>;
      scanSupportedFiles: (
        targetPaths: string[],
        limit?: number,
      ) => Promise<{ files: string[]; truncated: boolean; limit: number }>;
      getDroppedFilePaths: (files: File[] | FileList) => string[];
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
