"use client";
// Filtro do Modo Tela vindo do SERVIDOR.
//
// O BroadcastChannel (lib/tela.ts) resolve bem um caso só: mesma máquina, outra
// janela. Não resolve o caso real do produto — a TV do gabinete é OUTRO
// APARELHO, e o link público roda sem login nenhum. Entre aparelhos não existe
// canal de navegador. Então quem carrega o filtro nesses casos é o servidor, e
// este hook faz o poll e avisa quando ele MUDOU.
//
// Por que poll e não SSE/WebSocket: a VPS é burstable (~0,6 vCPU sustentado) e
// uma TV é um cliente só, ligado o dia inteiro. Uma leitura de uma linha
// indexada a cada 10 s é barata e não segura conexão aberta à toa.
import { useEffect, useRef, useState } from "react";
import { getTelaFiltros, resolverTelaPub } from "./bi";
import { CONSOLIDADO_URL, FiltrosTela } from "./tela";

const POLL_MS = 10_000;

export interface FiltroServidor {
  /** null = o servidor ainda não mandou nada de útil (usa o filtro da URL). */
  filtros: FiltrosTela | null;
  /** Mensagem para a TV quando o link morreu — silêncio aqui deixaria um
   *  painel velho no ar parecendo dado atual. */
  erro: string | null;
  /** false enquanto a primeira resposta não chegou. No link público isso
   *  também significa "ainda não tenho token", então os dados não podem ir. */
  pronto: boolean;
}

export function useFiltroTelaServidor(slug?: string): FiltroServidor {
  const [filtros, setFiltros] = useState<FiltrosTela | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [pronto, setPronto] = useState(false);
  // Assinatura do último valor VINDO DO SERVIDOR. Só reagimos a mudança real:
  // aplicar todo poll desfaria o que o BroadcastChannel acabou de aplicar,
  // fazendo a tela piscar entre dois filtros.
  const ultimoRef = useRef<string>("");

  useEffect(() => {
    let vivo = true;

    const buscar = async () => {
      try {
        let scope: string;
        let anos: number[];

        if (slug) {
          const r = await resolverTelaPub(slug);
          // O token do quiosque vem daqui (e não da URL) — é isso que permite
          // encurtar o link e revogá-lo depois sem derrubar os outros.
          //
          // Vai numa CHAVE PRÓPRIA: gravado em `pactha_token` (a do login), ele
          // sequestrava a sessão de quem abrisse o link público no próprio
          // computador — todo o sistema passava a autenticar como o quiosque.
          if (r.token && typeof window !== "undefined") {
            localStorage.setItem("pactha_kiosk_token", r.token);
          }
          scope = r.scope || CONSOLIDADO_URL;
          anos = r.anos || [];
        } else {
          const r = await getTelaFiltros();
          // Sem linha publicada, o servidor não tem opinião: quem manda segue
          // sendo a URL/localStorage de quem abriu.
          if (!r || (r as { existe?: boolean }).existe === false) {
            if (vivo) setPronto(true);
            return;
          }
          scope = r.scope || CONSOLIDADO_URL;
          anos = r.anos || [];
        }

        if (!vivo) return;
        const assinatura = `${scope}|${[...anos].sort((a, b) => a - b).join(",")}`;
        if (assinatura !== ultimoRef.current) {
          ultimoRef.current = assinatura;
          setFiltros({ scope, anos });
        }
        setErro(null);
      } catch (e) {
        if (!vivo) return;
        const st = (e as { response?: { status?: number } })?.response?.status;
        // 404 no slug = revogado, expirado ou inexistente. Só vale avisar no
        // link público; no modo logado um erro de rede não pode apagar a tela.
        if (slug && st === 404) setErro("Link inválido, expirado ou revogado.");
      } finally {
        if (vivo) setPronto(true);
      }
    };

    void buscar();
    const id = setInterval(() => void buscar(), POLL_MS);
    return () => {
      vivo = false;
      clearInterval(id);
    };
  }, [slug]);

  return { filtros, erro, pronto };
}
