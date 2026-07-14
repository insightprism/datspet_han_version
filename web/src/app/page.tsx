"use client";

/**
 * App home — the public front door (SPEC_DATSPET_FRONT_DOOR §4). Explains DatsPet
 * + its DatsMe relationship, and offers Sign in with DatsMe / Create account
 * (integrated) or Start designing (standalone). The Design landing (the tiles)
 * still lives at /design — the DPP launch deep-link target, unchanged.
 */

import PublicLanding from "@/components/PublicLanding";

export default function HomePage() {
  return <PublicLanding />;
}
