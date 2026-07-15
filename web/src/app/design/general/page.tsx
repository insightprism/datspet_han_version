"use client";

/**
 * The General designer — /design/general. The three-step flow of
 * SPEC_PET_DESIGNER_FLOW: an archetype, a design, an animation.
 *
 * Promoted from the /design/general2 sandbox (build step 8) once the flow was accepted.
 * The sandbox route is gone; this IS the designer the DatsMe launch lands users in
 * (the DPP deep-links to /design, and General is the path off that landing).
 *
 * This page is CHROME ONLY: a heading, the three steps, and <Designer>. It does not
 * fetch the catalog, pick a base, or know that a "reference" exists — the designer owns
 * all of that. That boundary is the platform spec's §0 (bespoke chrome, shared
 * contract), and it is what lets a themed page exist without owning a private copy of
 * how generation works.
 *
 * NOT cited: SPEC_PET_DESIGNER_PLATFORM §3.3. The page this replaced claimed it as its
 * "inherited contract", but §3.3 mandates General = "free-text, redesign-any-house-pet,
 * everything exposed" — which commits 53da4fd and 74c1783 deliberately overrode long
 * before this redesign. It is not a constraint on this page; the §3.3 rewrite is tracked
 * in SPEC_PET_DESIGNER_FLOW §11.
 */

import Designer from "./Designer";

// The three steps, in the user's own words (§0). This is the whole page copy: naming
// what each step GIVES you beats describing the flow, and it means the numbered cards
// below read as the answers to a question the header already asked.
const STEPS = [
  "Start from what a typical animal looks like",
  "Then make it yours — colour, shape, accessories, anything else",
  "Animate it and bring it to life, ready for DatsMe",
] as const;

export default function GeneralDesignPage() {
  return (
    <main>
      {/* The sandbox badge is gone with the sandbox: it existed to tell two
          indistinguishable tabs apart, and there is only one route now. */}
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Design your own
      </h1>
      <ol className="mb-6 flex flex-col gap-1.5">
        {STEPS.map((text, i) => (
          <li key={text} className="flex items-baseline gap-2.5 text-sm leading-relaxed">
            <span className="mono text-xs" style={{ color: "var(--faint)" }}>
              step {i + 1}
            </span>
            <span style={{ color: "var(--muted)" }}>{text}</span>
          </li>
        ))}
      </ol>

      <Designer />
    </main>
  );
}
