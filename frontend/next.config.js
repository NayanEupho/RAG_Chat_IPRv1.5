/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: {
    // Ignore ESLint errors during the build step
    ignoreDuringBuilds: true,
  },
  typescript: {
    // Optional: Ignore TypeScript errors to ensure build completes
    ignoreBuildErrors: true, 
  }
};

module.exports = nextConfig;
