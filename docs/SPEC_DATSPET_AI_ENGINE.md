# SPEC — DatsPet AI Engine (model catalog + purpose registry)

**Status:** proposed, 2026-07-23. **Rev.2** — separated from its first consumer (§0.1).
**Adapts:** `datsme_me` `api/apps/ai_engine/` — the design concept, not the code.
**Repos touched:** `datsme-pet-factory_wu` (`webui/` + two data subpackages). No GPU, no pool handler.

**A standalone feature.** It ships, is guard-tested, and is demonstrable in the admin UI on its
own — with **no pet-specific knowledge in it at all**. It must be deliverable and mergeable
whether or not any consumer is ever built.

> **Sequencing (2026-07-23): this is no longer next.** `SPEC_UPLOAD_LIKENESS` Rev.5 removed its
> dependency on AI entirely — the pipeline already owns an unused segmentation model
> (`_cutout`, `factory.py:115`), a documented precondition nothing enforced, and a prompt naming
> the wrong animal. Those get fixed first and measured. **This engine is built when a consumer
> has a measured need for it** — the likeliest first one being a harness scorer for sweeping a
> corpus where no user is in the loop (`SPEC_UPLOAD_LIKENESS` §8). Nothing in this spec changes;
> only its position in the queue.

DatsPet is about to make its first LLM call. This decides whether that call is a hard-coded
`client.messages.create(...)` buried in the upload path, or an addressable **purpose** whose
model and prompt are configuration.

### 0.1 The boundary — and where Rev.1 put it wrong

Rev.1 named `image_triage` and `pet_likeness` as the engine's "launch purposes". **That was a
leak**: those are pet content, and an engine that ships knowing what a *coat pattern* is has
already broken the rule the rest of this repo is built on — *runtime code never branches on
which variant produced a record; variants are data files plus a registry entry.*

| | Owns | Changes when |
|---|---|---|
| **This spec** (engine) | the model catalog, the purpose *schema + validator*, dispatch, usage, admin | a model is released or retired; a provider changes its API |
| **A consuming feature** | its own purpose files — prompt, schema, tier | the product question changes |

Those two change for entirely different reasons, so they live in different places. The engine
never imports `animal_catalog`, never mentions a species, and has no opinion about pets. A
feature contributes purpose files the way an animal contributes a `base.png` — and adding one
must not modify the engine.

**Dependency direction is one-way and enforced by a guard test** (§11): a consumer imports the
engine; the engine imports nothing from a consumer.

---

## 0. What the DatsMe AI Engine actually is

Read from `datsme_me/api/apps/ai_engine/` rather than from the admin screenshots, because the
screenshots hide the most important fact:

> **The model catalog is a self-validating *code file*, not a database table.** Only the
> *purpose* rows live in the DB. `model_catalog.py` opens: *"one file, every fact about every
> model… Adding, deprecating, or removing a model is a single-file edit. The catalog validates
> itself at import time — a malformed catalog raises CatalogError and the app refuses to start."*

That is **exactly** this repo's registry pattern — `motion_profiles/registry.json`,
`animal_catalog/catalog.json`, `tiers/tiers.json`, `design_axes/registry.json`: one data file,
one guard test, adding a variant never touches the consumers. The AI Engine is not a foreign
architecture being imported; it is the pattern DatsPet already uses four times, applied to
models and prompts.

Three pieces, and DatsPet wants all three:

| Piece | What it buys |
|---|---|
| **Model catalog** | Model churn becomes a one-file edit with a lifecycle (`draft → available → deprecated → retired`), a required `replacement_id`, and cost per model |
| **Purpose registry** | Each AI usage is a named purpose owning its own model, prompts, and params — *"Configure AI provider, model, and prompts for each platform feature independently"* |
| **Usage log** | Calls / tokens / est. cost, per purpose. The admin panel's `29 calls · 17,266 tokens · $0.0218` |

---

## 1. The correction that matters most

**Do not carry `temperature` into DatsPet's purpose registry.**

DatsMe's `AIPurpose` rows store `temperature` and `ai_purpose_service` passes it through
(`temperature = float(purpose.temperature)`; `_call_anthropic_with_image` hard-codes `0.1`).
That was correct when written. **It is now a 400 on every model DatsPet would choose** —
`temperature`, `top_p` and `top_k` were removed on Opus 4.8/4.7, Sonnet 5 and Fable 5.

