# Deploying DatsPet to pet.datsme.me

> **➡️ Deploying right now? Use [`CHECKLIST.md`](CHECKLIST.md), not this file.**
> That is the step-by-step procedure, and every item on it exists because something
> broke. This file is the *reference*: topology, one-off setup, and why the box looks
> the way it does. When the two disagree, fix both.

Production layout (spec `docs/SPEC_DEPLOY_PETDATSME_POOL.md` Part C; live since
2026-07-13). Everything runs on the Hetzner box (`ssh root@5.161.70.13`), which
also hosts DatsMe (prod + staging) and the pool dispatcher.

## Topology on the box

| Piece | Where | Notes |
|---|---|---|
| Code | `/var/www/datspet` | plain git clone (deployed via git bundle; no remote) |
| Backend | `datspet-backend.service` | uvicorn `app:app`, port **29954**, `--workers 1` (required — Finding 6) |
| Env + secrets | `/var/www/datspet/webui/.env` (600) | `PET_GEN_BACKEND=pool`, the three byte-identical `https://pet.datsme.me` URLs (§C.5!), `DATSME_BASE_URL/PUBLIC_URL` → the host, `DATSME_HMAC_SECRET` from registration, `POOL_APP_KEY` |
| Frontend | `/var/www/datspet/web/out` | static export; **build on the box** (R4-3/R4-4) |
| Vhost + TLS | `datspet-nginx` container | nginx:alpine on `sales_ai_net`, `VIRTUAL_HOST`/`LETSENCRYPT_HOST=pet.datsme.me`; conf mounted from `/var/www/datspet/nginx-default.conf`, static from `web/out` |
| Data | `/var/www/datspet/data` | SQLite pet store + transient previews/scratch |

**Partner SDK (Finding 5):** installed editable from the co-located host repo —
`webui/venv/bin/pip install -e /var/www/datsme-staging/api/sdk` — so SDK fixes
land with the host repo. Verify:
`webui/venv/bin/python -c "from datsme_partner_sdk.host_signature import verify_host_signature"`.

**`pet_factory` as a data-only install (motion profiles).** The web tier now imports
`pet_factory.motion_profiles` at module top (the species-aware pose menu — pure JSON/data,
SPEC_MOTION_PROFILES §5.1). `pet_factory/__init__` is lazy (PEP 562), so importing that
subpackage does NOT pull in the ML factory. But `pet_factory` must be *findable* on the
GPU-less venv, and the repo root is not on the backend's `sys.path` (cwd is `webui/`).
Install it **`--no-deps`** — this is essential; `pyproject.toml`'s deps include numpy/rembg,
so a plain install would destroy the GPU-less posture:

```bash
webui/venv/bin/pip install --no-deps -e /var/www/datspet          # prod
# (staging: -e /var/www/datspet-staging)
```

Verify after: `webui/venv/bin/python -c "from pet_factory import motion_profiles"` works, AND
`webui/venv/bin/python -c "import numpy"` still fails (numpy absent). A lazy factory attribute
(`pet_factory.make_pet_zip`) raises `ModuleNotFoundError: numpy` *at access time* — never at app
import — which is exactly the GPU-less property the backend relies on.

**UFW gotcha:** container→host traffic needs an explicit bridge rule or the
proxy times out while the backend works locally:
`ufw allow in on br-03ba34c7f8c0 to any port 29954 proto tcp`.

## Update procedure (from the dev box)

```bash
# 0. PREFLIGHT — before bundling, if web/ changed. Catches the export-only defects
#    that `next dev` is structurally incapable of showing you (see below). ~15 s.
#    STOP THE DEV SERVER FIRST — it runs a real `next build`, which poisons a live
#    dev server's .next/ (measured; an earlier "it's isolated by distDir" claim was
#    wrong and cost one dev server). The build guard blocks it and is correct to.
scripts/preflight_static_export.py

git bundle create /tmp/datspet.bundle main && scp /tmp/datspet.bundle root@5.161.70.13:/tmp/
ssh root@5.161.70.13 '
  cd /var/www/datspet && git pull /tmp/datspet.bundle main
  webui/venv/bin/pip install -q -r webui/requirements.txt        # if reqs changed
  webui/venv/bin/pip install -q --no-deps -e /var/www/datspet    # data-only pet_factory (idempotent; see above)
  cp deploy/nginx-default.conf nginx-default.conf                # if conf changed
  cd web && npm install --no-audit --no-fund                    # REQUIRED if package.json changed — see below
  DATSPET_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL=https://pet.datsme.me npm run build  # if web/ changed
  systemctl restart datspet-backend && docker restart datspet-nginx'
```

**`npm install` is NOT optional when `package.json` moved (learned 2026-07-15).** This
procedure had a `pip install -r requirements.txt` step for Python and *nothing* for npm, so
the box's `node_modules` silently drifts. Adding `vitest` as a devDependency broke the
staging build outright: `next build` typechecks `**/*.ts`, which includes `vitest.config.ts`,
which imports `vitest/config` — absent on the box. `Failed to compile`, no export, and
nothing about the error names npm. Run `npm install` first whenever `package.json` changed.
(`scripts/preflight_static_export.py` now fails with this exact advice, since it runs the
same build.)

**Run the preflight when `web/` changed (step 0).** `next dev` and `output: "export"` are two
different runtimes for identical source, and dev is the forgiving one — so a whole class of
defect exists ONLY in the artifact you ship and cannot be reproduced locally no matter how
carefully you look:

- A page calling Next's `redirect()` is a real server-side 307 under `next dev`. In the export
  it is a **blank page**: empty `<body>`, hop buried in a `NEXT_REDIRECT;…` script payload, no
  meta-refresh. That is how `/design` — the DPP deep-link target, whose URL is registered with
  the host and is not ours to edit — shipped broken on 2026-07-15. Prod's redirect must live in
  nginx (`location = /design`), and the preflight enforces that pairing.
