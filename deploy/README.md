# Deploying DatsPet to pet.datsme.me

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

**UFW gotcha:** container→host traffic needs an explicit bridge rule or the
proxy times out while the backend works locally:
`ufw allow in on br-03ba34c7f8c0 to any port 29954 proto tcp`.

## Update procedure (from the dev box)

```bash
git bundle create /tmp/datspet.bundle main && scp /tmp/datspet.bundle root@5.161.70.13:/tmp/
ssh root@5.161.70.13 '
  cd /var/www/datspet && git pull /tmp/datspet.bundle main
  webui/venv/bin/pip install -q -r webui/requirements.txt        # if reqs changed
  cp deploy/nginx-default.conf nginx-default.conf                # if conf changed
  cd web && DATSPET_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL=https://pet.datsme.me npm run build  # if web/ changed
  systemctl restart datspet-backend && docker restart datspet-nginx'
```

Gates after any deploy: `pip list | grep -iE "rembg|onnxruntime|pet.factory"`
must be EMPTY (the no-ML proof, §C.1); `curl https://pet.datsme.me/api/health`
shows `workshop.online: true`; a standalone design → preview →
create-from-preview works end to end.

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

## The staging twin (pet-staging.datsme.me)

One DatsPet instance serves ONE DatsMe host — the DPP token carries no host
identity (`iss: "datsme"` only) and the partner holds a single
`DATSME_HMAC_SECRET` + `DATSME_BASE_URL`, so launches/writebacks cannot be
routed per-environment. Staging therefore runs a full twin (live since
2026-07-13): `/var/www/datspet-staging`, `datspet-staging-backend.service` on
port **29964**, `datspet-staging-nginx` vhost, own data dir, own secret,
`DATSME_BASE_URL=https://staging.datsme.me`. Update it the same way as prod
(same bundle → `git pull` in `/var/www/datspet-staging`, rebuild the static
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
