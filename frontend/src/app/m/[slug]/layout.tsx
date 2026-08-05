// Metadata do app de celular. Fica no layout (server) porque `manifest` e
// `theme-color` precisam sair no HTML da primeira resposta: se fossem injetados
// depois pelo cliente, o Chrome já teria decidido que a página não é instalável.
//
// O manifest é POR SLUG — ver a route handler ao lado. É o que faz o atalho na
// tela inicial abrir já credenciado, sem pedir login.
import type { Metadata, Viewport } from "next";
import { tituloDoLink } from "@/lib/tituloLinkPublico";

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params;
  const { titulo, cidade } = await tituloDoLink(slug, "Mobile");
  return {
    title: titulo,
    description: cidade
      ? `Captação de recursos, convênios e transferências governamentais de ${cidade}.`
      : "Captação de recursos, convênios e transferências governamentais do município.",
    // ⭐ A PRÉVIA DO WHATSAPP. Quem recebe o link vê o card com este título — e
    // é o que permite a uma assessoria distinguir 50 links num grupo. O
    // WhatsApp lê a Open Graph do HTML da PRIMEIRA resposta, sem rodar JS: por
    // isso o título vem daqui (server) e não da página.
    openGraph: {
      title: titulo,
      description: cidade
        ? `Indicadores de ${cidade} — captação, convênios e transferências.`
        : "Indicadores de captação, convênios e transferências.",
      type: "website",
      locale: "pt_BR",
      siteName: "PACTHA",
    },
    manifest: `/m/${encodeURIComponent(slug)}/manifest.webmanifest`,
    // iOS ignora o manifest para "Adicionar à Tela de Início"; quem manda são
    // estas metatags. Sem elas o atalho abre dentro do Safari, com barra.
    appleWebApp: {
      capable: true,
      statusBarStyle: "black-translucent",
      title: "PACTHA",
    },
    // Link privado: não deve entrar em buscador nem em preview de rede social.
    robots: { index: false, follow: false },
  };
}

export const viewport: Viewport = {
  themeColor: "#0a0c0b",
  width: "device-width",
  initialScale: 1,
  // Sem `maximumScale`: travar zoom quebra acessibilidade de quem precisa
  // ampliar, e é justamente o público que mais usa isto.
  viewportFit: "cover", // respeita o notch do iPhone
};

export default function MobileLayout({ children }: { children: React.ReactNode }) {
  return children;
}
