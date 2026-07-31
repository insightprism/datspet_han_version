#!/usr/bin/env bash
# e2e_adopt_store_pet.sh — the Pet Store round-trip (SPEC_PET_STORE §12),
# exactly as the browser does it. The sibling of e2e_design_a_pet.sh with the
# ~3 min GPU build replaced by an instant store adopt — which is the product.
#
#   DatsMe mints a launch  →  DatsPet /launch (cookie)  →  adopt a published
#   store pet (zero GPU, instant)  →  claim + keep  →  the host quotes the FLAT
#   store price (price_basis=store_flat, never the pose formula)  →  binding
#   checkout  →  the pet appears in the DatsMe user's house.
#
# Verifies the RESULT in the DatsMe user's SQLite + credit ledger, and — the
# store-specific assertion — that the quote equals credit_pet_store_cost, not
# what the pose formula would have said.
#
# Usage:
#   ./scripts/e2e_adopt_store_pet.sh
#   DATSME_USER_ID=<uuid> ./scripts/e2e_adopt_store_pet.sh
set -uo pipefail

# --- config (the e2e_design_a_pet.sh conventions, see its comments) ----------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
die_early() { printf '   \033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
DATSME_API="${DATSME_API:-$REPO/../datsme_me/api}"
[ -d "$DATSME_API" ] || die_early "DATSME_API not found: $DATSME_API"
DATSME_API="$(cd "$DATSME_API" && pwd)"
DATSPET_BACKEND="${DATSPET_BACKEND:-http://127.0.0.1:19954}"
DATSME_HOST="${DATSME_HOST:-http://127.0.0.1:19994}"
DATSME_USER_ID="${DATSME_USER_ID:-5d8f6d64-5473-41c8-a709-5ed88c5ff850}"
SLUG="${DATSPET_SLUG:-datspet}"

DATSME_PY="${DATSME_PY:-}"
PYRUN() {
  local py="$DATSME_PY"
  [ -z "$py" ] && { [ -x "$DATSME_API/venv/bin/python" ] && py="$DATSME_API/venv/bin/python" || py=python3; }
  ( cd "$DATSME_API"; set -a; . .env 2>/dev/null; set +a
    PYTHONPATH="$DATSME_API/sdk:$DATSME_API" "$py" -c "$1" )
}

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '   \033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. preflight — no ComfyUI check: a store adopt burns no GPU anywhere ----
say "Preflight — services reachable?"
for pair in "DatsPet|$DATSPET_BACKEND/api/store" "DatsMe|$DATSME_HOST/docs"; do
  set -- $(echo "$pair" | tr '|' ' ')
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$2" 2>/dev/null)
  [ "$code" = "200" ] && ok "$1 up ($2 → 200)" || die "$1 not reachable ($2 → $code). Start it first."
done
sig=$(curl -s -m 5 -D - -o /dev/null "$DATSPET_BACKEND/partner/manifest" 2>/dev/null | grep -ci "x-datsme-signature")
[ "$sig" -ge 1 ] && ok "DatsPet manifest is signed" \
  || die "DatsPet manifest is NOT signed — DATSME_HMAC_SECRET missing."

# --- 1. the shelf must be stocked (the §8 migration or the store admin) ------
say "Shelf — a published store pet to adopt"
STORE_ID=$(curl -s -m 10 "$DATSPET_BACKEND/api/store" 2>/dev/null | python3 -c '
import sys, json
pets = json.load(sys.stdin).get("pets", [])
print(pets[0]["id"] if pets else "")')
[ -n "$STORE_ID" ] || die "the store is EMPTY — run scripts/migrate_samples_to_store.py or stock via /admin/store"
ok "will adopt store pet $STORE_ID"

# The host's flat store price — what the quote MUST equal (§7).
STORE_COST=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_config import get_credit_config_int
with SocialSessionLocal() as s:
    print(get_credit_config_int(s, 'credit_pet_store_cost'))
")
[ -n "${STORE_COST:-}" ] || die "could not read credit_pet_store_cost from the host"
ok "host's flat store price: $STORE_COST credits"

# --- 2. snapshot BEFORE ------------------------------------------------------
say "Snapshot — the DatsMe user's house + credits BEFORE"
read -r BAL_BEFORE PETS_BEFORE <<<"$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_credit_balance
from user_db import open_user_database
from apps.pets.pet_models import Pet
uid='$DATSME_USER_ID'
with SocialSessionLocal() as s: bal=get_user_credit_balance(s, uid)
d=open_user_database(uid); n=len([p for p in d.query(Pet).all() if (p.source or '').startswith('partner')]); d.close()
print(bal, n)
")"
[ -n "${BAL_BEFORE:-}" ] || die "Could not read the DatsMe user ($DATSME_USER_ID)"
ok "balance=$BAL_BEFORE, partner-pets=$PETS_BEFORE"

# --- 3. launch → cookie (identical to e2e_design_a_pet.sh) -------------------
say "Step 1/4 — DatsMe mints a launch, DatsPet /launch sets the cookie"
LAUNCH_URL=$(PYRUN "
from social_db import SocialSessionLocal
from social_models import User
from apps.dpp import service
with SocialSessionLocal() as db:
    u=db.query(User).filter(User.id=='$DATSME_USER_ID').first()
    r=service.mint_launch_token(db,u,'design_a_pet','$SLUG'); db.commit()
    print(r['launch_url'])
")
case "$LAUNCH_URL" in http*) ok "launch minted" ;; *) die "mint failed: $LAUNCH_URL" ;; esac
curl -s -m 10 -o /dev/null "$LAUNCH_URL" 2>/dev/null
TOKEN="${LAUNCH_URL##*token=}"
COOKIE=$(python3 -c "
import json
print(json.dumps({'token':'$TOKEN','user_id':'$DATSME_USER_ID',
  'activity_id':'design_a_pet','jti':'e2e','capabilities':['pets.write']}))
")
SESS=$(curl -s -m 5 -H "Cookie: datsme_launch=$COOKIE" "$DATSPET_BACKEND/api/datsme/session" 2>/dev/null)
echo "$SESS" | grep -q '"launched": *true\|"launched":true' && ok "session launched" \
  || die "session says not launched: $SESS"

# --- 4. adopt from the store (instant — this replaces the 3-min build) -------
say "Step 2/4 — adopt store pet $STORE_ID (instant, zero GPU)"
ADOPTED=$(curl -s -m 20 -H "Cookie: datsme_launch=$COOKIE" -X POST \
        "$DATSPET_BACKEND/api/store/$STORE_ID/adopt" 2>/dev/null)
PET_ID=$(echo "$ADOPTED" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("pet_id",""))' 2>/dev/null)
[ -n "$PET_ID" ] || die "store adopt failed: $ADOPTED"
ok "adopted → draft pet $PET_ID in the user's DatsPet house"

# --- 5. claim + keep, then the host quote — the store assertion --------------
say "Step 3/4 — claim + keep, then the host must quote the FLAT store price"
curl -s -m 20 -H "Cookie: datsme_launch=$COOKIE" -X POST -H "Content-Type: application/json" \
     -d "{\"pet_ids\":[\"$PET_ID\"]}" "$DATSPET_BACKEND/api/pets/claim" >/dev/null 2>&1
KEPT=$(curl -s -m 20 -H "Cookie: datsme_launch=$COOKIE" -X POST \
        "$DATSPET_BACKEND/api/pets/$PET_ID/keep" 2>/dev/null)
echo "$KEPT" | grep -q '"id"' || die "keep failed: $KEPT"

HOST_JAR="$(mktemp -t datspet_e2e_host.XXXXXX)"
trap 'rm -f "$HOST_JAR"' EXIT
HOST_TOKEN=$(PYRUN "
from social_db import SocialSessionLocal
from social_models import User
from session_store import create_user_session
class _Req:
    headers = {'user-agent': 'e2e'}
    client = None
with SocialSessionLocal() as db:
    u = db.query(User).filter(User.id=='$DATSME_USER_ID').first()
    print(create_user_session(db, u, _Req()))
    db.commit()
" 2>/dev/null | tail -1)
[ -z "$HOST_TOKEN" ] && die "could not mint a host session"
HOST_DOMAIN=$(echo "$DATSME_HOST" | sed -E 's#https?://##; s#:.*##')
printf '%s\tFALSE\t/\tFALSE\t0\ttoken\t%s\n' "$HOST_DOMAIN" "$HOST_TOKEN" > "$HOST_JAR"

QUOTE=$(curl -s -m 30 -b "$HOST_JAR" "$DATSME_HOST/api/integrations/import/datspet" 2>/dev/null)
CREDITS=$(echo "$QUOTE" | python3 -c "
import sys,json
items=[i for e in json.load(sys.stdin).get('exports',[]) for i in e.get('items',[])]
m=[i for i in items if i['id']=='$PET_ID']
print(m[0]['credits'] if m else 'MISSING')" 2>/dev/null)
[ "$CREDITS" = "MISSING" ] && die "the host does not offer this pet — check the transfer block"
# THE store assertion (§7): flat knob, not the pose formula. A store pet with
# 8 poses priced per-pose would quote 110 — seeing $STORE_COST proves the
# declared price_basis=store_flat travelled export → quote intact.
[ "$CREDITS" = "$STORE_COST" ] \
  && ok "host quotes $CREDITS = credit_pet_store_cost (store_flat lane works)" \
  || die "host quotes $CREDITS but the flat store price is $STORE_COST — price_basis lost between export and quote"

# --- 6. binding checkout + verify --------------------------------------------
say "Step 4/4 — binding checkout, then verify in the host's own DB"
SHA=$(echo "$QUOTE" | python3 -c "
import sys,json
items=[i for e in json.load(sys.stdin).get('exports',[]) for i in e.get('items',[])]
print([i for i in items if i['id']=='$PET_ID'][0].get('sha256',''))" 2>/dev/null)
IMP=$(curl -s -m 120 -b "$HOST_JAR" -X POST -H "Content-Type: application/json" \
      -d "{\"export_type\":\"pets\",\"items\":[{\"id\":\"$PET_ID\",\"sha256\":\"$SHA\",\"quoted_credits\":$CREDITS}]}" \
      "$DATSME_HOST/api/integrations/import/datspet" 2>/dev/null)
echo "$IMP" | grep -q '"imported"' || die "checkout failed: $IMP"
ok "checkout charged $(echo "$IMP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("credits_charged","?"))') credits"

read -r BAL_AFTER PETS_AFTER <<<"$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_credit_balance
from user_db import open_user_database
from apps.pets.pet_models import Pet
uid='$DATSME_USER_ID'
with SocialSessionLocal() as s: bal=get_user_credit_balance(s, uid)
d=open_user_database(uid); n=len([p for p in d.query(Pet).all() if (p.source or '').startswith('partner')]); d.close()
print(bal, n)
")"
CHARGED=$(( BAL_BEFORE - BAL_AFTER ))
GAINED=$(( PETS_AFTER - PETS_BEFORE ))
echo "   partner-pets: $PETS_BEFORE → $PETS_AFTER   (gained $GAINED)"
echo "   credits:      $BAL_BEFORE → $BAL_AFTER   (charged $CHARGED)"
[ "$GAINED" -ge 1 ] || die "NO new partner pet appeared in the DatsMe house"
ok "the store pet is in the DatsMe user's house"

say "E2E PASSED — the Pet Store round trip works, priced by the flat store lane."
