#!/usr/bin/env node
/**
 * Build preflight: refuse to `next build` while a **dev server for THIS
 * project** is live, because the two share one `.next` directory.
 *
 * Root cause this guards against: `next dev` and `next build` both write to
 * `.next/` (including `.next/cache/webpack`). Running a build while dev is live
 * overwrites the dev server's compiled chunks and manifests underneath it — the
 * dev server then serves 500s for its own chunks (blank screen), and webpack's
 * persistent cache can be left half-written, throwing
 * `ENOENT: rename '…N.pack.gz_' -> '…N.pack.gz'` on the next dev start. This is
 * the same poisoned-cache failure the launcher's self-heal recovers from; this
 * guard stops one of the ways it gets created in the first place.
 *
 * Precision (why port-alone is not enough): the danger is a **shared .next
 * directory**, not a busy port number. Two facts narrow the check so it doesn't
 * false-positive:
 *
 *   1. Same project directory. On the shared prod/staging host the PRODUCTION
 *      frontend runs `next start --port 19995` from /var/www/datsme/web, while a
 *      staging build runs from /var/www/datsme-staging/web — a DIFFERENT .next.
 *      No collision. So we only block when the port-holder's cwd resolves to the
 *      same project root as this build (process.cwd()).
 *   2. Dev, not start. Only `next dev` continuously writes .next/cache/webpack
 *      and is what gets poisoned. `next start` merely reads the built .next, so
 *      even a same-directory `next start` is not the hazard this guard targets.
 *   3. Same .next, not merely same directory. A build with DATSPET_DIST_DIR set
 *      writes somewhere else entirely (next.config.mjs maps it to `distDir`), so
 *      it cannot overwrite a dev server's chunks no matter whose cwd it shares.
 *      This is what lets scripts/preflight_static_export.py build a throwaway
 *      export while dev is live, WITHOUT ALLOW_BUILD_WITH_DEV=1 — that override
 *      would suppress the check on a build that genuinely does collide, which is
 *      a lie this guard should not have to accept to stay usable.
 *
 * Result: no dev server → no-op (CI, deploy boxes). A `next start` on the dev
 * port → no-op (the shared-host prod case). A build into its own distDir → no-op.
 * Only a `next dev` bound to THIS project's directory AND sharing its .next
 * blocks the build. Last-resort override: ALLOW_BUILD_WITH_DEV=1.
 */

const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const DEV_PORT = process.env.PETMAKER_FRONTEND_PORT || "19955";

// The project root this build writes to. npm runs the script with cwd = the
// package dir (web/), which is where `.next` lives — exactly the directory a
// colliding `next dev` would also be bound to.
const BUILD_ROOT = fs.realpathSync(process.cwd());

if (process.env.ALLOW_BUILD_WITH_DEV === "1") {
  console.log(
    `[guard-build-vs-dev] ALLOW_BUILD_WITH_DEV=1 set — skipping the dev-server check.`
  );
  process.exit(0);
}

// A build into its own distDir shares no state with the dev server (see #3
// above), so there is nothing to guard. Kept honest by next.config.mjs, which is
// the only reader of this variable: if that mapping is ever dropped, this branch
// must go with it or the guard starts waving through real collisions.
const DIST_DIR = process.env.DATSPET_DIST_DIR;
if (DIST_DIR && DIST_DIR !== ".next") {
  console.log(
    `[guard-build-vs-dev] Building into ${DIST_DIR}, not .next — no dev-server collision is possible.`
  );
  process.exit(0);
}

function pidsOnPort(port) {
  // ss is present on the dev/build hosts; lsof is not. Match the launcher.
  try {
    const out = execSync(`ss -ltnpH "sport = :${port}" 2>/dev/null`, {
      encoding: "utf8",
    });
    const pids = new Set();
    for (const m of out.matchAll(/pid=(\d+)/g)) pids.add(m[1]);
    return [...pids];
  } catch {
    // ss missing or errored — can't determine; don't block the build.
    return [];
  }
}

