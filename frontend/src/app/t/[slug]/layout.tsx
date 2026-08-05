// Metadata do link público do Modo Tela (TV). Existe SÓ para a prévia de
// compartilhamento: o WhatsApp lê a Open Graph do HTML da primeira resposta e,
// sem isto, todo link de TV chegava no grupo como "PACTHA — Indicadores" — sem
// dizer a cidade nem se era a TV ou o app.
//
// O `/m/[slug]` (app de celular) já tinha um layout, por causa do manifest; o
// da TV nasce aqui, e as duas superfícies compartilham `tituloDoLink`.
import type { Metadata } from "next";
import { tituloDoLink } from "@/lib/tituloLinkPublico";

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params;
  const { titulo, cidade } = await tituloDoLink(slug, "Dashboard");
  const descricao = cidade
    ? `Indicadores de ${cidade} — captação, convênios e transferências.`
    : "Indicadores de captação, convênios e transferências.";
  return {
    title: titulo,
    description: descricao,
    openGraph: {
      title: titulo,
      description: descricao,
      type: "website",
      locale: "pt_BR",
      siteName: "PACTHA",
    },
    // Link privado: não entra em buscador. (A prévia do WhatsApp continua —
    // ela busca a URL diretamente, não depende de indexação.)
    robots: { index: false, follow: false },
  };
}

export default function TelaLayout({ children }: { children: React.ReactNode }) {
  return children;
}
