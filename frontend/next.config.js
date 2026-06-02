/** @type {import('next').NextConfig} */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  async rewrites() {
    // Proxy non-SSE API calls to the FastAPI backend for dev convenience.
    // NOTE: SSE (/api/analyses/{id}/events) MUST hit the origin directly,
    // not this rewrite, because rewrites buffer streamed responses.
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
