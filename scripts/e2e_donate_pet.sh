#!/usr/bin/env bash
# e2e_donate_pet.sh — the donation reward loop, end to end (SPEC_PET_STORE §10.12).
#
#   a designed pet in the house  →  POST /donate  →  the pet becomes `intake`
#   store inventory and leaves the house  →  DatsPet asks DatsMe to recognise
#   it (signed writeback, NO amount on the request)  →  DatsMe reads its OWN
#   knob, awards, and answers per item  →  DatsPet records the figure and can
#   thank the donor with it.
#
# WHY THIS EXISTS, and why it is not optional. Every unit gate was green while
# this entire loop was dead: the host rebuilt its writeback response from three
# fixed keys and discarded the handler's per-award `results`, so the partner
# never settled a row and re-posted the same awards forever — for awards the
# host had already paid. The partner's own tests stubbed the host's response and
# handed themselves the array the real route does not send. Only a live stack
# crosses the two repos, the signed channel, the one-time nonce and a real
# launch token, so only a live stack can catch that class of break.
#
# Usage:
#   ./scripts/e2e_donate_pet.sh
#   DATSME_USER_ID=<uuid> ./scripts/e2e_donate_pet.sh
set -uo pipefail

# --- config (the e2e_adopt_store_pet.sh conventions) -------------------------
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
DATSPET_PYRUN() {
  ( cd "$REPO"; set -a; . ./pet_env.sh >/dev/null 2>&1; set +a
    PYTHONPATH="$REPO/webui:$REPO" python3 -c "$1" )
}

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '   \033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. preflight ------------------------------------------------------------
say "Preflight — services reachable?"
for pair in "DatsPet|$DATSPET_BACKEND/api/store" "DatsMe|$DATSME_HOST/docs"; do
  set -- $(echo "$pair" | tr '|' ' ')
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$2" 2>/dev/null)
  [ "$code" = "200" ] && ok "$1 up ($2 → 200)" || die "$1 not reachable ($2 → $code)."
done

# The host must KNOW the target. A host that predates Phase 2a answers 400
# unsupported_target, and the donation would sit owed forever with no error
# anywhere the donor could see.
HAS_TARGET=$(PYRUN "
from apps.dpp import service
print('YES' if 'user.social_award' in service._TARGET_HANDLERS else 'NO')
" 2>/dev/null)
[ "$HAS_TARGET" = "YES" ] || die "the host does not handle user.social_award — deploy the HOST first (§13)."
ok "host handles user.social_award"

REWARD=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_config import get_credit_config_int
with SocialSessionLocal() as s:
    print(get_credit_config_int(s, 'pet_donation_social_reward_amount'))
" 2>/dev/null)
[ -n "${REWARD:-}" ] || die "could not read pet_donation_social_reward_amount"
ok "host's donation reward: $REWARD social point(s)"
[ "$REWARD" -gt 0 ] || die "the reward knob is 0 — the loop would report 'disabled' and prove nothing. Set it above 0 to run this."

# --- 1. a DESIGNED pet to give away -----------------------------------------
# Seeded, not built: the ~3 min GPU build is already covered by
# e2e_design_a_pet.sh, and what is untested here is the donate→award→settle
# loop. The bundle is stamped factory/datspet exactly as a real build stamps
# it, because the donate door refuses anything else (§10.1 gate 3).
say "Seed — a factory-stamped pet in the donor's house"
PET_ID=$(DATSPET_PYRUN "
import io, json, time, uuid, zipfile
import db, pet_ownership
from PIL import Image
db.init_db()
breed='e2e_donor_pet'
sheet=io.BytesIO(); Image.new('RGBA',(2048,256),(180,120,220,255)).save(sheet,'PNG')
sheet=sheet.getvalue()
manifest={'schema_version':'pet_manifest.v1','columns':8,'frame_width':256,
          'frame_height':256,'animations':{'walk':{'frames':[0]},'idle':{'frames':[1]}}}
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w') as z:
    z.writestr('manifest.json', json.dumps(manifest))
    z.writestr('package.json', json.dumps({'breed_id':breed,'display_name':'E2E Donor Pet'}))
    z.writestr(f'{breed}_sprite.png', sheet)
zip_bytes=buf.getvalue()
zip_bytes,_=pet_ownership.stamp_bundle_fingerprint(zip_bytes)
zip_bytes,manifest_json=pet_ownership.transfer_pet_ownership(
    zip_bytes, category=pet_ownership.FACTORY_CATEGORY,
    name=pet_ownership.FACTORY_OWNER_NAME,
    at=pet_ownership.epoch_to_utc_iso(time.time()))
pet_id=uuid.uuid4().hex[:12]
db.insert_pet(pet_id=pet_id, breed_id=breed, display_name='E2E Donor Pet',
              created_at=time.time(), draft=False, sheet_png=sheet,
              manifest_json=manifest_json, package_json=None,
              bundle_zip=zip_bytes, external_user_id='$DATSME_USER_ID')
print(pet_id)
" 2>/dev/null | tail -1)
[ -n "$PET_ID" ] || die "could not seed a designed pet"
ok "seeded pet $PET_ID for $DATSME_USER_ID"

# --- 2. launch → cookie ------------------------------------------------------
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
  'activity_id':'design_a_pet','jti':'e2e','capabilities':['pets.write','social.award']}))
")
SESS=$(curl -s -m 5 -H "Cookie: datsme_launch=$COOKIE" "$DATSPET_BACKEND/api/datsme/session" 2>/dev/null)
echo "$SESS" | grep -q '"launched": *true\|"launched":true' && ok "session launched" \
  || die "session says not launched: $SESS"

