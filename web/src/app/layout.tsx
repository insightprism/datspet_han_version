import type { Metadata } from "next";
import Link from "next/link";
import FloatingEmojis from "@/components/FloatingEmojis";
import NavAuth from "@/components/NavAuth";
import { HOUSE_NAME } from "@/lib/houseCopy";
import "./globals.css";

// DatsMe pages scatter faint interest glyphs in the background
// (FloatingEmojis, copied verbatim from datsme_me). Pet Maker's
// interest is animals, so every page gets a drifting menagerie.
const ANIMAL_GLYPHS = "🐶,🐱,🐰,🦊,🐼,🐧,🐵,🦁,🐢,🦜,🐙,🦔,🐴,🐸,🦋,🐟";

export const metadata: Metadata = {
  title: "DatsMe Pet Maker",
  description:
    "Describe a pet or drop in a picture — get a living DatsMe pet, generated locally on the GPU.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <FloatingEmojis emojis={ANIMAL_GLYPHS} />
        <div
          className="sticky top-0 z-40 flex items-center justify-between px-6 py-3 backdrop-blur"
          style={{ borderBottom: "1px solid var(--line)", background: "rgba(15,15,15,0.75)" }}
        >
          <span className="font-bold" style={{ color: "var(--heading)" }}>
            Dats<span style={{ color: "var(--accent)" }}>Me</span>{" "}
            <span className="font-normal" style={{ color: "var(--muted)" }}>Pet Maker</span>
          </span>
          <div className="flex items-center gap-6">
            <nav className="flex gap-5 text-sm font-medium">
              <Link href="/" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
                Home
              </Link>
              <Link href="/design" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
                Design
              </Link>
              {/* The shop earned its nav entry on 2026-07-31 (owner call),
                  reversing the old "no new nav item" decision from the archived
                  catalog spec §3 — it was a placeholder grid then, a store now. */}
              <Link href="/catalog" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
                Pet Store
              </Link>
              <Link href="/house" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
                {HOUSE_NAME}
              </Link>
              {/* The Pet Games (SPEC_PET_ARENA §12 Phase 2) — same precedent
                  as the store's entry above: a real surface earns its link. */}
              <Link href="/arena" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
                Games
              </Link>
            </nav>
            <NavAuth />
          </div>
        </div>
        <div className="relative z-10 mx-auto max-w-4xl px-6 pb-40 pt-8">{children}</div>
      </body>
    </html>
  );
}
