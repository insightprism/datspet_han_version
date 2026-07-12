#!/usr/bin/env bash
# register_datspet.sh — register DatsPet as a DatsMe partner app (DPP Phase 3).
#
# This is the ONE live step of the DPP integration: it writes a PartnerApp row
# into DatsMe's Postgres and prints an HMAC secret ONCE. Everything before this
# (Phases 0–2) is code + local verification; this is the handshake that turns
# the two services into a connected partner.
#
# WHAT IT DOES
#   1. Loads DatsMe's DATABASE_URL from datsme_me/api/.env.
#   2. Runs datsme_me/api/scripts/register_partner_app.py, which:
#        - probes DatsPet's live /partner/manifest, /partner/export/{id},
#          /partner/revoke (all must be reachable and, for the manifest, signed)
#        - on success, inserts the partner row and PRINTS THE HMAC SECRET ONCE.
#
# PREREQUISITES (see docs/RUNBOOK_DPP_E2E.md for the full walkthrough)
#   - DatsPet backend running and reachable at $DATSPET_PUBLIC_URL, with a
#     TEMPORARY DATSME_HMAC_SECRET set so the manifest endpoint signs (the probe
#     needs a signed manifest; you replace this with the real secret afterward).
#   - DatsMe's Postgres up (default localhost:19993).
#
# USAGE
#   ./scripts/register_datspet.sh            # uses the URLs below
#   DATSPET_PUBLIC_URL=https://pets.datsme.me ./scripts/register_datspet.sh
#
# After it prints the secret: paste it into pet_env.local.sh (gitignored) as
# DATSME_HMAC_SECRET, restart the DatsPet backend, and run the E2E in
# docs/RUNBOOK_DPP_E2E.md.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATSME_API="${DATSME_API:-$(cd "$REPO/../datsme_me/api" && pwd)}"

SLUG="${DATSPET_SLUG:-datspet}"
NAME="${DATSPET_NAME:-DatsPet}"
DATSPET_PUBLIC_URL="${DATSPET_PUBLIC_URL:-http://localhost:19954}"
TIER="${DATSPET_TIER:-community}"

LAUNCH_BASE="$DATSPET_PUBLIC_URL/launch"
MANIFEST_URL="$DATSPET_PUBLIC_URL/partner/manifest"

echo "==> Registering partner '$SLUG' ($NAME)"
echo "    launch-base:  $LAUNCH_BASE"
echo "    manifest-url: $MANIFEST_URL"
echo "    tier:         $TIER"
echo "    DatsMe api:   $DATSME_API"
echo

# Load DatsMe's DATABASE_URL (and anything else the register script needs).
if [ -z "${DATABASE_URL:-}" ]; then
  if [ -f "$DATSME_API/.env" ]; then
    echo "==> Loading DATABASE_URL from $DATSME_API/.env"
    # shellcheck disable=SC1091
    set -a; . "$DATSME_API/.env"; set +a
  else
    echo "ERROR: DATABASE_URL not set and $DATSME_API/.env not found." >&2
    echo "       Set DATABASE_URL to DatsMe's Postgres URL and re-run." >&2
    exit 1
  fi
fi

# Sanity: can we see the partner's signed manifest before we ask the host to?
echo "==> Pre-checking DatsPet manifest is reachable + signed…"
if ! curl -fsS -o /dev/null -D - "$MANIFEST_URL" 2>/dev/null | grep -qi "X-DatsMe-Signature"; then
  echo "WARNING: $MANIFEST_URL did not return an X-DatsMe-Signature header." >&2
  echo "         The DatsPet backend must be running with a (temporary)" >&2
  echo "         DATSME_HMAC_SECRET set so the manifest signs, or the host" >&2
  echo "         probe will fail. Start it, then re-run. Continuing anyway…" >&2
  echo
fi

# Bootstrapping note: registration GENERATES the secret, then probes DatsPet's
# manifest and verifies its HMAC signature AGAINST that just-generated secret.
# On a first registration DatsPet cannot yet be signing with a secret it hasn't
# received — a genuine chicken-and-egg for a self-hosted partner. Two ways
# through, pick with DATSPET_SKIP_VALIDATION:
#   unset/0 (default): full probe. Use ONLY if you have pre-seeded DatsPet with
#           the exact secret registration will generate (not possible on a cold
#           first run — this path is for re-registration after a secret is known).
#   1:      skip the probe (like the reference personality partner did). The row
#           + secret are created without the signed-manifest check; you then wire
#           the secret into pet_env.sh and all ONGOING launch/writeback signature
#           checks work normally. Correct for local/self-hosted first-time setup.
SKIP_FLAG=()
if [ "${DATSPET_SKIP_VALIDATION:-0}" = "1" ]; then
  echo "==> DATSPET_SKIP_VALIDATION=1 — skipping the manifest-probe (first-run bootstrap)."
  SKIP_FLAG=(--skip-validation)
fi

cd "$DATSME_API"
exec python3 scripts/register_partner_app.py \
  --slug "$SLUG" \
  --name "$NAME" \
  --launch-base "$LAUNCH_BASE" \
  --manifest-url "$MANIFEST_URL" \
  --tier "$TIER" \
  "${SKIP_FLAG[@]}"
