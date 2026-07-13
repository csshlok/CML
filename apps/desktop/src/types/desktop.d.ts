export {};

declare global {
  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      openPath: (targetPath: string) => Promise<boolean>;
      openExternal: (url: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      selectSourceFolders: () => Promise<string[]>;
      selectEmbeddingFolder: () => Promise<string | null>;
      selectModelFolder: () => Promise<string | null>;
      selectVaultFolder: () => Promise<string | null>;
      prepareActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      setActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      clearActiveVaultFolder: () => Promise<string | null>;
      selectCoverImage: () => Promise<string | null>;
      getBackendUrl: () => Promise<string | null>;
      getBackendToken: () => Promise<string | null>;
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
