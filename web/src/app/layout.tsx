import type { Metadata } from "next";
import Link from "next/link";
import FloatingEmojis from "@/components/FloatingEmojis";
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
          <nav className="flex gap-5 text-sm font-medium">
            <Link href="/" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
              Home
            </Link>
            <Link href="/design" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
              Design
            </Link>
            <Link href="/make" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
              Describe
            </Link>
            <Link href="/house" className="hover:opacity-80" style={{ color: "var(--muted)" }}>
              Pet house
            </Link>
          </nav>
        </div>
        <div className="relative z-10 mx-auto max-w-4xl px-6 pb-40 pt-8">{children}</div>
      </body>
    </html>
  );
}
