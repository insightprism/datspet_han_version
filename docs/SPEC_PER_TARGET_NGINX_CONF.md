# SPEC — per-target nginx conf (delete the "cp prod's conf onto staging" landmine)

**Status:** Design — **Rev.1** (2026-07-15), **execution-ready**, **not started**. Grounded against
the two live vhosts. Written to be picked up cold: everything in §0 was verified, not assumed.

**The problem in one line.** `deploy/nginx-default.conf` **is production's file** — it hardcodes
`proxy_pass :29954` — but nothing in its name says so, and `deploy/README.md` tells you to
`cp` it onto the box. Do that on staging and the staging vhost proxies to the **production
backend**: DPP launches verify against the wrong environment and writebacks land on the wrong
host, which is the precise failure the staging twin exists to prevent. It fails **silently** —
`cp` succeeds, `nginx -t` passes, the site loads.

**Scope guard.** This changes deploy config only. It touches **no application code**, no
`webui/`, no `web/`, no `pool_handler/`, and no ML path. It is a **config refactor with a
rendering step**, nothing more.

---

## 0. What is already TRUE (verified 2026-07-15, against the live box)

| Fact | Evidence |
|---|---|
| **One conf in the repo, and it is prod's.** `deploy/nginx-default.conf` has `server_name pet.datsme.me` and `proxy_pass http://172.18.0.1:29954` ×2. | `grep proxy_pass deploy/nginx-default.conf` |
| **Staging's conf is NOT in git.** It exists only as a hand-patched file at `/var/www/datspet-staging/nginx-default.conf`. No history, no review, no restore if the box dies. | `find . -name '*.conf' -path '*deploy*'` returns exactly one file |
| **The two confs have already drifted, today.** Staging is **missing** the 2026-07-15 cache fix (`location ^~ /_next/static/` + `Cache-Control: no-cache`). The fix was written in the repo conf, `cp`'d to prod, and never reached staging — because they are unrelated files that merely resemble each other. | `diff` of repo conf vs staging's live conf |
| **Only THREE values actually differ per target**, at **7 sites**: `server_name` (1), backend port (2), rate-limit zone prefix (4). Everything else is byte-identical and changes for product reasons, not environment reasons. | line-by-line diff, ignoring comments |
| **Both targets have IDENTICAL topology.** Both proxy to `172.18.0.1:<port>` on the host bridge; both are `nginx:alpine` containers on `sales_ai_net` behind the same nginx-proxy. | `docker ps`, both confs |
| **The conf uses 8 of nginx's OWN `$variables`**: `$args $binary_remote_addr $host $is_args $proxy_add_x_forwarded_for $remote_addr $scheme $uri`. | `grep -oE '\$[a-z_]+'` |
| **`envsubst` with an allow-list preserves them.** `envsubst '${ZP}'` substitutes only `$ZP` and leaves `$binary_remote_addr`/`$uri` intact. | verified live (§4) |
| **datsme_me's two-file pattern has drifted**: `nginx.production.conf` vs `nginx.staging.conf` differ on **17 lines**, well beyond per-target values (staging has a `map $http_upgrade` block and an 86400 read-timeout prod lacks). | `diff` of the two files |

### The target table (the only per-target data that exists)

| | **Production** | **Staging** |
|---|---|---|
| `SERVER_NAME` | `pet.datsme.me` | `pet-staging.datsme.me` |
| `BACKEND_PORT` | `29954` | `29964` |
| `ZONE_PREFIX` | `datspet` | `datspet_stg` |
| Repo on box | `/var/www/datspet` | `/var/www/datspet-staging` |
| Vhost container | `datspet-nginx` | `datspet-staging-nginx` |
| systemd unit | `datspet-backend.service` | `datspet-staging-backend.service` |

---

## 1. The hazard, stated exactly

Three distinct failures, all live today:

1. **Mis-copy → cross-environment.** `cp deploy/nginx-default.conf` onto staging points it at
   prod's backend. Silent. The only current defense is a human remembering
   (`deploy/CHECKLIST.md` A5).
