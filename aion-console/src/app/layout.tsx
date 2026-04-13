import type { Metadata } from "next";
import "./globals.css";

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
      <body className="h-full">{children}</body>
    </html>
  );
}
