/* A PRÉVIA DO LINK — o que WhatsApp, Telegram e e-mail mostram ao colar o endereço
 * de um cliente (pedido do dono, 22/09/2026).
 *
 * São sete ambientes com a mesma cara; sem o nome do cliente na prévia, o link de
 * Juranda e o de Monte Sião chegavam iguais ("PACTHA - Monitoramento de
 * Convênios") e era questão de tempo alguém abrir o ambiente errado.
 *
 * ⚠️ TUDO AQUI É DE BUILD: cada tenant tem a própria imagem de frontend, com os
 * `NEXT_PUBLIC_*` embutidos pelo `build-frontend.yml`. Não há env de runtime — o
 * `metadata` do layout e a `opengraph-image` são gerados no `next build`.
 *
 * ⚠️ `NEXT_PUBLIC_SITE_URL` É OBRIGATÓRIA NA PRÁTICA: o WhatsApp só baixa a imagem
 * por URL ABSOLUTA, e o Next monta o `og:image` a partir do `metadataBase`. Sem
 * ela, a imagem sairia apontando para `http://localhost:3000` e a prévia voltaria
 * a ser só texto.
 */

/** "Juranda - PR", "Freitas & Associados"... — quem é o cliente deste ambiente. */
export const NOME_CLIENTE = (
  process.env.NEXT_PUBLIC_CLIENT_NAME || process.env.NEXT_PUBLIC_CLIENT_SUBTITLE || ""
).trim();

/** Endereço canônico do ambiente (o domínio próprio, não o sslip). */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "").trim();

export const SLOGAN = "Monitoramento de Convênios, Emendas e Transferências";

export const TITULO = NOME_CLIENTE
  ? `PACTHA - ${NOME_CLIENTE} | ${SLOGAN}.`
  : `PACTHA | ${SLOGAN}.`;

export const DESCRICAO =
  "Convênios, emendas parlamentares e transferências federais e estaduais num só " +
  "painel: prazos, repasses, obras e regularidade, atualizados todo dia pelas " +
  "fontes oficiais.";
