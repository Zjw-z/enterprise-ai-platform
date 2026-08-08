import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000",
  ),
  title: {
    default: "Enterprise AI Platform",
    template: "%s · Enterprise AI Platform",
  },
  description: "企业级 AI Agent 平台统一系统管理控制台",
  openGraph: {
    title: "企业级 AI Agent 平台",
    description: "统一管理 · 全链追踪 · 安全治理",
    images: ["/og.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: "企业级 AI Agent 平台",
    description: "统一管理 · 全链追踪 · 安全治理",
    images: ["/og.png"],
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
