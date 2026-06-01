export {};

declare global {
  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      openPath: (targetPath: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      selectSourceFolders: () => Promise<string[]>;
      selectEmbeddingFolder: () => Promise<string | null>;
      selectVaultFolder: () => Promise<string | null>;
      setActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      selectCoverImage: () => Promise<string | null>;
      getBackendUrl: () => Promise<string | null>;
      getBackendToken: () => Promise<string | null>;
      openVaultAnyway: () => Promise<string | null>;
      listSupportedFiles: (targetPaths: string[]) => Promise<string[]>;
      getDroppedFilePaths: (files: File[] | FileList) => string[];
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
