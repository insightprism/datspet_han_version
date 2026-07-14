"use client";

/**
 * App home — the "Design a pet" landing (SPEC_PET_DESIGNER_PLATFORM §2). This is
 * the front door: opening the app (standalone) lands here. The same landing also
 * renders at /design (the DPP launch deep-link target), so a DatsMe "Design your
 * pet" launch arrives at the identical page with no host change. "Describe a pet
 * instead" → /make (the free-text Make-your-own flow).
 */

import DesignLanding from "@/components/DesignLanding";

export default function HomePage() {
  return <DesignLanding />;
}
