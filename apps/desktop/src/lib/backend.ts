import { useEffect, useState } from "react";

const BACKEND_URL = "http://127.0.0.1:7342";

export type BackendHealthStatus = "checking" | "online" | "offline";

export function useBackendHealth() {
  const [status, setStatus] = useState<BackendHealthStatus>("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const response = await fetch(`${BACKEND_URL}/health`, {
          signal: AbortSignal.timeout(1000),
        });
        if (!cancelled) setStatus(response.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setStatus("offline");
      }
    }

    check();
    const id = window.setInterval(check, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return {
    status,
    url: BACKEND_URL,
  };
}
