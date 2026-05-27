const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("cmlDesktop", {
  platform: process.platform,
});