// The working directory a pid is bound to (its .next lives here), resolved
// through symlinks so it compares equal to BUILD_ROOT. null if unreadable.
function cwdOf(pid) {
  try {
    return fs.realpathSync(`/proc/${pid}/cwd`);
  } catch {
    return null;
  }
}

// The pid's command line, NUL-separated in /proc, joined with spaces. Used to
// tell `next dev` (the hazard) from `next start` (harmless — read-only on .next).
function cmdlineOf(pid) {
  try {
    return fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").replace(/\0/g, " ").trim();
  } catch {
    return "";
  }
}

// The parent pid of a pid, or null. Used to walk up the process tree.
function ppidOf(pid) {
  try {
    const out = execSync(`ps -o ppid= -p ${pid} 2>/dev/null`, { encoding: "utf8" }).trim();
    return out || null;
  } catch {
    return null;
  }
}

// A pid is a real collision only if it is a `next dev` AND its cwd is this
// build's project root (same .next).
//
// The `dev`/`start` verb almost never lives on the port-holder itself: Next
// forks a child `next-server` whose cmdline is just "next-server (vX)", and the
// actual "next dev" / "next start --port ..." string is on an ANCESTOR (the
// `sh -c next start …` / `npm exec next …` launcher). So we ALWAYS gather a few
// ancestor cmdlines — not only when the child's own cmdline looks non-Next —
// otherwise a `next start` (harmless, read-only on .next) gets misread as
// "can't tell" and wrongly blocked. That was the prod false-positive: the
// port-holder read "next-server", the parent-walk was skipped, and the guard
// never saw the "start" verb.
function collidesWith(pid) {
  const cwd = cwdOf(pid);
  if (cwd !== BUILD_ROOT) return false; // different project → different .next

  // Collect the port-holder's cmdline plus up to 3 ancestors, where the
  // dev/start verb lives.
  let cmd = cmdlineOf(pid);
  let cur = pid;
  for (let i = 0; i < 3; i++) {
    cur = ppidOf(cur);
    if (!cur || cur === "1" || cur === "0") break;
    cmd += " " + cmdlineOf(cur);
  }

  const isDev = /\bnext\b[^\n]*\bdev\b/.test(cmd);
  const isStart = /\bnext\b[^\n]*\bstart\b/.test(cmd);
  // Block a dev server (the hazard: it writes .next/cache/webpack). A same-dir
  // `next start` is read-only on .next, so don't block it. If we genuinely
  // can't tell (neither verb seen) but the cwd matches, err safe and block.
  if (isDev) return true;
  if (isStart) return false;
  return true; // cwd matches but verb unknown → block to be safe
}

const colliding = pidsOnPort(DEV_PORT).filter(collidesWith);

if (colliding.length > 0) {
  console.error(
    "\n[guard-build-vs-dev] REFUSING TO BUILD.\n" +
      `  A dev server for THIS project is live on port ${DEV_PORT} ` +
      `(pid ${colliding.join(", ")}, cwd ${BUILD_ROOT}).\n` +
      "  `next dev` and `next build` share this project's .next/ directory;\n" +
      "  building now would overwrite the dev server's chunks (blank screen)\n" +
      "  and can poison .next/cache/webpack (the recurring\n" +
      "  `ENOENT: rename …0.pack.gz_ -> …0.pack.gz` blank-screen bug).\n\n" +
      "  Do one of:\n" +
      "    • Stop the dev server first (Ctrl-C the start_petmaker_frontend_only.sh run).\n" +
      "    • Override if you know the collision is safe:\n" +
      "        ALLOW_BUILD_WITH_DEV=1 npm run build\n"
  );
  process.exit(1);
}

console.log(
  `[guard-build-vs-dev] No same-project dev server on port ${DEV_PORT} — safe to build.`
);
process.exit(0);
