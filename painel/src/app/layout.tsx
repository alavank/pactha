import type { Metadata, Viewport } from "next";
import { Sora, Inter } from "next/font/google";
import "./globals.css";
import { RegisterSW } from "@/components/RegisterSW";

// Display pesado (headings/numeros) + corpo neutro — casa com as refs fintech.
const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  display: "swap",
  weight: ["600", "700", "800"],
});
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const CLIENT = process.env.NEXT_PUBLIC_CLIENT_NAME || "Município";

export const metadata: Metadata = {
  title: `Painel Executivo · ${CLIENT}`,
  description: "Panorama de recursos, emendas e documentação do município.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icons/icon.svg", apple: "/icons/icon.svg" },
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Painel" },
};

export const viewport: Viewport = {
  themeColor: "#e9efea",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={`${sora.variable} ${inter.variable}`}>
      <body>
        {/* Aplica o tema salvo ANTES da hidratacao (evita flash). Padrao = light. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('painel_theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}catch(e){}`,
          }}
        />
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
