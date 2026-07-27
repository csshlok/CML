import { useEffect, useState } from "react";

export function useLocalImage(path: string | null | undefined) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!path) {
      setSource(null);
      return;
    }
    if (/^data:image\/(?:png|jpeg|webp|gif);base64,/i.test(path) || /^https:/i.test(path)) {
      setSource(path);
      return;
    }
    setSource(null);
    void window.cmlDesktop?.readLocalImage(path).then((next) => {
      if (!cancelled) setSource(next ?? null);
    }).catch(() => {
      if (!cancelled) setSource(null);
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return source;
}
