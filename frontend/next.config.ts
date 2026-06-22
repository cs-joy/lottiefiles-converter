import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 1. Put it right here at the root level:
  allowedDevOrigins: [
    'increased-sugar-fourth-chicago.trycloudflare.com',
    '*.trycloudflare.com' // Using a wildcard is great if Cloudflare changes the URL on restart
  ],

  // 2. Do NOT put it inside here:
  experimental: {
    // Other experimental features go here, but NOT allowedDevOrigins
  },
};

export default nextConfig;