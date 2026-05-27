export {};

declare global {
  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      openPath: (targetPath: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
