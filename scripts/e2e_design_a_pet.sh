#!/usr/bin/env bash
# e2e_design_a_pet.sh — full DPP round-trip, exactly as the browser does it.
#
#   DatsMe mints a launch  →  DatsPet /launch (cookie)  →  design/generate a REAL
#   pet (GPU, ~3 min)  →  Accept  →  the pet appears in the DatsMe user's house.
#
# Verifies the RESULT in the DatsMe user's SQLite + credit ledger, not just HTTP
# responses. Run this before the manual browser test to catch a broken stack.
#
# Usage:
#   ./scripts/e2e_design_a_pet.sh                 # designs for markly.1
#   DATSME_USER_ID=<uuid> ./scripts/e2e_design_a_pet.sh
#   PET_TEXT="an owl" PET_COLOR="purple" ./scripts/e2e_design_a_pet.sh
set -uo pipefail

# --- config -----------------------------------------------------------------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATSME_API="$(cd "$REPO/../datsme_me/api" && pwd)"
DATSPET_BACKEND="${DATSPET_BACKEND:-http://127.0.0.1:19954}"
DATSME_HOST="${DATSME_HOST:-http://127.0.0.1:19994}"
COMFY_URL="${PET_FACTORY_COMFY_URL:-http://127.0.0.1:19953}"
# markly.1 (display_name=markly, wu@insightprism.com). Override for another user.
DATSME_USER_ID="${DATSME_USER_ID:-5d8f6d64-5473-41c8-a709-5ed88c5ff850}"
# PET_TEXT names the ANIMAL — step 1's only input (SPEC_PET_DESIGNER_FLOW §0.1). It used
# to default to "a friendly green turtle", which baked a COLOUR into what is now the
# archetype prompt: step 1 draws what a typical turtle looks like, and green is step 2's
# business. PET_COLOR carries the design instead. The split is the spec's central rule,
# so the E2E should demonstrate it rather than quietly violate it.
PET_TEXT="${PET_TEXT:-a friendly turtle}"
PET_COLOR="${PET_COLOR:-green}"
SLUG="${DATSPET_SLUG:-datspet}"

JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

# host python with SDK + api on the path (for mint + DB reads)
PYRUN() {
  ( cd "$DATSME_API" && set -a && . .env 2>/dev/null && set +a \
    && PYTHONPATH="$DATSME_API/sdk:$DATSME_API" python3 -c "$1" )
}

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '   \033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. preflight -----------------------------------------------------------
say "Preflight — services reachable?"
for pair in "ComfyUI $COMFY_URL/system_stats" "DatsPet $DATSPET_BACKEND/api/pets" "DatsMe $DATSME_HOST/docs"; do
  set -- $pair
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$2" 2>/dev/null)
  [ "$code" = "200" ] && ok "$1 up ($2 → 200)" || die "$1 not reachable ($2 → $code). Start it first."
done
sig=$(curl -s -m 5 -D - -o /dev/null "$DATSPET_BACKEND/partner/manifest" 2>/dev/null | grep -ci "x-datsme-signature")
[ "$sig" -ge 1 ] && ok "DatsPet manifest is signed (DATSME_HMAC_SECRET is set)" \
  || die "DatsPet manifest is NOT signed — DATSME_HMAC_SECRET missing. Restart the backend after sourcing pet_env.sh."

# --- 1. snapshot BEFORE -----------------------------------------------------
say "Snapshot — the DatsMe user's house + credits BEFORE"
read -r BAL_BEFORE PETS_BEFORE <<<"$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_credit_balance
from user_db import open_user_database
from apps.pets.pet_models import Pet
uid='$DATSME_USER_ID'
with SocialSessionLocal() as s: bal=get_user_credit_balance(s, uid)
d=open_user_database(uid); n=len([p for p in d.query(Pet).all() if p.source=='partner']); d.close()
print(bal, n)
")"
[ -n "${BAL_BEFORE:-}" ] || die "Could not read the DatsMe user — is the user id right? ($DATSME_USER_ID)"
ok "balance=$BAL_BEFORE, partner-pets=$PETS_BEFORE"

