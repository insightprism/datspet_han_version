#!/usr/bin/env bash
# roll_pet_fleet.sh — roll the DatsPet pool handler (+ engine) across EVERY pet node,
# discovering the node set from the dispatcher so the roll can never miss one.
#
#   scripts/roll_pet_fleet.sh                       # roll every online pet node to this repo's HEAD
#   scripts/roll_pet_fleet.sh --dry-run             # show the plan, touch nothing
#   scripts/roll_pet_fleet.sh --stash               # stash a node's dirty engine/handler files, then ff
#   scripts/roll_pet_fleet.sh --verify-url https://pet-staging.datsme.me   # + a real upload job at the end
#
# WHY THIS EXISTS (the 2026-07-23 upload_isolate roll)
# ----------------------------------------------------
# The pet fleet was DOCUMENTED as one node (omen-pet). It was two: dual-nvidia-pet
# was still on the OLD handler and would have 422'd isolate jobs that routed to it —
# an intermittent, coin-flip failure that is miserable to diagnose. The docs were
# stale; the dispatcher was not. So the rules this script bakes in, each learned the
# hard way that day:
#
#   1. DISCOVER the node set from /api/pool, never a hardcoded list. A discovered pet
#      node that is NOT in the reach-map below is a HARD STOP before anything mutates —
#      that stop is exactly the check that would have caught node #2.
#   2. A node's checkout can carry UNCOMMITTED engine/handler edits (omen did — a stale
#      hand-applied worktree). ff-only refuses to merge over them, so we check that
#      pet_factory/ + pool_handler/ are clean per node and (with --stash) stash them.
#   3. The INSTALLED handler is a COPY; advancing git does NOT touch it. Copy the file +
#      clear __pycache__ + restart, then GREP the installed "version" to confirm — because
#      `pool-install-handler --restart` has printed "restarted" while the restart FAILED.
#   4. Never finish VERSION-MIXED. Every online pet node must report the target handler
#      version, or the run fails loudly. Roll with upload_isolate OFF (the fleet gate) and
#      flip it on only once this script is green.
#
# The target handler version is READ from THIS repo's pool_handler/pet_preview_handler.py —
# the script rolls "whatever this checkout declares" and holds every node to it. Bump the
# handler, commit, run this; there is no version string to keep in sync here.
#
# Exit 0 = every online pet node is on the target version. Non-zero = do not walk away.
set -uo pipefail

# ------------------------------------------------------------------ reach-map
# The dispatcher knows WHICH nodes serve pets; it does NOT know how to reach them (workers
# dial out, NAT'd). This map is that missing half: node_id -> how to run a command there and
# where its files live. A pet node the dispatcher reports that is missing here HALTS the roll.
#
#   SSH=""  -> this box (run locally).      REPO -> the checkout its worker imports pet_factory from.
#   HANDLERS -> its POOL_HANDLERS_DIR.      UNIT -> its systemd worker unit.
NODE_ORDER=(omen-pet dual-nvidia-pet)                       # roll order; Omen first (R3-1)
declare -A NODE_SSH=(      [omen-pet]="flipper@192.168.0.22"                         [dual-nvidia-pet]="" )
declare -A NODE_REPO=(     [omen-pet]="/home/flipper/datsme-pet-factory_wu"          [dual-nvidia-pet]="/home/markly2/claude_code/datsme-pet-factory_wu" )
declare -A NODE_HANDLERS=( [omen-pet]="/home/flipper/.pool/pet_handlers"             [dual-nvidia-pet]="/home/markly2/.pool/handlers_pet" )
declare -A NODE_UNIT=(     [omen-pet]="pool-worker-pet"                              [dual-nvidia-pet]="pool-worker-pet" )

DISPATCHER_URL="${DISPATCHER_URL:-https://pool.datsme.me}"
POOL_BOX="${POOL_BOX:-root@5.161.70.13}"                    # holds the app key + env files
LOCAL_REPO="$(cd "$(dirname "$0")/.." && pwd)"             # this checkout = the source of truth

DRY=0; STASH=0; VERIFY_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)    DRY=1; shift ;;
    --stash)      STASH=1; shift ;;
    --verify-url) VERIFY_URL="$2"; shift 2 ;;
    *) echo "unknown arg: $1"; echo "usage: $0 [--dry-run] [--stash] [--verify-url URL]"; exit 2 ;;
  esac
done