2. **Staging's conf is unversioned.** Un-reviewable, un-restorable, invisible without SSH.
3. **Shared changes reach one target only.** Proven: staging lacks the cache fix right now.
   Every future vhost change has this same coin-flip.

**Not a hazard:** the two environments needing different ports. That is legitimate and
permanent. The hazard is that the difference is expressed by *hand-editing two lookalike
files* instead of by *data*.

---

## 2. The design

One template, one target table, one renderer.

```
deploy/
  nginx-site.conf.template      # the vhost, with @@PLACEHOLDERS@@ — the ONLY copy
  targets/
    production.env              # SERVER_NAME=pet.datsme.me  BACKEND_PORT=29954  ZONE_PREFIX=datspet
    staging.env                 # SERVER_NAME=pet-staging.datsme.me  BACKEND_PORT=29964  ZONE_PREFIX=datspet_stg
  render_nginx_conf.sh <target> # template + target -> stdout; exits non-zero on any
                                # unsubstituted placeholder
```

`deploy/nginx-default.conf` is **deleted**. Nothing named "default" survives — the name is
half the trap.

**Why this shape.** It is `pet_factory`'s own engine-vs-content rule applied to deploy config:
the vhost body is the **engine** (one copy, changes for product reasons), the three values are
**content** (a table, changes per environment). Adding a third environment becomes one `.env`
file and zero edits to the vhost — the same test every registry in this repo has to pass.

---

## 3. Why a template and NOT two files (deliberate divergence from datsme_me)

`datsme_me/deploy/` keeps `nginx.production.conf` + `nginx.staging.conf`. The repo-wide default
is to reuse an existing sibling pattern, so this divergence needs a semantic reason, and it has
one:

- **datsme's two files encode a real topology difference** — prod proxies to docker service
  names (`datsme-backend:19994`), staging to the host bridge (`172.18.0.1:29994`), and staging
  carries websocket plumbing prod lacks. Two files describe two genuinely different things.
- **DatsPet's would encode nothing.** Identical topology; **3 values** differ. Two files would
  be ~90% duplication with no semantic difference behind it.
- **And the duplication has already failed here.** The drift in §0 (staging missing the cache
  fix) is exactly what two lookalike files produce. Copying the pattern would commit that
  failure mode to git rather than remove it — the difference is only that it would be visible.
- datsme's own 17-line drift is the empirical result of the pattern, not a hypothetical.

Consistency loses to the "same reason → same place" rule here. **Revisit if** DatsPet's
environments ever diverge structurally (different proxy topology, an env-only location block);
at that point two files stop being duplication and start describing two things.

---

## 4. The `$` collision (the one real trap)

An nginx conf is **full of `$`**. A naive `envsubst < template` blanks **all 8** of nginx's own
variables — `try_files $uri $uri.html` becomes `try_files` — producing a conf that may still
pass `nginx -t` while behaving wrongly.

Two acceptable resolutions; **pick @@ placeholders**:

- **`@@NAME@@` placeholders + `sed`.** No collision possible, by construction. The template is
  greppable for un-rendered placeholders. Preferred: it cannot be got wrong later by someone
  who doesn't know about the allow-list.
- `envsubst '${SERVER_NAME} ${BACKEND_PORT} ${ZONE_PREFIX}'` — the allow-list form. Verified
  working (only listed vars substitute; `$binary_remote_addr`/`$uri` survive). Correct, but a
  future edit that drops the allow-list silently destroys the conf.

**Renderer must fail closed:** after rendering, `grep -q '@@' && exit 1`. An unsubstituted
placeholder must never reach `nginx -t`.

---

## 5. Build steps

1. **Extract the template.** `deploy/nginx-site.conf.template` from today's
   `deploy/nginx-default.conf` (which already carries the `/design` 307 and the cache fix),
   replacing the 7 sites with `@@SERVER_NAME@@`, `@@BACKEND_PORT@@`, `@@ZONE_PREFIX@@`.
   Keep every comment — they are the incident record.
