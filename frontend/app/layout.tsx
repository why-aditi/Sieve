import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sieve",
  description: "Hidden subscription & recurring-payment leak detector",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
