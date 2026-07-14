"use client";

/**
 * /design — the DPP launch deep-link target (webui/datsme_integration.py redirects
 * a "Design a pet" launch here). Renders the SAME <DesignLanding> as the app home
 * (/), so the launch flow is unchanged and the host needs no edit. Keeping this
 * route means the deployed launch URL (/design?from=datsme) stays valid.
 */

import DesignLanding from "@/components/DesignLanding";

export default function DesignPage() {
  return <DesignLanding />;
}
