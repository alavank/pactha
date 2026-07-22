"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Raiz: detecta o ambiente e leva pro modo certo. Override por ?mode=app|tv.
export default function Root() {
  const router = useRouter();
  useEffect(() => {
    const mode = new URLSearchParams(window.location.search).get("mode");
    if (mode === "tv") return void router.replace("/tv");
    if (mode === "app") return void router.replace("/app");
    const bigScreen =
      window.innerWidth >= 1024 && !window.matchMedia("(pointer: coarse)").matches;
    router.replace(bigScreen ? "/tv" : "/app");
  }, [router]);

  return <div className="min-h-dvh grid place-items-center bg-page text-ink-3 text-sm">Abrindo painel…</div>;
}
