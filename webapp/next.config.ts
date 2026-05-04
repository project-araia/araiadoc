import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Mark 'child_process' as external so Turbopack doesn't try to bundle it
  serverExternalPackages: ["child_process"],

  // Allow access from any local network host so that buttons and JS hydration
  // work when the webapp is accessed via an IP address (not just localhost).
  allowedDevOrigins: ["*.local", "*.internal", "192.168.*.*", "10.*.*.*"],
};

export default nextConfig;
