import type { NextConfig } from "next";

/**
 * The production build is a static export served by FastAPI on the same origin,
 * so cookies stay first-party and no proxy is required.
 * In development the app talks to the API through NEXT_PUBLIC_API_BASE.
 */
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  reactStrictMode: true,
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;
