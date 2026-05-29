export {};

declare global {
  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      openPath: (targetPath: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      selectSourceFolders: () => Promise<string[]>;
      selectVaultFolder: () => Promise<string | null>;
      selectCoverImage: () => Promise<string | null>;
      listSupportedFiles: (targetPaths: string[]) => Promise<string[]>;
      getDroppedFilePaths: (files: File[] | FileList) => string[];
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
