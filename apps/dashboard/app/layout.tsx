import type { Metadata } from "next";
import fa from "@/locales/fa.json";
import "./globals.css";

export const metadata: Metadata = {
  title: fa.app.title,
  description: fa.app.tagline,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
