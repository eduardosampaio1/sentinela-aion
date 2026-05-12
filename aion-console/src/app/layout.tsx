import type { Metadata } from "next";
import "./globals.css";
import { AionSessionProvider } from "@/components/auth/session-provider";
import { I18nProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "Sentinela AION",
  description: "Controle sua IA em tempo real — Sentinela AION",
  icons: { icon: "/logo.svg" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" className="h-full antialiased">
      <body className="h-full">
        <I18nProvider>
          <AionSessionProvider>{children}</AionSessionProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
