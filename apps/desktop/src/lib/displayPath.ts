export function displayPath(value: string | null | undefined) {
  if (!value) return "";
  return value.replace(/\\/g, "/").replace(/\/{2,}/g, "/");
}
