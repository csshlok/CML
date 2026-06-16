type CopyElementToFigmaOptions = {
  element: HTMLElement;
  name: string;
};

function getElementFrame(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  return {
    width: Math.max(1, Math.ceil(rect.width)),
    height: Math.max(1, Math.ceil(Math.max(rect.height, element.scrollHeight))),
  };
}

export async function copyElementToFigma({
  element,
  name,
}: CopyElementToFigmaOptions) {
  if (!window.isSecureContext || !navigator.clipboard?.write) {
    throw new Error("Clipboard export requires a secure browser context with clipboard write access.");
  }

  const { createFigmaConverter } = await import("@figit/dom-to-figma");
  const { width, height } = getElementFrame(element);
  const figma = createFigmaConverter();
  const result = await figma.convert({
    element,
    width,
    height,
    name,
  });

  await navigator.clipboard.write([result.toClipboardItem()]);
}