# --- 2. DatsMe mints a launch (the 'Design a pet' button) -------------------
say "Step 1/6 — DatsMe mints a launch token for '$SLUG' (the Design-a-pet button)"
LAUNCH_URL=$(PYRUN "
from social_db import SocialSessionLocal
from social_models import User
from apps.dpp import service
with SocialSessionLocal() as db:
    u=db.query(User).filter(User.id=='$DATSME_USER_ID').first()
    r=service.mint_launch_token(db,u,'design_a_pet','$SLUG'); db.commit()
    print(r['launch_url'])
")
case "$LAUNCH_URL" in
  http*) ok "launch minted: ${LAUNCH_URL:0:60}…" ;;
  *) die "mint failed: $LAUNCH_URL  (grant pets.write consent for this user first, or check the partner is active)";;
esac

# --- 3. follow the launch into DatsPet (sets the cookie) --------------------
say "Step 2/6 — browser follows the launch → DatsPet /launch verifies + sets the cookie"
# Exercise the REAL /launch endpoint: it must verify the token, emit a
# SameSite=None; Secure cookie, and 303 to the design page.
HDRS=$(curl -s -m 10 -D - -o /dev/null "$LAUNCH_URL" 2>/dev/null)
echo "$HDRS" | grep -qi "^location:.*\/design?from=datsme" || die "/launch did not 303 to the design page"
echo "$HDRS" | grep -qi "set-cookie:.*datsme_launch" || die "/launch did not set the datsme_launch cookie"
echo "$HDRS" | grep -qi "samesite=none; *secure" || die "cookie is not SameSite=None; Secure (Accept button would never show)"
ok "/launch verified token, set SameSite=None;Secure cookie, 303→/design"

# For the subsequent authenticated calls we build the cookie value the SAME way
# /launch does. This is NOT a shortcut around the flow: curl over plain http
# refuses to store or replay a Secure cookie (a browser treats localhost as a
# secure context and does; curl doesn't), so we can't use curl's own jar here.
TOKEN="${LAUNCH_URL##*token=}"
COOKIE=$(python3 -c "
import json
print(json.dumps({'token':'$TOKEN','user_id':'$DATSME_USER_ID',
  'activity_id':'design_a_pet','jti':'e2e','capabilities':['pets.write']}))
")
SESS=$(curl -s -m 5 -H "Cookie: datsme_launch=$COOKIE" "$DATSPET_BACKEND/api/datsme/session" 2>/dev/null)
echo "$SESS" | grep -q '"launched": *true\|"launched":true' && ok "session: launched=true ($SESS)" \
  || die "session says not launched: $SESS"

# --- 4. design + generate a REAL pet (GPU) ----------------------------------
# Walks the REAL three-step flow (SPEC_PET_DESIGNER_FLOW): an archetype, a design, an
# animation. It used to POST `text=` straight at /api/generate — a field that no longer
# exists. Generate takes ONE base field now, so a round-trip test has to earn it, which
# is the contract working rather than ceremony. It also means this script now exercises
# /api/reference and /api/preview, which it never did before.
# -m 200, not 60: a warm redraw is ~10 s, but BOTH of these render server-side through
# pool_client.run_to_result(timeout_s=180) (app.py) — and a COLD pool worker has to load
# Z-Image first, which is exactly why nginx allows proxy_read_timeout 300 for /api/preview
# and why pet_preview's own handler budget is 180 s. A 60 s client ceiling under a 180 s
# server budget fails the run on the slowest legitimate case and blames the endpoint for
# the script's own impatience. Stay above the server's budget so a timeout here means the
# SERVER gave up, which is a real failure worth reporting.
say "Step 3/6 — draw the base animal: \"$PET_TEXT\"  (~10 s warm, up to ~3 min cold)"
REF=$(curl -s -m 200 -H "Cookie: datsme_launch=$COOKIE" -X POST "$DATSPET_BACKEND/api/reference" \
        -F "animal=$PET_TEXT" 2>/dev/null \
        | python3 -c 'import sys,json;print(json.load(sys.stdin).get("reference_id",""))' 2>/dev/null)
[ -n "$REF" ] || die "/api/reference did not return a reference_id"
ok "archetype drawn: $REF"

# A design is REQUIRED (§4.1) — designing nothing is what adopt-a-sample is for — so the
# preview needs at least one modifier. Preview returns a NEW reference (§6.1): the design
# made visible, and the still the build will animate as-is.
say "Step 4/6 — preview the design: $PET_COLOR  (~10 s warm)"
PREV=$(curl -s -m 200 -H "Cookie: datsme_launch=$COOKIE" -X POST "$DATSPET_BACKEND/api/preview" \
        -F "reference_id=$REF" -F "color=$PET_COLOR" 2>/dev/null \
        | python3 -c 'import sys,json;print(json.load(sys.stdin).get("reference_id",""))' 2>/dev/null)
[ -n "$PREV" ] || die "/api/preview did not return a reference_id"
ok "preview drawn: $PREV"

say "Step 5/6 — generate the pet from the previewed still  (GPU build, ~3 min)"
JOB=$(curl -s -m 20 -H "Cookie: datsme_launch=$COOKIE" -X POST "$DATSPET_BACKEND/api/generate" \
        -F "reference_id=$PREV" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("job_id",""))' 2>/dev/null)
[ -n "$JOB" ] || die "generate did not return a job_id"
ok "job started: $JOB — polling…"
DEADLINE=$(( $(date +%s) + 420 ))   # 7 min ceiling
while :; do
  J=$(curl -s -m 8 "$DATSPET_BACKEND/api/job/$JOB" 2>/dev/null)
  STAT=$(echo "$J" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
  PROG=$(echo "$J" | python3 -c 'import sys,json;print(round(json.load(sys.stdin).get("progress",0)*100))' 2>/dev/null)
  MSG=$(echo "$J"  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("message","")[:44])' 2>/dev/null)
  case "$STAT" in
    done)  ok "generation DONE (100%)"; break ;;
    error) die "generation FAILED: $MSG" ;;
    *)     printf '\r      %s %s%% — %-44s' "${STAT:-?}" "${PROG:-0}" "$MSG" ;;
  esac
  [ "$(date +%s)" -ge "$DEADLINE" ] && { echo; die "generation timed out after 7 min"; }
  sleep 5
