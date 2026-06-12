import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Auto Triage Setup",
  description: "Setup console for repository and alert triage configuration.",
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
