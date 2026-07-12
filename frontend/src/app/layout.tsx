import type { Metadata } from "next";
import { Nunito } from "next/font/google";
import "./globals.css";
import { Toaster } from "react-hot-toast";

// Fonte do design "Base" — Nunito em tudo (inclusive onde havia font-mono).
const nunito = Nunito({
  variable: "--font-nunito",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PACTHA - Monitoramento de Convenios",
  description: "Sistema de Monitoramento de Convenios e Transferencias Governamentais",
  icons: { icon: "/pactha-favicon.png" },
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
