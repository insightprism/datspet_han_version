# DatsPet Deploy Checklist

> **Every item on this list exists because something broke.** None of it is theoretical.
> Work top to bottom. Do not skip an item because "nothing in that area changed" — three
> of the failures below came from exactly that reasoning.
>
> `deploy/README.md` is the *reference* (topology, one-off setup, why the box looks like
> it does). **This file is the procedure.** When they disagree, fix both.

## Rule 0 — STAGING FIRST, ALWAYS. Production may never be ahead of staging.

**Every production deploy goes through staging first.** Deploy staging, verify it (Phase C),
*then* deploy production with the same commit. There is no exception, no "it's a small change",
no "staging is behind anyway".

**Production must never be at a commit staging does not already have.** If you find it is, that
is a defect to correct, not a state to work from — bring staging up before the next prod deploy.

*(Added 2026-07-27, user policy. Until then this file described a **per-target** procedure — pick
a target, run A→B→C — and C2's "check the one you did *not* deploy" assumed you deploy one, not a
sequence. Nothing stopped a prod-only deploy, and on 2026-07-27 one happened: prod went to
`c603356` while staging sat at `2a95c8d`, 32 commits behind. No harm resulted, but the twin had
stopped being a twin, so there was nothing to rehearse the next deploy in.)*

**The fleet is SHARED; the web tiers are NOT.** `omen-pet` + `dual-nvidia-pet` serve staging and
production **both** — one roll covers each. But `/var/www/datspet` and `/var/www/datspet-staging`
are two separate servers with separate venvs, builds, units, vhosts and ports, and each needs its
own Phase B. **Rolling the fleet is not deploying anything.** So the full order is:

    fleet (once)  ->  staging Phase B + C  ->  production Phase B + C

---

## The one thing to understand before deploying this app

The 2026-07-15 designer deploy produced **nine distinct failures. Every single one was a
false green** — a check that reported success while the thing it named was broken:

