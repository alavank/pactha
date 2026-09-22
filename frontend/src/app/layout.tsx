import type { Metadata } from "next";
import { Nunito } from "next/font/google";
import "./globals.css";
import { Toaster } from "react-hot-toast";
import { DESCRICAO, NOME_CLIENTE, SITE_URL, TITULO } from "@/lib/previa-link";

// Fonte do design "Base" — Nunito em tudo (inclusive onde havia font-mono).
const nunito = Nunito({
  variable: "--font-nunito",
  subsets: ["latin"],
  display: "swap",
});

/* A prévia do link (WhatsApp, Telegram, e-mail) leva o NOME DO CLIENTE: são sete
   ambientes, e sem isso os links chegavam todos iguais. Ver `lib/previa-link.ts`.
   A imagem grande é `app/opengraph-image.tsx` — o Next a liga sozinho ao
   `og:image`, e o `metadataBase` a torna absoluta. */
export const metadata: Metadata = {
  ...(SITE_URL ? { metadataBase: new URL(SITE_URL) } : {}),
  title: TITULO,
  description: DESCRICAO,
  applicationName: "PACTHA",
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: NOME_CLIENTE ? `PACTHA - ${NOME_CLIENTE}` : "PACTHA",
    title: TITULO,
    description: DESCRICAO,
    ...(SITE_URL ? { url: SITE_URL } : {}),
  },
  // `summary_large_image` é o que faz a prévia sair GRANDE (e não o quadradinho).
  twitter: { card: "summary_large_image", title: TITULO, description: DESCRICAO },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" data-theme="pactha" className={`${nunito.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-base-200">
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('pactha_theme');if(t==='pactha-dark'||t==='pactha')document.documentElement.setAttribute('data-theme',t);}catch(e){}`,
          }}
        />
        {children}
        <Toaster position="top-right" />
      </body>
    </html>
  );
}