2. **Write the two target files** from §0's table.
3. **Write `render_nginx_conf.sh <production|staging>`** → stdout; unknown target → exit 2;
   any surviving `@@` → exit 1.
4. **Prove equivalence (§6 gate 1) — the whole point of the change.**
5. **Delete `deploy/nginx-default.conf`.**
6. **Update `deploy/CHECKLIST.md` A5**: "never `cp`, patch staging by hand" becomes "render for
   your target". Move the old A5 hazard text into §E's incident log — it stays as history, not
   as a live instruction.
7. **Update `deploy/README.md`** (its `cp` line) **and `CLAUDE.md`** (which currently warns that
   the repo conf is prod's — that warning becomes obsolete and must go, or it will mislead).

---

## 6. Gates (all must pass before rollout)

1. **Equivalence, byte-level.** This is the gate that matters — it proves the refactor changes
   nothing:
   ```bash
   diff <(deploy/render_nginx_conf.sh production) deploy/nginx-default.conf   # must be EMPTY
   diff <(deploy/render_nginx_conf.sh staging) /tmp/staging_live.conf         # ONLY the cache
                                                                             # fix should appear
   ```
   The staging diff is *expected* to be non-empty in exactly one way: staging is missing the
   cache fix (§0). Confirm the diff shows **that and nothing else** — no port change, no
   `server_name` change, no zone change. If anything else appears, the template is wrong.
2. **Syntax, both targets.**
   ```bash
   for t in production staging; do
     deploy/render_nginx_conf.sh $t > /tmp/$t.conf
     docker run --rm -v /tmp/$t.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t
   done
   ```
3. **Cross-wiring is impossible.** `deploy/render_nginx_conf.sh staging | grep -c 29954` → **0**.
   This is the landmine, gated.
4. **Fails closed.** Remove a target file's `BACKEND_PORT` → renderer exits non-zero, emits
   nothing usable.
5. **nginx's own variables survive.** `render_nginx_conf.sh production | grep -c 'binary_remote_addr'`
   → **2** (one per `limit_req_zone`); `grep -c 'try_files $uri $uri.html'` → **1**.
   *(Counts verified against today's conf 2026-07-15. Gate 1's byte-level diff subsumes this —
   it is here because it names the specific failure the `$` collision causes, which a diff
   reports but does not explain.)*

---

## 7. Rollout (config-only; no code, no rebuild, no backend restart)

**Staging first, and staging alone, until it is proven.** Both targets share the box; a bad
vhost is a site outage.

1. **Staging.** Back up `/var/www/datspet-staging/nginx-default.conf` → render → `nginx -t` →
   `docker restart datspet-staging-nginx` → `scripts/verify_deployment.sh https://pet-staging.datsme.me`.
   This **also lands staging's missing cache fix**, so expect verify's cache checks to flip
   from FAIL to PASS — that is the visible payoff.
2. **Confirm production is untouched**: `scripts/verify_deployment.sh https://pet.datsme.me --expect-max-poses 5`.
3. **Production**, only after staging is green: same shape, `datspet-nginx`, then verify prod
   **and** re-verify staging.
4. Rollback either target: restore the backup conf, restart that vhost. Seconds.

**Do not deploy this without a target-named go-ahead.**

---

## 8. Out of scope (real, adjacent, deliberately NOT bundled)

Each is separately worth doing; none is a prerequisite:

- **`deploy.sh <target>`.** Phase B of the checklist is still hand-typed, and hand-typed
  heredocs mangled the `/design` redirect once. This spec's target table is the natural input
  for it — build it after, and let it consume `deploy/targets/*.env`.
- **A fleet runtime gate.** Checklist A6 is still prose; it should be a script that submits a
  real job of the new shape to **every** node before the web tier deploys.
- **Rate-limit zone names.** `ZONE_PREFIX` exists only because staging's zones were renamed by
  hand. The two vhosts are **separate nginx containers**, so the zones almost certainly could
  not collide and the prefix may be unnecessary. **Do not investigate as part of this change** —
  preserve today's behaviour exactly, so the equivalence gate in §6 stays meaningful. Simplify
  later, as its own change, if ever.
