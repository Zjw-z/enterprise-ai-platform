import type { Metadata } from "next";
import { PlatformConsole } from "./platform-console";

export const metadata: Metadata = {
  title: "Enterprise AI Platform",
  description: "企业级 AI Agent 平台统一系统管理控制台",
};

export default function Home() {
  return <PlatformConsole />;
}