PASS=0; FAIL=0
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
note() { printf '        %s\n' "$1"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
die()  { printf '\n\033[31mABORT:\033[0m %s\n' "$1"; exit 1; }

# run a fully-interpolated command string on a node (locally if SSH is empty)
run_on() { local t="${NODE_SSH[$1]}"; if [ -z "$t" ]; then bash -c "$2"; else ssh -o BatchMode=yes "$t" "$2"; fi; }

echo "=============================================================="
echo " roll_pet_fleet  ->  target = this checkout ($LOCAL_REPO)"
echo "=============================================================="

# ---------------------------------------------------------------- target version
TARGET_VER=$(grep -oP '"version": "\K[0-9]+' "$LOCAL_REPO/pool_handler/pet_preview_handler.py" | head -1)
TARGET_SHA=$(git -C "$LOCAL_REPO" rev-parse --short HEAD 2>/dev/null || echo "?")
[ -z "$TARGET_VER" ] && die "cannot read target pet_preview version from $LOCAL_REPO/pool_handler/pet_preview_handler.py"
echo " target pet_preview handler version = $TARGET_VER   (repo HEAD $TARGET_SHA)"

# ---------------------------------------------------------------- discover nodes
hdr "1. Discover pet nodes from the dispatcher (source of truth, NOT the docs)"
APP_KEY="${POOL_APP_KEY:-}"
[ -z "$APP_KEY" ] && [ -f "$HOME/.pool/datspet_key" ] && APP_KEY=$(cat "$HOME/.pool/datspet_key")
if [ -z "$APP_KEY" ]; then
  APP_KEY=$(ssh -o BatchMode=yes "$POOL_BOX" 'grep -oP "^POOL_APP_KEY=\K.*" /var/www/datspet/webui/.env 2>/dev/null || cat /var/www/pool/app_key_datspet 2>/dev/null' 2>/dev/null)
fi
[ -z "$APP_KEY" ] && die "no pool app key (set POOL_APP_KEY, or ~/.pool/datspet_key, or ensure ssh $POOL_BOX works)"

POOL_JSON=$(curl -sS -m 20 -H "X-App-Key: $APP_KEY" "$DISPATCHER_URL/api/pool" 2>/dev/null)
DISCOVERED=$(echo "$POOL_JSON" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for n in d.get('nodes',[]):
    if any('pet' in str(t) for t in n.get('tasks',[])) and n.get('online'):
        print(n['node_id'])
" 2>/dev/null)
[ -z "$DISCOVERED" ] && die "dispatcher returned no online pet nodes (bad key, or $DISPATCHER_URL unreachable). Raw: ${POOL_JSON:0:160}"
echo " online pet nodes: $(echo $DISCOVERED | tr '\n' ' ')"

# HARD STOP: any discovered pet node we don't know how to reach = the miss that started this.
UNKNOWN=""
for n in $DISCOVERED; do [ -z "${NODE_REPO[$n]:-}" ] && UNKNOWN="$UNKNOWN $n"; done
[ -n "$UNKNOWN" ] && die "online pet node(s) NOT in this script's reach-map:$UNKNOWN
        Add each to NODE_ORDER/NODE_SSH/NODE_REPO/NODE_HANDLERS/NODE_UNIT and re-run.
        Refusing to roll a fleet I cannot fully reach — that leaves it version-mixed."
ok "every online pet node is in the reach-map"

# roll only the nodes that are BOTH mapped and currently online
TARGETS=(); for n in "${NODE_ORDER[@]}"; do echo "$DISCOVERED" | grep -qx "$n" && TARGETS+=("$n"); done

if [ "$DRY" = 1 ]; then
  hdr "DRY RUN — plan"
  for n in "${TARGETS[@]}"; do
    echo "  $n  (ssh='${NODE_SSH[$n]:-<local>}')"
    echo "      repo     ${NODE_REPO[$n]}   -> ensure clean(pet_factory,pool_handler) + at/after $TARGET_SHA"
    echo "      handlers ${NODE_HANDLERS[$n]}  <- copy pet_preview_handler.py + pet_factory_handler.py (v$TARGET_VER)"
    echo "      restart  ${NODE_UNIT[$n]}, then assert installed version == $TARGET_VER"
  done
  echo; echo "(no changes made)"; exit 0
fi

# ---------------------------------------------------------------- roll each node
declare -A GOT_VER
for n in "${TARGETS[@]}"; do
  repo="${NODE_REPO[$n]}"; hdir="${NODE_HANDLERS[$n]}"; unit="${NODE_UNIT[$n]}"
  hdr "2. Roll $n  (${NODE_SSH[$n]:-local})"

  # (2a) engine repo: engine/handler files must be clean before an ff-only advance.
  dirty=$(run_on "$n" "git -C '$repo' status --porcelain pet_factory pool_handler 2>&1")
  if [ -n "$dirty" ]; then
    if [ "$STASH" = 1 ]; then
      run_on "$n" "git -C '$repo' stash push -u -m 'roll_pet_fleet-pre-$TARGET_SHA' -- pet_factory pool_handler" >/dev/null 2>&1 \
        && note "stashed dirty engine/handler files on $n" \
        || { bad "$n: could not stash dirty files"; continue; }
    else
      bad "$n: engine/handler files are DIRTY — commit them, or re-run with --stash"
      note "$(echo "$dirty" | head -4)"; continue
    fi
  fi

  # (2b) advance the engine to the target if the node knows the commit and is behind.
  head_now=$(run_on "$n" "git -C '$repo' rev-parse --short HEAD 2>/dev/null")
  if [ "$head_now" != "$TARGET_SHA" ]; then
    if run_on "$n" "git -C '$repo' cat-file -e '$TARGET_SHA^{commit}' 2>/dev/null"; then
      run_on "$n" "git -C '$repo' merge --ff-only '$TARGET_SHA' >/dev/null 2>&1" \
        && note "engine $n: $head_now -> $TARGET_SHA (fast-forward)" \
        || { bad "$n: ff to $TARGET_SHA failed (diverged?) — reconcile $repo manually"; continue; }
    else
      bad "$n: target $TARGET_SHA is not present in $repo — push/bundle it to this node first"
      note "(omen tracks a bundle/remote; get the commit there, then re-run)"; continue
    fi
  else
    note "engine $n: already at $TARGET_SHA"
  fi

  # (2c) install the handler COPY (git does not touch it) + clear stale bytecode.
  run_on "$n" "cp '$repo/pool_handler/pet_preview_handler.py' '$repo/pool_handler/pet_factory_handler.py' '$hdir/' && rm -rf '$hdir/__pycache__'" \
    && note "installed handlers into $hdir" \
    || { bad "$n: handler copy failed"; continue; }

  # (2d) restart the worker (passwordless sudo verified on both boxes today).
  run_on "$n" "sudo -n systemctl restart '$unit'" \
    || { bad "$n: restart failed (interactive sudo?) — the WORKER, not the installer, is the truth"; continue; }
  sleep 4

  # (2e) verify the RUNTIME, not the installer: unit up + installed version == target.
  active=$(run_on "$n" "systemctl is-active '$unit' 2>/dev/null")
  iver=$(run_on "$n" "grep -oP '\"version\": \"\K[0-9]+' '$hdir/pet_preview_handler.py' | head -1")
  GOT_VER[$n]="$iver"
  if [ "$active" = "active" ] && [ "$iver" = "$TARGET_VER" ]; then
    ok "$n: unit active, installed pet_preview = v$iver"
  else
    bad "$n: unit=$active, installed pet_preview=v${iver:-none} (want active/v$TARGET_VER)"
  fi
done

# ---------------------------------------------------------------- fleet consistency
hdr "3. Fleet must NOT be version-mixed"
mixed=0
for n in $DISCOVERED; do
  v="${GOT_VER[$n]:-<not rolled>}"
  if [ "$v" = "$TARGET_VER" ]; then ok "$n -> v$v"; else bad "$n -> $v (expected v$TARGET_VER)"; mixed=1; fi
done
[ "$mixed" = 1 ] && note "A stale node still online means isolate jobs routed there 422. Fix before flipping upload_isolate on."

# ---------------------------------------------------------------- optional real job
if [ -n "$VERIFY_URL" ]; then
  hdr "4. Real job: upload → $VERIFY_URL/api/reference"
  IMG="$LOCAL_REPO/pet_factory/animal_catalog/dog/corgi/base.png"
  CODE=$(curl -sS -m 160 -o /dev/null -w '%{http_code}' -F "animal=dog" -F "ai_caption=false" \
         -F "image=@$IMG;type=image/png" "$VERIFY_URL/api/reference" 2>/dev/null)
  [ "$CODE" = "200" ] && ok "upload preview -> 200 (pet_preview path live end-to-end)" \
                       || bad "upload preview -> $CODE"
  note "for full coverage also run: scripts/verify_deployment.sh $VERIFY_URL"
fi

echo
echo "=============================================================="
printf ' roll_pet_fleet: \033[32m%d ok\033[0m, \033[31m%d fail\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] && echo " GREEN — every online pet node is on v$TARGET_VER. Safe to flip upload_isolate on." \
                || echo " NOT green — see FAIL lines; do NOT flip upload_isolate on while mixed."
echo "=============================================================="
[ "$FAIL" = 0 ]
