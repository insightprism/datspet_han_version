/** @type {import('next').NextConfig} */
// DATSPET_STATIC_EXPORT=1 turns the build into a static export (out/) for the
// GPU-less prod deploy (spec §8.5): every page is a client component, so the
// site is plain files behind nginx — no Node SSR service on the CPU-only box.
// Dev (`next dev`) and the default build are unchanged.
const nextConfig = process.env.DATSPET_STATIC_EXPORT === "1" ? { output: "export" } : {};

export default nextConfig;
