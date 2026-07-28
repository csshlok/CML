function createDroppedFilePathStore(target, getPathForFile) {
  let pendingPaths = [];

  target.addEventListener(
    "drop",
    (event) => {
      const files = event?.dataTransfer?.files;
      pendingPaths = files
        ? Array.from(files)
            .map((file) => {
              try {
                return getPathForFile(file);
              } catch {
                return "";
              }
            })
            .filter(Boolean)
        : [];
    },
    true,
  );

  return {
    consume() {
      const paths = pendingPaths;
      pendingPaths = [];
      return paths;
    },
  };
}

module.exports = {
  createDroppedFilePathStore,
};
