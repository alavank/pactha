"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";
import api from "@/lib/api";
import type { User } from "@/types";
import { allowedTelasOf } from "@/lib/telas";
import { abasVisiveis } from "@/lib/configuracoes";
import { TituloTela } from "@/components/TituloTela";

/** ⭐ CONFIGURAÇÕES — a casa das telas de administração, em abas.
 *
 *  Seis telas viviam soltas no menu lateral (Usuários, Auditoria, Cofre,
 *  Sessões, Service Tokens, Status dos Dados) e viraram abas de um lugar só,
 *  mais a de Parâmetros. Pedido do dono (11/08/2026): "um menu de configurações
 *  onde aglomere algumas opções que já temos no menu lateral".
 *
 *  ⚠️ A BARRA DE ABAS É FILTRADA, e por isso este layout busca `/auth/me`: cada
 *  pessoa vê só as abas que já podia ver como item de menu. Quem tem só o Cofre
 *  vê uma aba; o administrador vê todas menos as de dono; o dono vê tudo. A
 *  conta mora em `lib/configuracoes.ts::abasVisiveis`, junto da lista — regra e
 *  dado no mesmo arquivo não divergem.
 *
 *  A segurança de verdade continua no BACKEND (cada endpoint tem seu
 *  `ensure_tela`/`_require_admin`/`is_super_admin`); esconder aba é UX.
 */
export default function ConfiguracoesLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let vivo = true;
    api.get<User>("/auth/me")
      .then((r) => { if (vivo) setUser(r.data); })
      .catch(() => { /* sem /auth/me a barra fica vazia e a página abaixo se defende sozinha */ });
    return () => { vivo = false; };
  }, []);

  const abas = abasVisiveis(user, allowedTelasOf(user));

  return (
    <div className="space-y-4">
      <div className="border-b pb-3" style={{ borderColor: "var(--bi-line)" }}>
        <TituloTela icon={Settings}>Configurações</TituloTela>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Administração do ambiente: pessoas, acesso, credenciais e parâmetros.
        </p>
      </div>

      {abas.length > 0 && (
        /* Rola no eixo X em telas estreitas — a barra nunca empurra a página
           para os lados (a regra de ouro do produto: conteúdo largo rola dentro
           do próprio contêiner). */
        <div className="bi-scroll -mx-1 overflow-x-auto px-1">
          <nav className="flex min-w-max gap-1 border-b" style={{ borderColor: "var(--bi-line)" }}>
            {abas.map((aba) => {
              const ativa = pathname === aba.href || pathname.startsWith(`${aba.href}/`);
              const Icone = aba.icon;
              return (
                <Link
                  key={aba.href}
                  href={aba.href}
                  aria-current={ativa ? "page" : undefined}
                  className="flex items-center gap-1.5 whitespace-nowrap px-3 py-2 text-[13px] font-medium transition-colors"
                  style={{
                    color: ativa ? "var(--bi-text)" : "var(--bi-muted)",
                    /* A aba ativa é marcada por uma linha embaixo, e não por
                       fundo colorido: mesma gramática das abas do Painel. */
                    boxShadow: ativa ? "inset 0 -2px 0 0 var(--bi-cta)" : undefined,
                  }}
                >
                  <Icone className="size-3.5" />
                  {aba.label}
                </Link>
              );
            })}
          </nav>
        </div>
      )}

      {children}
    </div>
  );
}