| What broke | What the check said |
|---|---|
| 100% of pool jobs dying | fleet gate **green** (it tested a schema, not the runtime) |
| node running stale engine | `pool-install-handler` printed **"restarted"** — it had failed |
| staging pointed at prod's backend | `cp` **succeeds silently** |
| `/design` blank in prod | dev **perfect**, server **200** |
| users served a deleted page | every curl said **307** |
| `max_poses=10` to real users | tests **passed** (they'd been updated to expect 10) |
| a live dev server poisoned | guard said **"no collision is possible"** |

So the rule this checklist enforces: **never accept a proxy for the real thing.** A status
code is not a working page. An installer's output is not a running process. Config is not
behaviour. Where you can exercise the real path, exercise it.

---

## Quick Reference

| | **Staging** | **Production** |
|---|---|---|
| URL | `https://pet-staging.datsme.me` | `https://pet.datsme.me` |
| Box | `ssh root@5.161.70.13` | same box |
| Repo | `/var/www/datspet-staging` | `/var/www/datspet` |
| Backend port | **29964** | **29954** |
| systemd unit | `datspet-staging-backend.service` | `datspet-backend.service` |
| Vhost container | `datspet-staging-nginx` | `datspet-nginx` |
| nginx conf | **patch in place — see A5** | `cp deploy/nginx-default.conf` is correct |
| DatsMe host | staging host | prod host |

⚠️ **The repo's `deploy/nginx-default.conf` IS PRODUCTION'S** — it hardcodes `:29954`.
See **A5**. This is the sharpest edge in the whole procedure.

---

## Phase A — Local, before you touch a box

- [ ] **A1. Stop the dev server.**
      The preflight runs a real `next build`, which poisons a live dev server's `.next/`
      (measured: `BUILD_ID` re-stamped, 189→170 files, dev then 500s on its own
      `layout.css`). The build guard blocks this and is **correct** to.
      **Do not** set `ALLOW_BUILD_WITH_DEV=1` to get past it.
      *(2026-07-15: a "distDir isolates it" claim was wrong and cost one dev server.)*

- [ ] **A2. Tests green.**
      ```bash
      .venv/bin/python -m pytest pet_factory/tests webui/tests -q   # 218 passing
      cd web && npm test && npx tsc --noEmit
      ```

- [ ] **A3. Preflight the export** — catches defects that exist ONLY in the shipped
      artifact and that `next dev` is structurally incapable of showing you.
      ```bash
      scripts/preflight_static_export.py          # ~15 s
      ```
      *(2026-07-15: `/design` shipped to staging as a blank page. Dev rendered it
      perfectly — under `next dev` there's a Node server, so `redirect()` is a real 307;
      the export has none, so it's an empty `<body>` + a JS-only hop.)*

- [ ] **A4. Hunt testing knobs and launch landmines.** ⚠️ **PRODUCTION ONLY — do not skip.**
      ```bash
      grep -rniE "REVERT BEFORE LAUNCH|FOR TESTING|TESTING \(20" \
        --include=*.json --include=*.py --include=*.ts --include=*.tsx . | grep -v node_modules
      ```
      Tests will **not** save you here — a knob commit updates the tests to match itself.
      *(2026-07-15: `plus.max_poses` was 10 for testing. `default_tier` is `plus`, so that
      is what EVERY user gets: a 10-pose pet charges 100 + 8×50 = **500 credits**. It was
      caught by asking, not by any gate. Reverting it also needed care — `git revert`
      conflicted and would have resurrected deleted tests and undone the `reference_id`
      migration. Check what changed since before reverting.)*

- [ ] **A5. Decide the nginx conf per target.** ⚠️ **The silent one.**
      - **Prod:** `cp deploy/nginx-default.conf nginx-default.conf` is correct.
      - **Staging:** **NEVER `cp`.** The repo conf hardcodes `proxy_pass :29954`; staging
        is **29964**. Copying it points the staging vhost at the **production backend** —
        launches verify against the wrong environment and writebacks land on the wrong
        host, the exact failure the twin exists to prevent. **Patch staging's own conf in
        place**, then diff it against the repo's to confirm only the port differs.
      *(Fix forward: datsme_me already keeps `nginx.production.conf` + `nginx.staging.conf`
      as separate files. DatsPet should do the same and delete this hazard — see §E.)*

- [ ] **A6. Does the pool fleet need rolling first?**
      If this deploy changes `pool_handler/*` **or** any `pet_factory` engine function a
      handler calls: **the fleet rolls FIRST, and the engine rolls WITH the handler.**
      Each node imports `pet_factory` from its **own clone**, so shipping the handler
      alone leaves nodes on the old signature.

      **Use `scripts/roll_pet_fleet.sh --stash --verify-build`.** It discovers the node set
      from the dispatcher (so it cannot miss one), refuses to finish version-mixed, and
      `--verify-build` runs a **real `make_pet_zip` per node** and checks the sprite's alpha.
      Prefer it over `--verify-url`: that one posts to `/api/reference`, which is the *preview*
      path and never touches the cutout, so it cannot see a broken arena cap or a fatal matte.
      *(2026-07-26: `--verify-build`'s first run caught `dual-nvidia-pet` failing a real build —
      it shares GPU 1 with the Motion Lab's separate ComfyUI `:19963`, which was holding 18 GB.
      F4 evicts only the pool's instance `:19956`, so **a card can be full while the eviction
      correctly reports "landed"**. Check `nvidia-smi` on a pet node's GPU, not just the
      eviction log.)*

      ⚠️ **ORDER: commit → push/bundle → deliver to EVERY node → then roll.** The script does
      `merge --ff-only <target>` against objects the node already has; it deliberately does not
      fetch, because nodes differ (omen-pet pulls from GitHub, the Hetzner box pulls from
      `/tmp/datspet.bundle`). Rolling before the commit is reachable everywhere just fails with
      *"target … is not present"* — harmless, but it cost three re-runs on 2026-07-26.

      ⚠️ **ARMED for the first deploy carrying `ca46e38` (design axes).** Both handlers'
      param schema widened (`animal`/`description` maxLength 250 → **600**) because axis
      picks make composed prompts longer than 250. A node still on the old handler will
      **reject a maximal design as schema-invalid** — 100%-green gates, per-job failures,
      the exact 2026-07-15 shape. The widening is backward-compatible (600 accepts
      everything 250 did), so the safe order is: `pool-install-handler` on **every** node
      any time BEFORE the web tier ships — then verify per A6's own rule: the unit is
      actually up AND a real job of the new shape (a 3-axis design preview) succeeds.
      Delete this block after that deploy's C1 passes.
      *(2026-07-15: `pet_preview` v2 went out; `omen-pet`'s clone was stale; 100% of jobs
      died with `render_design_still() missing 2 required positional arguments` while the
      gate stayed green. And `pool-install-handler --restart` printed "restarted" when the
      restart had actually failed with `Interactive authentication required` — **verify the
      unit is up and submit a real job of the new shape.** Never trust the installer.)*

---

## Phase B — On the box

- [ ] **B1. Record the rollback point BEFORE anything.**
      ```bash
      cd /var/www/datspet && git rev-parse --short HEAD          # write it down
      cp nginx-default.conf /root/backup_$(date +%Y%m%d)_nginx-default.conf
      ```

- [ ] **B2. Pull.** Then **re-read the box's HEAD** and confirm it is what you intended.
      *(If a multi-step script is denied or fails mid-way, the `git pull` may never have
      run while later steps still report "active". Never infer the pull from a later step.)*

- [ ] **B3. `pip install` — unconditionally.** It's idempotent and costs seconds.
      ```bash
      webui/venv/bin/pip install -q -r webui/requirements.txt
      webui/venv/bin/pip install -q --no-deps -e /var/www/datspet   # --no-deps is LOAD-BEARING
      ```

- [ ] **B4. GPU-less gate — the posture is the product.**
      ```bash
      webui/venv/bin/python -c "from pet_factory import motion_profiles, tiers, design_axes"  # must PASS  (body_shapes was absorbed into design_axes)
      webui/venv/bin/python -c "import numpy"                                                 # must FAIL
      webui/venv/bin/pip list | grep -iE "^(rembg|onnxruntime|numpy|torch) "                  # must be EMPTY
      ```

- [ ] **B5. `npm install` — unconditionally.** Also idempotent, also seconds.
      ```bash
      cd web && npm install --no-audit --no-fund
      ```
      *(2026-07-15: the procedure had a pip step and **nothing** for npm, so the box's
      `node_modules` drifted. A new `vitest` devDependency broke the staging build
      outright — `next build` typechecks every `.ts`, including `vitest.config.ts`, which
      `next dev` never loads. The error said "Failed to compile" and named nothing about
      npm. The prod deploy pulled **44 packages**, so the drift was real.)*

- [ ] **B6. Build the export.**
      ```bash
      DATSPET_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL=https://pet.datsme.me npm run build
      ```

- [ ] **B7. Conf per A5, then `nginx -t` BEFORE restarting.** Never restart an unvalidated conf.
      ```bash
      docker run --rm -v /var/www/datspet/nginx-default.conf:/etc/nginx/conf.d/default.conf:ro \
        nginx:alpine nginx -t
      ```

- [ ] **B8. Restart.** Backend + vhost. A conf-only change needs **only** the vhost.
      ```bash
      systemctl restart datspet-backend && systemctl is-active datspet-backend
      docker restart datspet-nginx
      ```

---

## Phase C — Verify. This phase is not optional.

- [ ] **C1. Run the real verification.** It submits real jobs to the real pool, because a
      fleet where every job dies cannot survive a check that submits a job.
      ```bash
      # WARM THE POOL FIRST — see §E 2026-07-27. A cold typed-animal draw exceeds the
      # 60 s outer-proxy timeout and door 2 comes back 504 on a perfectly good deploy.
      curl -s -o /dev/null -m 200 -X POST https://pet.datsme.me/api/reference -F "animal=a blue jay"
      scripts/verify_deployment.sh https://pet.datsme.me --expect-max-poses 8
      ```
      ⚠️ `--expect-max-poses` must match `pet_factory/tiers/*.json`'s `default_tier` cap —
      **8** as of 2026-07-27. The old `5` in this example was stale and would fail a good deploy.
      **Exit 0 or you are not deployed.** Everything it checks is a scar: the DPP deep
      link 307s for real and keeps `?from=datsme`; the designer's *content* renders (a 200
      proves nothing — `try_files` serves `index.html` for missing routes); HTML
      revalidates; all three doors run real jobs.

- [ ] **C2. Verify the OTHER environment is still healthy.**
      Prod and staging share the box **and the GPU pool**. Rolling the fleet or restarting
      touches both. Check the one you did *not* deploy.

- [ ] **C3. Hard-reload in a real browser** (Ctrl+Shift+R), and click the DatsMe
      "Design a pet" launch button end to end.
      *(2026-07-15: `curl` said 307 while a real browser showed a **deleted page** for
      hours — HTML had no `Cache-Control`, so caches applied a heuristic lifetime. This is
      invisible server-side. Only a browser that had been there before could see it. If
      you see something stale, check `Cache-Control` before doubting the deploy.)*

- [ ] **C4. Confirm the box HEAD equals the commit you intended.** Not the output of a
      later step — the HEAD itself.

---

## Phase D — Rollback

```bash
cd /var/www/datspet && git reset --hard <rollback-point-from-B1>
cp /root/backup_<date>_nginx-default.conf nginx-default.conf
webui/venv/bin/pip install -q --no-deps -e /var/www/datspet
cd web && npm install --no-audit --no-fund && DATSPET_STATIC_EXPORT=1 \
  NEXT_PUBLIC_API_URL=https://pet.datsme.me npm run build
systemctl restart datspet-backend && docker restart datspet-nginx
scripts/verify_deployment.sh https://pet.datsme.me      # verify the ROLLBACK too
```

Pool handlers roll back separately — backups are on each node under `~/.pool/backup_*`.

---

## §E — Incident log & how to keep this alive

**When a deploy bites you, add it here, then add the checklist item that would have caught
it.** An incident with no new checklist item means we learned nothing. An item with no
incident is speculation — those rot and get skipped.

Format: date · what broke · what the check said · what now catches it.

| Date | What broke | What the check said | Now caught by |
|---|---|---|---|
| 2026-07-15 | `/design` blank in prod (DPP deep-link target) | dev perfect; server 200 | A3 preflight, C1 |
| 2026-07-15 | staging build failed on `vitest.config.ts` | "Failed to compile", nothing about npm | B5 (unconditional) |
| 2026-07-15 | 100% of pool jobs dying, stale engine on `omen-pet` | fleet gate **green** | A6, C1 (real jobs) |
| 2026-07-15 | `pool-install-handler --restart` no-op | printed **"restarted"** | A6 (verify the unit + a real job) |
| 2026-07-15 | staging conf would point at **prod's backend** | `cp` succeeds silently | A5 |
| 2026-07-15 | `max_poses=10` nearly shipped (500 credits/pet) | tests **passed** | A4, C1 `--expect-max-poses` |
| 2026-07-15 | users served a **deleted page** after a correct deploy | every curl **307** | C1 (cache headers), C3 |
| 2026-07-15 | live dev server poisoned by a build | guard: "no collision possible" | A1 |
| 2026-07-15 | `git revert` of the knob would have undone a migration | git reported the conflict (loud) | A4 |
| 2026-07-27 | prod deployed while staging stayed 32 commits behind | nothing — the procedure was per-target | **Rule 0** |
| 2026-07-27 | C1 door 2 **504'd twice on a healthy deploy** (a false RED) | the same request succeeded 4/4 standalone in 19–45 s | C1's warm-up call |
| 2026-07-27 | C1's `--expect-max-poses 5` example vs the real cap of 8 | would have failed a good deploy | C1's ⚠️ note |

### Known gaps — not yet automated

- ⚠️ **The 60 s outer-proxy timeout — this one reaches USERS, not just C1.** Measured
  2026-07-27: a typed-animal draw (`POST /api/reference`, txt2img on the pool) takes **19–45 s
  warm** and **over 60 s cold**, and comes back **`504` in exactly 60.2 s**. The cause is not
  our vhost — `/var/www/datspet*/nginx-default.conf` correctly sets `proxy_read_timeout 300`.
  It is the **outer `nginx-proxy`**: its generated server blocks for `pet.datsme.me` and
  `pet-staging.datsme.me` set **no** `proxy_read_timeout`, so nginx's **60 s default** applies
  and the outer layer gives up long before our 300 s does. A user who types an animal while the
  pool is cold gets a gateway-timeout page.
  **Fix (not applied — it touches shared infra serving other apps, so it needs a decision):**
  add a `proxy_read_timeout 300;` override in `nginx-proxy`'s `vhost.d/pet.datsme.me` and
  `vhost.d/pet-staging.datsme.me`. The pattern already exists on that box —
  `vhost.d/staging.datsme.me` sets `86400`. Until then, C1's warm-up call is the workaround,
  and it only hides the symptom for the deploy check.

- **`deploy/nginx-default.conf` is prod's file in a shared repo.** A5 is a human
  remembering. **Specced: [`docs/SPEC_PER_TARGET_NGINX_CONF.md`](../docs/SPEC_PER_TARGET_NGINX_CONF.md)**
  (Rev.1, execution-ready, not started) — one template + a 3-value target table, so the
  port is data and cross-wiring becomes impossible rather than remembered. Also fixes a
  live drift: staging is **missing the 2026-07-15 cache fix** because the repo conf and
  staging's conf are unrelated lookalike files.
- **No `deploy.sh`.** Phase B is hand-typed, and hand-typed heredocs mangled the nginx
  redirect once already. Target should be data (`{path, port, url, unit, container}`), the
  sequence fixed, and C1 the final step.
- **The fleet has no runtime gate of its own.** A6 is prose; it should be a script that
  submits a real job of the new shape to **every** node before the web tier deploys.