done
echo

# --- 5. Accept → writeback → host fetches + adopts --------------------------
say "Step 6/6 — Accept: DatsPet posts the writeback; DatsMe fetches the bundle + adopts"
ACC=$(curl -s -m 90 -H "Cookie: datsme_launch=$COOKIE" -X POST -H "Content-Type: application/json" \
        -d "{\"pet_id\":\"$JOB\"}" "$DATSPET_BACKEND/api/datsme/accept" 2>/dev/null)
if echo "$ACC" | grep -q '"redirect_url"'; then
  ok "Accept OK → redirect: $(echo "$ACC" | python3 -c 'import sys,json;print(json.load(sys.stdin)["redirect_url"])')"
elif echo "$ACC" | grep -q '"queued":true\|"queued": true'; then
  die "Accept was QUEUED (host unreachable at write time): $ACC"
else
  die "Accept failed: $ACC"
fi

# --- 6. verify the RESULT in the DatsMe user's DB ---------------------------
say "Verify — in the DatsMe user's SQLite + ledger (not just HTTP)"
RESULT=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_credit_balance
from user_db import open_user_database
from apps.pets.pet_models import Pet
uid='$DATSME_USER_ID'
with SocialSessionLocal() as s: bal=get_user_credit_balance(s, uid)
d=open_user_database(uid)
partner=[p for p in d.query(Pet).all() if p.source=='partner']
newest=max(partner, key=lambda p: p.slot_index) if partner else None
d.close()
print(bal, len(partner), (newest.name if newest else ''), (newest.breed_id if newest else ''))
")
read -r BAL_AFTER PETS_AFTER NEW_NAME NEW_BREED <<<"$RESULT"

CHARGED=$(( BAL_BEFORE - BAL_AFTER ))
GAINED=$(( PETS_AFTER - PETS_BEFORE ))
echo "   partner-pets: $PETS_BEFORE → $PETS_AFTER   (gained $GAINED)"
echo "   credits:      $BAL_BEFORE → $BAL_AFTER   (charged $CHARGED)"
echo "   newest pet:   '$NEW_NAME'  ($NEW_BREED)"
echo
[ "$GAINED" -ge 1 ] || die "NO new partner pet appeared in the DatsMe house"
ok "a new source=partner pet is in the DatsMe user's house"
[ "$CHARGED" -gt 0 ] && ok "credits were charged ($CHARGED)" \
  || printf '   \033[1;33m! credits unchanged (cost may be 0, or auto-refill absorbed it)\033[0m\n'

say "E2E PASSED — the round trip works end to end. Safe to do the manual browser test."
