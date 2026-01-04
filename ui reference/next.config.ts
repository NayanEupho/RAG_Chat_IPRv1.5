import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: false,
  allowedDevOrigins: [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://0.0.0.0:3000",
    "http://10.20.41.185:3000",
  ],
  // Next.js 15 might need logging to see HMR errors
  logging: {
    fetches: {
      fullUrl: true,
    },
  },
};

export default nextConfig;
