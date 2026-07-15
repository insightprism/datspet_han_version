#!/usr/bin/env bash
# verify_deployment.sh — prove a DEPLOYED DatsPet actually works, by using it.
#
#   scripts/verify_deployment.sh https://pet-staging.datsme.me
#   scripts/verify_deployment.sh https://pet.datsme.me --expect-max-poses 5
#   scripts/verify_deployment.sh https://pet.datsme.me --skip-gpu     # ~5 s surface only
#
# WHY THIS EXISTS (deploy/CHECKLIST.md §E has the full incident list)
# ------------------------------------------------------------------
# The 2026-07-15 designer deploy produced nine distinct failures. Every one was a
# FALSE GREEN — a check that passed while the thing it named was broken:
#
#   the fleet gate was green        while 100% of jobs died   (it tested a schema,
#                                                              not the runtime)
#   pool-install-handler said       while the restart had failed
#     "restarted"
#   every curl said 307             while real browsers saw a deleted page
#   dev rendered /design perfectly  while prod served it blank
#
# The pattern: we kept testing a PROXY for the thing instead of the thing. So this
# script's rule is: no check passes on a status code alone where the real behaviour
# can be exercised instead. It submits real jobs to the real pool, because a fleet
# where every job dies cannot survive a check that submits a job.
#
# Exit 0 = the deploy is good. Non-zero = do not walk away; see the FAILED lines.
set -uo pipefail

BASE="${1:-}"
[ -z "$BASE" ] && { echo "usage: $0 <base-url> [--expect-max-poses N] [--skip-gpu]"; exit 2; }
shift

EXPECT_MAX_POSES=""
SKIP_GPU=0
while [ $# -gt 0 ]; do
  case "$1" in
    --expect-max-poses) EXPECT_MAX_POSES="$2"; shift 2 ;;
    --skip-gpu) SKIP_GPU=1; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

PASS=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
note() { printf '        %s\n' "$1"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

jget() { python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))" 2>/dev/null; }

echo "=============================================================="
echo " verify_deployment  ->  $BASE"
echo "=============================================================="

# ---------------------------------------------------------------- surface
hdr "1. Backend"
H=$(curl -s -m 15 "$BASE/api/health")
[ "$(echo "$H" | jget status)" = "ok" ] && ok "/api/health -> ok" || { bad "/api/health not ok"; note "got: ${H:0:120}"; }
WS=$(echo "$H" | python3 -c "import sys,json;print(json.load(sys.stdin).get('workshop',{}).get('online',''))" 2>/dev/null)
if [ "$(echo "$H" | jget backend)" = "pool" ]; then
  [ "$WS" = "True" ] && ok "pool workshop online" || bad "pool workshop OFFLINE — generation will 423"
fi

hdr "2. The DPP deep link  (/design is registered with the DatsMe host; not ours to edit)"
# MUST be a real server-side 307. The static export renders /design as a BLANK page
# whose redirect only runs after JS paints — nginx must intercept it first.
# 2026-07-15: this shipped to staging as a blank page.
CODE=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$BASE/design")
LOC=$(curl -s -o /dev/null -m 15 -w '%{redirect_url}' "$BASE/design")
if [ "$CODE" = "307" ] && [ "${LOC%%\?*}" = "$BASE/design/general" ]; then
  ok "/design -> 307 -> /design/general (real, server-side)"
else
  bad "/design -> $CODE (want 307)"
  note "A 200 here means nginx is serving the blank export shell. Add to the vhost:"
  note "    location = /design { return 307 /design/general\$is_args\$args; }"
fi
# The host launches with ?from=datsme — the query must survive ($is_args$args).
QLOC=$(curl -s -o /dev/null -m 15 -w '%{redirect_url}' "$BASE/design?from=datsme")
case "$QLOC" in
  *from=datsme) ok "/design?from=datsme keeps its query" ;;
  *) bad "launch query DROPPED: $QLOC"; note "vhost is missing \$is_args\$args" ;;
esac

hdr "3. The designer renders"
# NOT a status check: try_files falls back to /index.html, so a MISSING route still
# answers 200 with the landing page. Only content proves the route exists.
BODY=$(curl -s -m 15 "$BASE/design/general")
echo "$BODY" | grep -q "Select the Animal to Design" \
  && ok "/design/general serves the three-step designer" \
  || { bad "/design/general is NOT the designer"; note "200 here proves nothing — try_files serves index.html for missing routes"; }

