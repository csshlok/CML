export {};

declare global {
  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      openPath: (targetPath: string) => Promise<boolean>;
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
