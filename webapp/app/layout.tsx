import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "araiadoc — Pipeline Dashboard",
  description: "Web UI for araiadoc document acquisition and processing tools",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${geistMono.variable} font-mono antialiased bg-background text-foreground min-h-screen`}>
        <header className="border-b border-border px-6 py-4 flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-green-500" />
            <span className="text-sm font-semibold tracking-tight">araiadoc</span>
          </div>
          <span className="text-muted-foreground text-sm">Pipeline Dashboard</span>
        </header>
        <main className="px-6 py-8 max-w-5xl mx-auto">{children}</main>
      </body>
    </html>
  );
}
