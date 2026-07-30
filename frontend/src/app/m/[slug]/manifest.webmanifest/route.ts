// Manifest POR LINK. Tem de ser dinâmico: o `start_url` precisa apontar para o
// slug daquele gestor, senão o atalho instalado no celular abriria uma tela sem
// credencial e pediria login — que é exatamente o que o app existe para evitar.
//
// Por isso é uma route handler e não um arquivo estático em public/.
import { NextResponse } from "next/server";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const inicio = `/m/${encodeURIComponent(slug)}`;

  return NextResponse.json(
    {
      name: "PACTHA — Indicadores",
      short_name: "PACTHA",
      description:
        "Captação de recursos, convênios e transferências governamentais do município.",
      start_url: inicio,
      scope: inicio,
      // standalone = abre sem barra de endereço, com cara de aplicativo.
      display: "standalone",
      orientation: "portrait",
      // Combina com o tema escuro do painel: a barra de status do Android
      // acompanha, em vez de piscar branco na abertura.
      background_color: "#0a0c0b",
      theme_color: "#0a0c0b",
      lang: "pt-BR",
      dir: "ltr",
      icons: [
        { src: "/pwa-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
        { src: "/pwa-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
        // `maskable` tem margem de segurança: o Android recorta ~10% de cada
        // borda para o formato do launcher, e sem folga a arte sai decepada.
        { src: "/pwa-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
        { src: "/pwa-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      ],
    },
    {
      headers: {
        "Content-Type": "application/manifest+json; charset=utf-8",
        // Sem cache longo: o link é por gestor e o manifest muda com o slug.
        "Cache-Control": "public, max-age=300",
      },
    }
  );
}
