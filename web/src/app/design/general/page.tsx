"use client";

/**
 * General designer — the power-user / long-tail path (SPEC_PET_DESIGNER_PLATFORM
 * §3.3): redesign ANY house pet with color/accessories/strength/poses, no theming,
 * everything exposed. This is today's `/design` page, unchanged in behavior — the
 * form/preview/pose machinery moved verbatim into the shared <PetDesigner> (§8.1);
 * this page owns only its header + nav chrome and drops the designer in.
 */

import Link from "next/link";
import PetDesigner from "@/components/PetDesigner";

export default function GeneralDesignPage() {
  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Design your own
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Start from a pet in the house, pick a new color and some accessories, and it gets
        redrawn to your design — same pet, new look. The prompt is composed for you.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/design"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
        >
          ← All the design worlds
        </Link>
        <Link
          href="/make"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
        >
          Describe a pet instead
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      <PetDesigner />
    </main>
  );
}
