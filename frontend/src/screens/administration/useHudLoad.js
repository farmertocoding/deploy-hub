import { useEffect, useState } from "react";

export function hudErrorPhase(err) {
  if (err?.signedOut) return "signed-out";
  if (err?.denied) return "permission-denied";
  if (err?.notFound) return "not-found";
  if (err?.conflict) return "conflict";
  return "error";
}

export function useHudLoad(loader, deps = []) {
  const [phase, setPhase] = useState("loading");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    Promise.resolve().then(loader).then((body) => {
      if (!cancelled) {
        setData(body);
        setPhase("live");
      }
    }).catch((err) => {
      if (cancelled) return;
      setError(err?.data?.detail || "HTTP error");
      setPhase(hudErrorPhase(err));
    });
    return () => { cancelled = true; };
  }, [...deps, tick]);
  return {
    phase,
    data,
    error,
    setData,
    setPhase,
    retry: () => setTick((n) => n + 1),
    asOf: data?.observed_at,
  };
}
