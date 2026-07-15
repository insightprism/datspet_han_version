#!/usr/bin/env python3
"""Preflight: catch the bugs that ONLY exist in the static export.

Run before any deploy that ships web/ (deploy/README.md names it):

    scripts/preflight_static_export.py                 # build a throwaway export, check it
    scripts/preflight_static_export.py --export-dir web/out   # check an export you already built

WHY THIS EXISTS
───────────────
`next dev` and `output: "export"` are two different runtimes for identical source,
and dev is the forgiving one. Under `next dev` there is a Node server, so a page
that calls Next's `redirect()` performs a real server-side 307. The export has no
server: it emits an HTML file whose <body> renders NOTHING and whose hop rides a
`NEXT_REDIRECT;replace;/target;307;` payload inside a <script>, with no
meta-refresh. nginx serves that as a plain 200 — a blank page that redirects in JS
after a paint, and not at all for a client that runs no JS.

That shipped. `/design` — the DPP launch deep-link target, whose URL is registered
with the DatsMe host and is not ours to edit — was a blank page in the export while
being perfect in dev. It was found by hand, with curl, after deploying. No amount
of care in dev could have caught it, because dev is structurally incapable of
reproducing it. Hence a check that runs against the artifact that actually ships.

WHY THE CHECKS ARE STRUCTURAL, NOT HTTP
───────────────────────────────────────
The vhost ends in `try_files $uri $uri.html $uri/ /index.html`. That last fallback
means a MISSING route never 404s — nginx serves the landing page with a 200:

    $ curl -o /dev/null -w '%{http_code}' https://pet-staging.datsme.me/design/total-nonsense
    200

So "curl the route and assert 200" passes on a completely broken route. The only
honest question is whether a real file exists in the export, which is what
resolves_in_export() asks.

WHAT IT CHECKS
──────────────
1. Every blank-redirect shell in the export is covered by an nginx exact-match
   `location = /route { return 30x ...; }`. Generalised on purpose: the shells are
   DISCOVERED by scanning for the NEXT_REDIRECT payload and the target/status are
   read out of the payload itself, so a `redirect()` page added next year is caught
   without touching this file. Nothing here hardcodes /design.
2. Every nginx redirect lands somewhere real — both the shells' targets and the
   `return` targets resolve to an actual file. A 307 into the try_files catch-all
   is worse than no redirect: it looks like it works and silently serves the wrong
   page.
3. The catch-all itself resolves (index.html exists), since checks 1-2 lean on it.

Exit 0 = safe to deploy. Exit 1 = a real defect, with the fix spelled out.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
NGINX_CONF = REPO / "deploy" / "nginx-default.conf"

# Built into its OWN dist dir so this can run while a dev server is live: the
# dev/build hazard is a shared .next/, so a different one cannot collide.
# next.config.mjs maps DATSPET_DIST_DIR -> distDir and web/scripts/guard-build-vs-dev.js
# stands down for it. NOTE: with distDir set, `output: "export"` writes the static site
# INTO that directory instead of to web/out — so this dir IS the export, and a normal
# deploy build (no DATSPET_DIST_DIR) still lands in web/out, untouched by preflight runs.
PREFLIGHT_DIST = ".next-preflight"

# Ground truth, verified against a real 2026-07-15 export of this app. The shell is
# `<html id="__next_error__">` with an empty body; the hop is this payload, inside a
# <script>, and it names its own target and status:
#     4:E{"digest":"NEXT_REDIRECT;replace;/design/general;307;"}
NEXT_REDIRECT_RE = re.compile(r"NEXT_REDIRECT;(?P<kind>[a-z]+);(?P<target>[^;\\\"]+);(?P<status>\d+);")

# `location = /design {  return 307 /design/general$is_args$args;  }`
# Exact-match locations only: a prefix or regex location does NOT beat the
# `location /` static block reliably, and exact-match is the one nginx resolves
# first, before try_files ever sees the path.
LOCATION_EXACT_RE = re.compile(r"location\s*=\s*(?P<path>\S+)\s*\{(?P<body>[^}]*)\}", re.S)
RETURN_RE = re.compile(r"return\s+(?P<status>30[12378])\s+(?P<target>\S+?)\s*;")

# $is_args$args and friends are runtime nginx variables, not part of the path.
NGINX_VAR_RE = re.compile(r"\$\w+")


def log(msg=""):
    print(msg, flush=True)


def rel_to_repo(path):
    """Repo-relative for display, absolute if it lives outside (--nginx-conf can)."""
    try:
        return path.resolve().relative_to(REPO)
    except ValueError:
        return path


def build_export(api_url):
    """Build a throwaway static export and return the directory holding it."""
    dist = WEB / PREFLIGHT_DIST
    shutil.rmtree(dist, ignore_errors=True)

    env = {
        **os.environ,
        "DATSPET_STATIC_EXPORT": "1",
        "DATSPET_DIST_DIR": PREFLIGHT_DIST,
        # Structural checks don't depend on the origin, but the build demands one.
        "NEXT_PUBLIC_API_URL": api_url,
    }
    log(f"[preflight] building static export into web/{PREFLIGHT_DIST} …")
    proc = subprocess.run(
        ["npm", "run", "build"], cwd=WEB, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if proc.returncode != 0:
        log(proc.stdout)
        log("[preflight] FAIL: the export did not build.")
        log("  If this names a missing module, the box's node_modules has drifted:")
        log("    cd web && npm install")
        log("  (`next build` typechecks every .ts in the tree — including configs")
        log("   that `next dev` never loads, which is how vitest.config.ts broke a")
        log("   staging deploy on 2026-07-15.)")
        sys.exit(1)
    return dist


def resolves_in_export(export_dir, url_path):
    """Does `try_files $uri $uri.html $uri/` find a REAL file for this URL?

    Deliberately excludes the final `/index.html` fallback: that fallback is
    exactly what makes a broken route invisible (200 + the landing page), so
    treating it as success would defeat the check.
    """
    # An off-site redirect target is not ours to resolve — nginx hands it to the
    # browser and this export never serves it.
    if re.match(r"^(https?:)?//", url_path):
        return True
    rel = url_path.strip("/")
    if not rel:
        return (export_dir / "index.html").is_file()
    return any(
        p.is_file()
        for p in (export_dir / rel, export_dir / f"{rel}.html", export_dir / rel / "index.html")
    )


def find_redirect_shells(export_dir):
    """Every route the export renders as a blank JS-redirect page.

    Discovered by payload, not by name — a `redirect()` page added later is caught
    with no edit here.
    """
    shells = []
    for html in sorted(export_dir.rglob("*.html")):
        # _next/ is chunks and assets, never routes.
        if "_next" in html.parts:
            continue
        m = NEXT_REDIRECT_RE.search(html.read_text(encoding="utf-8", errors="replace"))
        if not m:
            continue
        # file -> URL. foo/bar.html -> /foo/bar; index.html -> /; foo/index.html -> /foo.
        rel = html.relative_to(export_dir).with_suffix("")
        if rel.name == "index":
            rel = rel.parent
        route = "/" if rel == Path(".") else "/" + str(rel)
        shells.append({
            "route": route,
            "kind": m.group("kind"),          # replace | push — how the client hop behaves
            "target": m.group("target"),
            "status": int(m.group("status")),
            "file": html.relative_to(export_dir),
        })
    return shells


def parse_nginx_redirects(conf_text):
    """{exact location path -> (status, target-with-nginx-vars-stripped)}"""
    out = {}
    for loc in LOCATION_EXACT_RE.finditer(conf_text):
        ret = RETURN_RE.search(loc.group("body"))
        if ret:
            target = NGINX_VAR_RE.sub("", ret.group("target"))
            out[loc.group("path")] = (int(ret.group("status")), target)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-dir", type=Path,
                    help="Check an export that already exists (e.g. web/out on the deploy box) "
                         "instead of building a throwaway one. Prefer this at deploy time: it "
                         "checks the artifact you are actually shipping.")
    ap.add_argument("--api-url", default="https://pet.datsme.me",
                    help="NEXT_PUBLIC_API_URL for the throwaway build (default: %(default)s).")
    ap.add_argument("--nginx-conf", type=Path, default=NGINX_CONF)
    args = ap.parse_args()

    export_dir = args.export_dir.resolve() if args.export_dir else build_export(args.api_url)
    if not export_dir.is_dir():
        log(f"[preflight] FAIL: no export at {export_dir}")
        return 1
    if not args.nginx_conf.is_file():
        log(f"[preflight] FAIL: no nginx conf at {args.nginx_conf}")
        return 1

    conf = args.nginx_conf.read_text()
    redirects = parse_nginx_redirects(conf)
    shells = find_redirect_shells(export_dir)
    failures = []

    log(f"\n[preflight] export   : {export_dir}")
    log(f"[preflight] vhost    : {rel_to_repo(args.nginx_conf)}")
    log(f"[preflight] redirects: {len(redirects)} exact-match location(s)")
    log(f"[preflight] shells   : {len(shells)} blank-redirect page(s) in the export\n")

    # 0. The catch-all every other check leans on.
    if not (export_dir / "index.html").is_file():
        failures.append("The export has no index.html — the try_files catch-all itself is broken.")

    # 1. Every blank shell must be intercepted by nginx before try_files sees it.
    for s in shells:
        covered = redirects.get(s["route"])
        if covered:
            # Coverage only — whether the TARGET is real is check 2's job, and saying
            # "OK → /gone" here would contradict the FAIL it is about to print.
            log(f"  OK    {s['route']:<24} blank shell intercepted by nginx {covered[0]}")
        else:
            log(f"  FAIL  {s['route']:<24} shell → NOT covered by nginx")
            failures.append(
                f"{s['route']} renders as a BLANK page in the export.\n"
                f"      {s['file']} has an empty <body>; its hop is a "
                f"NEXT_REDIRECT;{s['kind']};{s['target']};{s['status']} "
                f"payload that only runs after JS paints.\n"
                f"      nginx serves it as a plain 200. Under `next dev` this same source is a real\n"
                f"      server-side redirect, which is why it looks fine locally.\n"
                f"      FIX — add to {rel_to_repo(args.nginx_conf)}, above `location / {{`:\n"
                f"          location = {s['route']} {{\n"
                f"              return {s['status']} {s['target']}$is_args$args;\n"
                f"          }}"
            )

    # 2. Every redirect must land on something real — the shells' own targets and
    #    the vhost's. A 307 into the catch-all is a silent wrong-page 200.
    for route, (status, target) in sorted(redirects.items()):
        if not resolves_in_export(export_dir, target):
            log(f"  FAIL  {route:<24} nginx {status} → {target} (does not exist)")
            failures.append(
                f"{rel_to_repo(args.nginx_conf)} redirects {route} → {target}, but {target}\n"
                f"      does not exist in the export. nginx will NOT 404 — try_files falls through to\n"
                f"      /index.html, so the user gets the landing page with a 200 and no error anywhere.\n"
                f"      FIX: point the redirect at a route that exists, or restore {target}."
            )
    for s in shells:
        if not resolves_in_export(export_dir, s["target"]):
            failures.append(
                f"{s['route']} redirects to {s['target']}, which does not exist in the export.\n"
                f"      FIX: fix the redirect() target in web/src/app{s['route']}/page.tsx."
            )

    log()
    if failures:
        log(f"[preflight] FAILED — {len(failures)} problem(s) that dev cannot show you:\n")
        for i, f in enumerate(failures, 1):
            log(f"  {i}. {f}\n")
        return 1

    log("[preflight] PASSED — every blank-redirect shell is covered and every redirect lands on a real page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