A faithful copy of the purpose schema would ship a config field whose only effect is to break
every call. Steering that used `temperature` moves into the prompt, which is already the thing
the purpose registry makes configurable.

**Second correction: prompt-and-parse → structured outputs.** `describe_file` asks for JSON in
the prompt and parses the text back out. DatsPet's purposes declare a **JSON schema** and the
API guarantees the shape (`output_config.format`, or `messages.parse()` with a Pydantic model).
That deletes the parse-and-repair path, and it is what makes a purpose's *output* contract
reviewable next to its prompt.

> Both are why this is an **adaptation**, not a port. The design concept is right and a year
> old; two of its implementation details have expired.

---

## 2. The model catalog — `pet_factory/ai_models/`

A data subpackage beside `tiers/` and `design_axes/`, importable with **no ML dependencies**
(the GPU-less posture: `webui/` may import it freely).

```jsonc
// catalog.json — one entry per model, every fact in one place
{
  "models": [
    { "id": "claude-opus-4-8", "label": "Claude Opus 4.8", "provider": "anthropic",
      "tier": "capable", "status": "available", "vision": true,
      "cost_per_mtok": { "input": 5.00, "output": 25.00 },
      "default_for_tiers": ["capable"] },

    { "id": "claude-sonnet-5", "label": "Claude Sonnet 5", "provider": "anthropic",
      "tier": "balanced", "status": "available", "vision": true,
      "cost_per_mtok": { "input": 3.00, "output": 15.00 },
      "default_for_tiers": ["balanced"] },

    { "id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "provider": "anthropic",
      "tier": "fast", "status": "available", "vision": true,
      "cost_per_mtok": { "input": 1.00, "output": 5.00 },
      "default_for_tiers": ["fast"] }
  ]
}
```

**The lifecycle is the point, and it earns its keep with one purpose.** Models churn on their
own schedule regardless of how many features you have — DatsMe's catalog already carries a
retired `gpt-4` family and a `claude-sonnet-4` deprecated with a date, kept so historical usage
rows still price. A `status` + `replacement_id` pair turns "this model is going away" from a
grep across the codebase into a one-line edit that the guard test enforces.

**Guard test** (`pet_factory/tests/`), mirroring DatsMe's import-time validator and this repo's
existing registry guards — the build fails on a half-formed entry:

| Rule | |
|---|---|
| 1 | Every `id` unique; every `provider`/`tier`/`status` in its closed set |
| 2 | Only `status: "available"` may appear in `default_for_tiers` |
| 3 | Every tier named by a purpose has exactly one default |
| 4 | `deprecated`/`retired` **must** carry a `replacement_id` that resolves |
| 5 | `cost_per_mtok` present and positive on every entry — usage rows must always price |
| 6 | Any model referenced by a purpose exists and is not `retired` |
| 7 | A purpose whose input includes an image resolves to a model with `vision: true` |

Rule 7 has no DatsMe equivalent and is DatsPet-specific: every purpose here is image-shaped, so
a text-only model is a build error rather than a runtime surprise.

---

## 3. The purpose registry — `pet_factory/ai_purposes/`

One JSON per purpose + `registry.json`, exactly like `design_axes/`. **Data, not a DB table** —
DatsPet's `tiers/` precedent (*"the entitlement table is data; `default_tier` is the one-line
launch lever"*) applies unchanged, and it keeps the whole engine importable on the GPU-less
web tier with no migration.

```jsonc
// ai_purposes/pet_likeness.json
{
  "purpose_key": "pet_likeness",
  "display_name": "Pet likeness from a photo",
  "description": "Turns an uploaded photo into the structured description the redraw prompt needs.",
  "tier": "capable",                 // resolved through the catalog, not a pinned model id
  "max_tokens": 512,
  "input": "image",
  "system_prompt": "You identify animals in photographs for a cartoon-pet generator. …",
  "user_prompt_template": "Describe this animal.{hint_clause}",
  "output_schema": { "type": "object", "properties": { "species": {"type": ["string","null"]}, … },
                     "required": ["species"], "additionalProperties": false },
  "is_active": true
}
```

Four properties carried over from DatsMe, each load-bearing:

- **`tier`, not a pinned model id.** A purpose asks for *capable*; the catalog answers with the
  current model. Model swaps stay one edit in one file.
- **Prompts are templates.** `{hint_clause}` is filled at call time — the same mechanism as
  DatsMe's `website_agent`, whose `{name}/{bio}/{tags}` let an admin own the wording globally
  while each site injects its identity. Here it lets the engine stay ignorant of *which* animal.
