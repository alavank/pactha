// ⭐ O TÍTULO DA PRÉVIA DE COMPARTILHAMENTO — "Painel de Indicadores PACTHA -
// Conceição da Barra - Mobile".
//
// ⚠️ POR QUE ISTO É SERVER-SIDE E NÃO SAI DA PÁGINA. O WhatsApp (e Telegram,
// Slack, iMessage) buscam o link e leem as meta tags do HTML da PRIMEIRA
// resposta — não executam JavaScript. Um título montado no cliente chegaria
// tarde: o card já teria sido gerado com o texto genérico.
//
// O PROBLEMA QUE ISTO RESOLVE: uma assessoria que atende 50 municípios gera 100
// links (app + TV de cada) e, no grupo de WhatsApp, todos apareciam como
// "PACTHA — Indicadores". Não havia como saber qual link era de qual cidade nem
// se era o do celular ou o da TV.
//
// Falha SEMPRE para o genérico: prévia é enfeite, e nenhuma página pode quebrar
// porque o título não veio.

/** Onde o servidor do Next alcança a API. Em produção é a env do container
 *  (mesma que o proxy `/api` usa); em dev, o localhost do backend. NÃO dá para
 *  usar o `/api` relativo aqui: isto roda no servidor, sem origem. */
function apiBase(): string {
  return process.env.API_PROXY_TARGET || "http://localhost:8000";
}

export interface TituloLink {
  titulo: string;
  cidade: string | null;
  modo: string;
}

/**
 * Busca cidade + modo do link e monta o título.
 * @param slug   o slug de 12 chars da URL pública
 * @param modoPadrao "Mobile" (/m/) ou "Dashboard" (/t/) — usado se a API não responder
 */
export async function tituloDoLink(slug: string, modoPadrao: string): Promise<TituloLink> {
  const generico: TituloLink = {
    titulo: "Painel de Indicadores PACTHA",
    cidade: null,
    modo: modoPadrao,
  };
  try {
    const r = await fetch(
      `${apiBase()}/api/bi/tela-pub/${encodeURIComponent(slug)}/meta`,
      {
        // O nome da cidade de um link muda raramente; 5 min corta a ida à API a
        // cada visita sem congelar uma correção de cadastro.
        next: { revalidate: 300 },
        headers: { Accept: "application/json" },
      }
    );
    if (!r.ok) return generico;
    const d = (await r.json()) as Partial<TituloLink>;
    return {
      titulo: d.titulo || generico.titulo,
      cidade: d.cidade ?? null,
      modo: d.modo || modoPadrao,
    };
  } catch {
    return generico; // rede fora, API caída: a página abre igual
  }
}
