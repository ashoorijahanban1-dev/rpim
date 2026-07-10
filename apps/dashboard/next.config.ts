import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output → slim Docker runtime image (no node_modules copy).
  output: "standalone",
  // Browser talks same-origin (/api/...) everywhere; in production Coolify's
  // proxy has no /api route on the app domain, so the Next server forwards
  // to core-api over the compose network. Locally/CI the `local` Caddy
  // intercepts /api/* first, so this rewrite only matters on the servers.
  // Own filesystem routes (e.g. /api/health) win over afterFiles rewrites.
  async rewrites() {
    const coreApi = process.env.CORE_API_INTERNAL_URL ?? "http://core-api:8000";
    return [{ source: "/api/:path*", destination: `${coreApi}/:path*` }];
  },
};

export default nextConfig;
