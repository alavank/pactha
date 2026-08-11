"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import api from "@/lib/api";
import type { User } from "@/types";
import { allowedTelasOf } from "@/lib/telas";
import { abasVisiveis } from "@/lib/configuracoes";

/** A raiz de Configurações não tem conteúdo próprio: manda para a PRIMEIRA aba
 *  que esta pessoa pode ver. Quem não vê nenhuma (não deveria chegar aqui, o
 *  item nem aparece no menu) volta para a home em vez de encarar uma casca
 *  vazia. */
export default function ConfiguracoesIndex() {
  const router = useRouter();
  const [semAcesso, setSemAcesso] = useState(false);

  useEffect(() => {
    let vivo = true;
    api.get<User>("/auth/me")
      .then((r) => {
        if (!vivo) return;
        const abas = abasVisiveis(r.data, allowedTelasOf(r.data));
        if (abas.length > 0) router.replace(abas[0].href);
        else { setSemAcesso(true); router.replace("/dashboard"); }
      })
      .catch(() => { if (vivo) router.replace("/dashboard"); });
    return () => { vivo = false; };
  }, [router]);

  return (
    <div className="flex items-center gap-2 p-6 text-sm" style={{ color: "var(--bi-muted)" }}>
      {!semAcesso && <Loader2 className="size-4 animate-spin" />}
      {semAcesso ? "Sem acesso às configurações." : "Abrindo…"}
    </div>
  );
}
