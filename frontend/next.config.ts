import type { NextConfig } from "next";
import { getBackendUrl } from "@/lib/backend-url";

const nextConfig: NextConfig = {
  async rewrites() {
    const backendUrl = getBackendUrl(process.env.BACKEND_URL);
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
