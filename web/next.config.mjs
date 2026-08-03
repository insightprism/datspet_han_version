/** @type {import('next').NextConfig} */
// DATSPET_STATIC_EXPORT=1 turns the build into a static export (out/) for the
// GPU-less prod deploy (spec §8.5): every page is a client component, so the
// site is plain files behind nginx — no Node SSR service on the CPU-only box.
// Dev (`next dev`) and the default build are unchanged.
//
// DEV-ONLY same-origin proxy: `next dev` proxies /api/* to the DatsPet backend
// (:19954) so the browser talks to ONE origin (:19955). This makes the launch
// cookie FIRST-PARTY — without it the cookie is SameSite=None; Secure and set
// cross-origin (:19954 ≠ :19955), which Firefox refuses to store over plain
// http://localhost (Chrome is lenient; Firefox is not), so the signed-in state
// never sticks. The static export (prod) sets no rewrites — there nginx serves
// the API same-origin. Override the backend with DATSPET_API_ORIGIN.
const isStaticExport = process.env.DATSPET_STATIC_EXPORT === "1";

// DATSPET_DIST_DIR builds into a directory OTHER than `.next`. The preflight
// (scripts/preflight_static_export.py) uses it to build a throwaway export while
// a dev server is live: `next dev` and `next build` collide only through a SHARED
// .next/, so a build with its own distDir cannot poison the dev server, and
// scripts/guard-build-vs-dev.js stands down when this is set. Unset = `.next`,
// i.e. every normal dev/build/deploy path is untouched.
const distDir = process.env.DATSPET_DIST_DIR || undefined;

const nextConfig = isStaticExport
  ? { output: "export", ...(distDir ? { distDir } : {}) }
  : {
      ...(distDir ? { distDir } : {}),
      // SSE must flow through the dev proxy unbuffered: Next's built-in
      // compression holds event-stream bytes until the buffer fills, so the
      // arena room stream (SPEC_PET_ARENA_ROOMS §3.2) delivers nothing and
      // the lobby looks frozen — dev-only, and invisible in prod, where the
      // static export has no Node server and nginx owns buffering (§5.1).
      compress: false,
      async rewrites() {
        const api = process.env.DATSPET_API_ORIGIN || "http://localhost:19954";
        // Proxy BOTH the XHR API (/api/*) and the browser-navigated backend
        // routes (/launch, /partner/*) so the whole flow is same-origin on the
        // frontend host — the launch cookie is then first-party (Firefox stores
        // it; cross-origin Secure over http it would not). The registered partner
        // launch_base_url must point at the FRONTEND (:19955/launch) so DatsMe's
        // redirect lands here and the cookie is set as :19955.
        return [
          { source: "/api/:path*", destination: `${api}/api/:path*` },
          { source: "/launch", destination: `${api}/launch` },
          { source: "/partner/:path*", destination: `${api}/partner/:path*` },
          // The spectator URL (SPEC_PET_ARENA_ROOMS R3): /arena/{code} serves
          // the watch shell. Prod's nginx does the same against the export.
          { source: "/arena/:code((?!watch$)[A-Za-z0-9_-]{8,24})",
            destination: "/arena/watch" },
        ];
      },
    };

export default nextConfig;
