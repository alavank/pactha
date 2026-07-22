"use client";
import { useEffect } from "react";

// Registra o service worker (push + notificationclick). Sem offline caching.
export function RegisterSW() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);
  return null;
}
