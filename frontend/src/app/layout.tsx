import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "react-hot-toast";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PACTHA - Monitoramento de Convenios",
  description: "Sistema de Monitoramento de Convenios e Transferencias Governamentais",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" data-theme="pacta" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-base-200">
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('pacta_theme');if(t==='pacta-dark'||t==='pacta')document.documentElement.setAttribute('data-theme',t);}catch(e){}`,
          }}
        />
        {children}
        <Toaster position="top-right" />
      </body>
    </html>
  );
}
