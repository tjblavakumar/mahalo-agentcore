import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";

export const metadata: Metadata = {
  title: "MAHALO3 - AI-Powered SDLC Platform",
  description: "Multi-persona SDLC platform with conversational AI agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