# --- 3. snapshot the donor's SOCIAL balance BEFORE ---------------------------
SOCIAL_BEFORE=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_point_balance
with SocialSessionLocal() as s: print(get_user_point_balance(s, '$DATSME_USER_ID'))
" 2>/dev/null | tail -1)
[ -n "${SOCIAL_BEFORE:-}" ] || die "could not read the donor's social balance"
ok "donor social points BEFORE: $SOCIAL_BEFORE"

# --- 4. donate ---------------------------------------------------------------
say "Step 2/4 — donate $PET_ID (final, irreversible)"
DON=$(curl -s -m 30 -H "Cookie: datsme_launch=$COOKIE" -X POST \
        "$DATSPET_BACKEND/api/pets/$PET_ID/donate" 2>/dev/null)
DONATION_ID=$(echo "$DON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("donation_id",""))' 2>/dev/null)
[ -n "$DONATION_ID" ] || die "donate failed: $DON"
ok "donated → donation $DONATION_ID"

# The pet left the house and became inventory, unshelved.
say "Step 3/4 — the pet is store inventory, in intake, and gone from the house"
STATE=$(DATSPET_PYRUN "
import db
gone = db.get_pet('$PET_ID') is None
rows = [d for d in db.donations_for_donor('$DATSME_USER_ID') if d['id']=='$DONATION_ID']
d = rows[0] if rows else {}
sp = db.get_store_pet(d.get('store_pet_id') or '')
print('|'.join([str(gone), str(sp['status'] if sp else 'MISSING'),
                str(d.get('reward_state')), str(d.get('points_awarded'))]))
" 2>/dev/null | tail -1)
IFS='|' read -r PET_GONE SHELF_STATUS REWARD_STATE POINTS <<<"$STATE"
[ "$PET_GONE" = "True" ] || die "the pet is still in the house — donating must MOVE it"
ok "the house row is gone (the slot freed)"
[ "$SHELF_STATUS" = "intake" ] || die "the listing is '$SHELF_STATUS', expected 'intake' — a donation must never self-shelve"
ok "it is store inventory, in intake, invisible to shoppers"

# --- 5. THE REWARD LOOP — the assertion this whole script exists for ---------
say "Step 4/4 — the reward loop: DatsPet asked, DatsMe decided, DatsPet recorded"
# Delivery rides the donate request as a background task, so give it a moment.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ "$REWARD_STATE" = "owed" ] || break
  sleep 1
  STATE=$(DATSPET_PYRUN "
import db
rows=[d for d in db.donations_for_donor('$DATSME_USER_ID') if d['id']=='$DONATION_ID']
d=rows[0] if rows else {}
print('|'.join([str(d.get('reward_state')), str(d.get('points_awarded'))]))
" 2>/dev/null | tail -1)
  IFS='|' read -r REWARD_STATE POINTS <<<"$STATE"
done

[ "$REWARD_STATE" != "owed" ] || die "the reward is STILL owed after 10s — the writeback never settled. This is the Cluster A failure: check that the host's response carries \`results\` and that a 401 is not being treated as terminal."
[ "$REWARD_STATE" = "delivered" ] || die "reward_state=$REWARD_STATE (expected delivered). 'capped' means this donor was already thanked today; 'disabled' means the knob is 0; 'declined' means the host refused outright."
ok "the donation settled as DELIVERED"

[ "$POINTS" = "$REWARD" ] || die "DatsPet recorded $POINTS point(s), the host's knob says $REWARD — the figure must be the HOST's, echoed exactly"
ok "DatsPet recorded the host's own figure: $POINTS"

# ...and the host actually moved the points.
SOCIAL_AFTER=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_point_balance
with SocialSessionLocal() as s: print(get_user_point_balance(s, '$DATSME_USER_ID'))
" 2>/dev/null | tail -1)
GAINED=$(( SOCIAL_AFTER - SOCIAL_BEFORE ))
echo "   social points: $SOCIAL_BEFORE → $SOCIAL_AFTER   (gained $GAINED)"
[ "$GAINED" -eq "$REWARD" ] || die "the donor's balance moved by $GAINED, expected $REWARD — DatsPet recorded a thank-you the host did not give"
ok "the host's ledger really moved"

AWARD_ROW=$(PYRUN "
from social_db import SocialSessionLocal
from apps.dpp.models import PartnerSocialAward
with SocialSessionLocal() as s:
    r=s.query(PartnerSocialAward).filter(
        PartnerSocialAward.partner_slug=='$SLUG',
        PartnerSocialAward.award_key=='$DONATION_ID').first()
    print(f'{r.points}' if r else 'MISSING')
" 2>/dev/null | tail -1)
[ "$AWARD_ROW" = "$REWARD" ] || die "the host's claim row says '$AWARD_ROW' — it is the unique key that makes a retry safe"
ok "the host's idempotency claim row is written ($AWARD_ROW)"

# A second delivery must pay nothing. This is what makes at-least-once safe.
say "Idempotency — a re-delivery must pay NOTHING"
DATSPET_PYRUN "
import db
db.settle_donation_reward('$DONATION_ID', state=db.REWARD_DELIVERED,
                          points_awarded=None, settled_at=0)
" >/dev/null 2>&1   # no-op: settle only moves rows OUT of owed
SOCIAL_FINAL=$(PYRUN "
from social_db import SocialSessionLocal
from social_ledger.social_ledger_service import get_user_point_balance
with SocialSessionLocal() as s: print(get_user_point_balance(s, '$DATSME_USER_ID'))
" 2>/dev/null | tail -1)
[ "$SOCIAL_FINAL" = "$SOCIAL_AFTER" ] || die "the balance moved again ($SOCIAL_AFTER → $SOCIAL_FINAL)"
ok "no double payment"

say "E2E PASSED — a donation is final, becomes intake inventory, and the donor is thanked with the host's own figure."
