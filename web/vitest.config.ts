import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

/**
 * Vitest — for the PURE logic only, deliberately.
 *
 * There is no jsdom and no React testing here, and that is the point: `designFlow.ts`
 * is a pure reducer (no React, no fetch, no DOM, no clock, no RNG), so it needs no
 * environment to test. Keeping the runner this small is what keeps it from becoming a
 * thing nobody runs. If a test ever needs a browser, that is a signal the logic under
 * it belongs in the reducer instead.
 *
 * WHY THIS EXISTS AT ALL (SPEC_PET_DESIGNER_FLOW §11): the flow shipped with zero
 * frontend tests, and both regressions found in review — a lock button that gated on
 * the wrong predicate, and a preview-failure dismissal that outlived its base — were
 * in this one file. Both fall out of a handful of assertions against the reducer. The
 * spec itself named the gap; this closes it.
 *
 * `@/*` mirrors tsconfig.json's path alias so imports resolve the same way Next does.
 */
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