- **`output_schema` is part of the purpose**, per §1 — the contract lives next to the prompt
  that has to satisfy it.
- **`is_active`** — a purpose can be switched off without a deploy.

Deliberately **not** carried over: `temperature` (§1), `credit_cost` (DatsPet has no credit
ledger — DatsMe's is the host's), `user_overridable` (§7).

*(The `pet_likeness.json` above is shown as an **illustration of the schema**. It is not part of
this spec's deliverable — it belongs to `SPEC_UPLOAD_LIKENESS`, per §0.1.)*

### 3.1 The engine ships exactly one purpose, and it is about the engine

`ai_purposes/connectivity_check.json` — `tier: "fast"`, a two-token prompt, no image. It exists
so the admin's **Test configuration** button has something to call: install a key, press it, and
watch a real row land in the usage table with real tokens and a real cost.

That is the whole point of the split. The engine is **end-to-end demonstrable with zero product
features built** — key → admin → test → usage row. A feature that later contributes
`pet_likeness.json` inherits a path that has already been proven live.

It also keeps the registry honest: `connectivity_check` is genuinely engine-owned (it tests the
engine), so the engine ships with a working instance without smuggling in a product concern.

---

## 4. One dispatch path — `webui/ai_engine.py`

```python
def call_purpose(purpose_key: str, *, image: bytes | None = None,
                 media_type: str | None = None, variables: dict | None = None) -> tuple[dict, Usage]
```

Mirrors `call_ai_purpose_with_usage`'s shape (purpose key in, `(result, usage)` out) at
DatsPet's scale. It resolves the purpose → resolves the tier through the catalog → fills the
templates → calls Anthropic with `output_config.format` → records usage → returns the validated
object.

- **Web tier only.** No GPU, no ML packages, one HTTPS call — the posture `CLAUDE.md` calls
  load-bearing. `pool_client.py` is the precedent: one adapter that owns one backend's URLs.
- **Copy DatsMe's proxy handling verbatim.** `_call_anthropic_with_image` strips a `socks://`
  `https_proxy` and passes `trust_env=False` into its own `httpx.Client`. That is a debugged
  environment fact, not a style choice.
- **`DATSPET_AI_API_KEY` unset ⇒ the whole engine is inert** and `call_purpose` raises a typed
  `AIUnavailable` that every caller degrades on — the standalone-first posture
  `datsme_integration.py` already uses for `DATSME_HMAC_SECRET`.
- **Model: `claude-opus-4-8`** for `capable`, `claude-haiku-4-5` for `fast`. Not
  cost-downgraded by default — that is an admin decision, and the tier indirection is what makes
  it a one-line one.

---

## 5. Usage — the one genuinely stateful piece

A table in `db.py` (SQLite, `time.time()` floats per that file's convention), append-only per
this repo's ledger rule — a re-run is a new row, never an UPDATE:

```
ai_usage(id, ts, purpose_key, model_id, input_tokens, output_tokens, ok, error_code, external_user_id)
```

Cost is **derived at read time** from the catalog's `cost_per_mtok`, never stored. Storing a
computed price freezes it at the moment of the call and makes a pricing correction unfixable;
catalog rule 5 guarantees historical rows always price, which is why DatsMe keeps retired
families in its catalog at all.

`external_user_id` follows `db.py`'s existing identity scoping — a WHERE clause, never an
engine fork.

---

## 6. Admin surface — `webui/ai_admin.py`

The third admin router, following `motion_admin.py` and the design-axes admin exactly:
`APIRouter(prefix="/api/admin/ai", dependencies=[Depends(require_admin_launch)])`, the
adm-claim cookie, `admin_common.writable()` gating, and the audit `print`.

**The rule those two established and this one inherits:** the admin writes through *the same
validator the guard test uses*, so the admin cannot save a configuration the build would reject.

Surfaces, mirroring the screenshots at DatsPet's scale:

- **Purpose registry** — per purpose: tier, max_tokens, prompts, active. Editable.
- **Model catalog** — **read-only**, with status and cost. A catalog edit is a code change with
  a guard test; exposing it to runtime CRUD is how the two get out of sync.
- **Usage** — calls / tokens / est. cost, by purpose, over a window.

A fourth tab on the existing admin UI (`web/src/app/admin/`, which already has `design` and
`motions`).

---

## 7. What is deliberately NOT adopted

| DatsMe has | DatsPet | Why |
|---|---|---|
| Postgres-backed purpose rows | **JSON data files** | Matches `tiers/`, `design_axes/`. No migration, importable on the GPU-less tier, diffable in review. DatsMe needs DB rows because its admin edits at runtime across many purposes; DatsPet's admin can write files through the validator, as `motion_admin` already does |
| `credit_cost` per purpose | **dropped** | DatsPet has no credit ledger; DatsMe's belongs to the host |
| `user_overridable` + per-user model + "use my own API key" | **dropped** | That exists because DatsMe users own a personal agent and may bring a key. DatsPet has one platform key and no per-user settings surface. Note DatsMe already gates it: `website_agent` is **not** overridable because *"a visitor must not be able to fork the model/provider of the published agent"* — the same reasoning makes every DatsPet purpose platform-controlled |
| `temperature` | **dropped** | §1 — a 400 on every current model |
| Three providers + a 3-arm dispatcher | **`provider` is a catalog field; one dispatch arm** | The field is a *fact about a model*, so it stays. Building an unused dispatcher for providers with zero entries is the single-element abstraction `CLAUDE.md` forbids. A second provider arrives as a new arm plus catalog entries — and *that* is the moment to ask whether the engine should stop branching on provider and register them instead |
| `catalog_scheduler.py`, `ai_usage_rollup.py` | **dropped** | Rollup jobs for a platform with orders of magnitude more traffic. A `GROUP BY` over the usage table answers the same question here |
| purposes bundled with the engine | **contributed by features** | §0.1. DatsMe seeds its purposes centrally because it *is* the platform; DatsPet's engine is a component inside one, and a component that knows its callers is not reusable |

---

## 8. Reconciling with "three instances before consolidating"

`CLAUDE.md` says: *"Do not build a registry/engine/abstraction until at least three concrete
instances with visible variation exist. Single-element abstractions usually mismatch the
2nd/3rd element's actual shape."* This engine ships with **one** purpose (§3.1). Address it
directly rather than hoping nobody checks:

- **The rule's stated reason does not apply here.** It exists because a single-element
  abstraction is *guessed* — you cannot see the shape the 2nd and 3rd elements will need. This
  shape is not guessed: DatsMe runs **five-plus purposes against it in production**
  (`personal_agent`, `website_agent`, `news_scoring`, `file_description`, …), and the fields
  that survived that — tier indirection, prompt templates, `is_active`, the status lifecycle —
  are observable, not hypothetical. The evidence the rule asks for exists; it was gathered in
  the sibling repo, which is why this spec could be written by reading code instead of guessing.
- **The catalog clears the bar on its own.** It holds N models from day one and solves model
  *churn*, which happens on the vendors' schedule no matter how many purposes consume it.
- **Separating the engine from its consumers (§0.1) is what makes the count irrelevant.** The
  engine is not an abstraction over two known things — it is a component with a schema, a
  validator and one self-test. Features arrive later and are judged on their own merits; if
  `SPEC_UPLOAD_LIKENESS` is never built, nothing here becomes dead code, because the catalog and
  the admin still do their job.
- **The alternative is not "no abstraction."** It is a model id and a prompt hard-coded in the
  upload path — which this repo's engine-vs-content rule forbids independently.

**And the corrections in §1 are the rule working.** Adopting a shape without re-deriving it is
how you inherit a `temperature` field that 400s. Two of DatsMe's field choices did not survive
review against current models — which is the strongest evidence that this is an adaptation and
not a copy.

---

## 9. Files and build order

| Phase | | |
|---|---|---|
| **1** | `pet_factory/ai_models/` — `catalog.json`, `__init__.py` (`resolve(tier)`, `entry(id)`, `price(...)`), guard test | No API calls; pure data |
| **2** | `pet_factory/ai_purposes/` — `registry.json`, the purpose **schema + validator**, `connectivity_check.json`, guard tests (incl. catalog rules 6–7 and the no-back-import rule) | Still no API calls |
| **3** | `webui/ai_engine.py` — `call_purpose()`, proxy handling, `AIUnavailable`, structured outputs | First live call; key unset ⇒ inert |
| **4** | `db.py` — `ai_usage` table; record on every call | |
| **5** | `webui/ai_admin.py` + admin tab, incl. **Test configuration** | **The engine is DONE here** |

**Phases 1–5 are the entire deliverable.** No pet feature is required to finish, review, or
merge this spec — the acceptance test is: install a key, open the admin tab, press **Test
configuration**, see a usage row with real tokens and a derived cost.

Phases 1–2 ship **without an API key** and are fully guard-tested, so the data half is
verifiable before a single token is spent.

**Consumers are separate specs and separate PRs.** `SPEC_UPLOAD_LIKENESS` contributes
`image_triage.json` + `pet_likeness.json` and calls `call_purpose(...)` from the upload path;
that work does not appear in this build order and does not gate it.

---

## 10. Decisions

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Copy `ai_engine/` or adapt it? | **Adapt the concept** | ~3,600 lines coupled to Postgres, a credit ledger and a usage-rollup scheduler. The *shape* is what transfers (§0) |
| 2 | Catalog in a DB or a file? | **File** — and this matches DatsMe, whose catalog is also code | Self-validating at import, one-file edits, guard-tested. Matches four existing DatsPet registries |
| 3 | Purposes in a DB or files? | **Files** | No migration, GPU-less-safe, diffable. The admin writes through the guard-test validator, as `motion_admin` already does |
| 4 | Keep `temperature`? | **No — it 400s** on Opus 4.8/4.7, Sonnet 5, Fable 5 (§1) | Copying it ships a config field that breaks every call |
| 5 | Prompt-and-parse or structured outputs? | **Structured outputs**, schema declared on the purpose | Deletes the parse-and-repair path; makes the output contract reviewable beside the prompt |
| 6 | Pin a model per purpose, or a tier? | **Tier**, resolved through the catalog | A model swap stays one edit in one file |
| 7 | Per-user model / own API key? | **No** | No per-user settings surface, one platform key. DatsMe itself locks this off for its platform-controlled purpose |
| 8 | Credits? | **No** | DatsPet has no ledger; DatsMe's is the host's |
| 9 | Multi-provider dispatcher? | **`provider` is a catalog field; one arm** | A dispatcher for zero other entries is the abstraction `CLAUDE.md` forbids (§7) |
| 10 | Store computed cost on usage rows? | **No — derive at read time** | A stored price freezes at call time and makes a correction unfixable. Catalog rule 5 guarantees old rows still price |
| 11 | One purpose vs "three instances"? | **Build it** — §8 | The shape is observed in production next door, not guessed. The catalog clears the bar alone, and separating the engine from its consumers makes the count irrelevant |
| 12 | Where does it run? | **Web tier, HTTPS** | No VRAM against Wan, no per-worker install, fits the GPU-less prod posture |
| 13 | Do the pet purposes ship with the engine? | **No — features contribute them (§0.1)** | They change for a different reason (the product question) than the engine does (a model is retired). An engine that knows what a coat pattern is has broken the rule the rest of this repo is built on |
| 14 | Is this spec deliverable without any pet feature? | **Yes, and that is the acceptance test** | Key → admin → **Test configuration** → a usage row. If `SPEC_UPLOAD_LIKENESS` is never built, nothing here becomes dead code (§9) |
| 15 | Can a consumer import engine internals? | **No — `call_purpose()` + its typed errors are the whole surface** | Guard-tested both ways (§11). A consumer reaching past the seam re-couples what §0.1 separated |

---

## 11. Guard tests

Same posture as `motion_profiles` and `design_axes` — the build fails on a half-formed entry:

- Catalog rules 1–7 (§2).
- Every purpose's `tier` resolves; `output_schema` is valid JSON Schema with
  `additionalProperties: false` (a structured-outputs requirement, so this is a real gate).
- Every `{placeholder}` in a `user_prompt_template` is supplied by its caller — the failure mode
  is a prompt that silently ships the literal `{hint_clause}` to the model.
- The registry's purpose list matches the files on disk, both directions.
- **`webui/` and both data subpackages import with numpy absent** — the existing GPU-less gate,
  extended to the new packages.
- **The seam holds, both directions** (§0.1) — the test that keeps this a separate feature
  rather than a folder:
  - `ai_models/` and `ai_purposes/` import nothing from `animal_catalog`, `design_axes`,
    `motion_profiles`, `tiers`, or `webui`. A back-import is the boundary dissolving.
  - `webui/ai_engine.py` names no purpose key: every key reaching it is a caller's argument.
    A literal `"pet_likeness"` anywhere in the engine fails the build.
  - The engine's own package contains exactly one purpose file, and it is `connectivity_check`.