hdr "4. Caching  (a correct deploy can still serve a deleted page)"
# 2026-07-15: HTML went out with Last-Modified+ETag and NO Cache-Control. That does
# not mean "always revalidate" — caches may apply a HEURISTIC lifetime (RFC 9111
# §4.2.2), so users kept a deleted page for hours while every curl said 307.
CC=$(curl -s -D - -o /dev/null -m 15 "$BASE/design/general" | grep -i '^cache-control:' | tr -d '\r' | cut -d' ' -f2-)
case "$CC" in
  *no-cache*|*no-store*|*max-age=0*) ok "HTML revalidates (cache-control: $CC)" ;;
  "") bad "HTML has NO Cache-Control — browsers will heuristically cache a stale page" ;;
  *) bad "HTML cache-control is '$CC' — must revalidate" ;;
esac
ET=$(curl -s -D - -o /dev/null -m 15 "$BASE/design/general" | grep -i '^etag:' | tr -d '\r' | cut -d' ' -f2)
if [ -n "$ET" ]; then
  RC=$(curl -s -o /dev/null -m 15 -w '%{http_code}' -H "If-None-Match: $ET" "$BASE/design/general")
  [ "$RC" = "304" ] && ok "revalidation is cheap (If-None-Match -> 304)" || bad "ETag present but revalidation returned $RC (want 304)"
fi
ASSET=$(echo "$BODY" | grep -o '/_next/static/[^"]*\.js' | head -1)
if [ -n "$ASSET" ]; then
  ACC=$(curl -s -D - -o /dev/null -m 15 "$BASE$ASSET" | grep -i '^cache-control:' | tr -d '\r')
  case "$ACC" in *immutable*) ok "hashed assets are immutable" ;; *) bad "hashed assets not immutable ($ACC) — needless revalidation every load" ;; esac
fi

hdr "5. Entitlement  (this is what every user gets — default_tier is 'plus')"
E=$(curl -s -m 15 "$BASE/api/entitlement")
MP=$(echo "$E" | jget max_poses)
if [ -n "$EXPECT_MAX_POSES" ]; then
  [ "$MP" = "$EXPECT_MAX_POSES" ] && ok "max_poses = $MP (as expected)" \
    || { bad "max_poses = $MP, EXPECTED $EXPECT_MAX_POSES"; note "4cf7961 once set this to 10 for testing; shipping that charges 100+8x50=500 credits"; }
else
  note "max_poses = $MP  (pass --expect-max-poses to assert)"
fi
[ -n "$(curl -s -m 15 "$BASE/api/body-shapes" | jget shapes)" ] && ok "/api/body-shapes serves content" || bad "/api/body-shapes empty/missing"

# ---------------------------------------------------------------- the real thing
if [ "$SKIP_GPU" = "1" ]; then
  hdr "6. GPU doors — SKIPPED (--skip-gpu)"
  note "WARNING: the surface can be perfect while every job dies. The 2026-07-15"
  note "fleet gate was green for exactly this reason. Do not skip before a launch."
else
  hdr "6. The three doors — REAL jobs on the REAL pool (this is the part that matters)"
  R=$(curl -s -m 30 -X POST "$BASE/api/reference" -F "catalog_animal=dog" -F "catalog_breed=corgi")
  RID=$(echo "$R" | jget reference_id)
  if [ -n "$RID" ]; then
    ok "door 1 — curated base -> $RID (free, no pool call)"
    PC=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$BASE/api/reference/$RID.png")
    [ "$PC" = "200" ] && ok "reference image serves (200)" || bad "reference png -> $PC"
  else
    bad "door 1 — curated base FAILED"; note "got: ${R:0:140}"
  fi

  # The door that needs pet_preview v2 + the engine change on EVERY node. A stale
  # node kills 100% of these while the dispatcher's schema check stays green.
  T=$(curl -s -m 120 -X POST "$BASE/api/reference" -F "animal=a blue jay")
  TN=$(echo "$T" | jget display_name)
  [ -n "$TN" ] && ok "door 2 — typed animal -> \"$TN\" (fleet is v2 + engine)" \
    || { bad "door 2 — typed animal FAILED (the fleet-rollout canary)"; note "got: ${T:0:140}"; }

  if [ -n "$RID" ]; then
    P=$(curl -s -m 120 -X POST "$BASE/api/preview" -F "reference_id=$RID" -F "color=purple" -F "body_shape=fat")
    PN=$(echo "$P" | jget display_name)
    [ -n "$PN" ] && ok "step 2 — preview -> \"$PN\" (img2img)" \
      || { bad "step 2 — preview FAILED"; note "got: ${P:0:140}"; }
  fi
fi

echo
echo "=============================================================="
printf ' %s: \033[32m%d passed\033[0m, \033[31m%d failed\033[0m\n' "$BASE" "$PASS" "$FAIL"
echo "=============================================================="
[ "$FAIL" -gt 0 ] && { echo " DEPLOY IS NOT VERIFIED. Fix the FAILs above or roll back."; exit 1; }
echo " Verified."
exit 0