- **A broken route does not 404.** The vhost ends in `try_files … /index.html`, so a missing
  page serves the *landing page* with a **200**. Curling a route and asserting 200 therefore
  proves nothing; the preflight checks the export's actual files instead.

Both halves of the `/design` redirect (`web/src/app/design/page.tsx` for dev, the nginx
`location =` for prod) must move together. The preflight fails if they drift apart.

**⚠️ NEVER `cp deploy/nginx-default.conf nginx-default.conf` ON STAGING.** The repo conf is
PROD's: it hardcodes `proxy_pass http://172.18.0.1:29954`. Staging's backend is **29964**, so
that copy silently points the staging vhost at the PRODUCTION backend — launches would verify
against the wrong environment and writebacks would land on the wrong host, which is the exact
failure the twin exists to prevent. Patch staging's own `nginx-default.conf` in place instead,
and always `docker run --rm -v <conf>:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t`
before restarting the vhost.

**First deploy of the motion-profiles code (and on any fresh venv):** run the
`--no-deps -e` install above BEFORE restarting the backend — the web tier imports
`pet_factory.motion_profiles` at module top, so without it the backend hits
`ModuleNotFoundError: pet_factory` and `Restart=always` crash-loops.

Gates after any deploy (the no-ML proof, §C.1 — updated for the data-only pet_factory):
`pip list | grep -iE "rembg|onnxruntime|numpy|torch"` must be **EMPTY** (the ML stack is
absent); `pet_factory` MAY appear (it's a `--no-deps` data-only install and drags in no ML);
`webui/venv/bin/python -c "from pet_factory import motion_profiles; import sys; sys.exit(0)"`
imports cleanly while `import numpy` fails. Then `curl https://pet.datsme.me/api/health` shows
`workshop.online: true`; a standalone design → preview → create-from-preview works end to end.

## Production posture (§7 step 9)

- **Maintenance thread** (in the backend, ASGI startup): drains the DPP
  writeback retry queue every 5 min; sweeps previews/scratch older than 24 h
  and long-expired bundle tokens hourly.
- **Opt-1 reattach:** in-flight pool jobs are persisted (`jobs` table) and
  reattached after a backend restart — a restart mid-generation no longer
  orphans the pet.
- **Rate limits** (nginx, per IP): `/api/generate` + `/api/preview` 6/min
  (burst 4), other backend surfaces 10/s (burst 20) → 429.
- **Monitoring:** `GET /api/health` → `{status, backend, active_jobs, workshop}`.

## Tier posture & pose pricing (SPEC_PET_DESIGNER_PLATFORM §5)

The pose selector cap + extra-pose price come from `pet_factory/tiers/tiers.json`
(a data-only file on the GPU-less web tier, `--no-deps -e` like the motion
profiles). The **one-line launch lever is `default_tier`**:

- **Current posture — `default_tier: "plus"`.** EVERY user (standalone + any
  DatsMe-launched user) resolves to `plus`: up to **5 poses**, and each pose
  beyond walk+idle is charged **50 credits** on Accept. This works with no
  DatsMe capability grant — the host counts poses server-side from the fetched
  bundle manifest (`credit_pet_extra_pose_cost`, default 50; see the host repo's
  `social_ledger_config.py` + `pet_writeback.py`). A 3-pose Accept charges
  `credit_pet_design_cost + 2×50` (100 + 100 = **200** at defaults); observe it
  in the credit ledger as the first live proof of the charging change.
- **To differentiate tiers later** (free = 2 poses, a premium capability unlocks
  5): (1) DatsMe registers a real premium capability (known-capabilities list +
  partner manifest request + user grant), (2) map its string in
  `capability_tiers`, (3) flip `default_tier` back to `"base"`. All three are
  config/data — **no code change, no redeploy of logic** — and the resolution is
  forge-resistant (the tier comes from the launch token's verified capabilities,
  never a client claim). A guard test (`test_tiers.py::test_launch_posture_
  default_is_plus`) pins the current default so a flip is deliberate.

## The staging twin (pet-staging.datsme.me)

One DatsPet instance serves ONE DatsMe host — the DPP token carries no host
identity (`iss: "datsme"` only) and the partner holds a single
`DATSME_HMAC_SECRET` + `DATSME_BASE_URL`, so launches/writebacks cannot be
routed per-environment. Staging therefore runs a full twin (live since
2026-07-13): `/var/www/datspet-staging`, `datspet-staging-backend.service` on
port **29964**, `datspet-staging-nginx` vhost, own data dir, own secret,
`DATSME_BASE_URL=https://staging.datsme.me`. Update it the same way as prod
(same bundle → `git pull` in `/var/www/datspet-staging`, the `--no-deps -e
/var/www/datspet-staging` data-only `pet_factory` install, rebuild the static
export with `NEXT_PUBLIC_API_URL=https://pet-staging.datsme.me`). Never point
both hosts' partner rows at one instance — the launch may verify (shared
secret) but the writeback lands on the wrong environment.

## Registration (Part D)

Per host (staging, then prod):
`PATH=<host api venv>/bin:$PATH DATSME_API=/var/www/<host>/api DATSPET_SKIP_VALIDATION=1 DATSPET_PUBLIC_URL=https://pet.datsme.me bash scripts/register_datspet.sh`
→ wire the printed secret into `webui/.env` as `DATSME_HMAC_SECRET`, restart the
backend, then trigger the host's manifest reconciler
(`apps.dpp.scheduler._manifest_refresh_tick()`; natural cadence 15 min).
The single instance points at ONE host via `DATSME_BASE_URL` (currently prod
`datsme.me`); flipping = env edit + restart.
