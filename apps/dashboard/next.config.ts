import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output → slim Docker runtime image (no node_modules copy).
  output: "standalone",
};

export default nextConfig;
