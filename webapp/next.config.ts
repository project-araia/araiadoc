import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Mark 'child_process' as external so Turbopack doesn't try to bundle it
  serverExternalPackages: ["child_process"],
};

export default nextConfig;
