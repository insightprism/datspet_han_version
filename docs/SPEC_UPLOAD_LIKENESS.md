# SPEC — "That's my dog": making the upload door produce a recognisable pet

**Status:** proposed, 2026-07-23. **Rev.6 — implementation-ready.** Rev.5 made this standalone
(the AI left the plan, §8); Rev.6 fixes what a read against the running code turned up: the
isolation function's real name and call sites, a failure mode the table missed (the cutout can
*raise*), a guard-test suite that could not have run on this repo's no-GPU test gate, and the
artifact §4 actually has to judge. **Depends on nothing new** — no model, no API key, no
`SPEC_DATSPET_AI_ENGINE`.

**Amends:** `SPEC_PET_DESIGNER_FLOW` §3.5, §3.4. **Depends on:** `SPEC_STEP1_SOURCE_RAIL` §1.12.
**Repos touched:** `datsme-pet-factory_wu` — `web/`, `webui/`, `pet_factory/`, one pool handler.

Someone photographs their dog and says *make an animation out of it*. Today they get a generic
cartoon pet. This is what it takes to get *"that's Rufus"* — with the parts already on the box.

---

## 0. Two facts that decide the whole design

Both verified against the running pipeline before anything below was written.

### 0.1 Step 3 does not reinvent the animal — the still IS the pet

```python
"class_type": "WanFirstLastFrameToVideo",                              # factory.py:176
"inputs": { ..., "start_image": ["9", 0], "end_image": ["9", 0] }      # node 9 = the step-1 still
```

Wan 2.2 I2V receives the step-1 still as **both the first and last frame** of every loop. The
prompt it also gets is the **motion profile's** per-pose text — it drives *how the animal
moves*, not what it looks like.

> **Likeness is not lost in animation. It is decided entirely by one 1024 px image.** "Animate
> my dog" reduces to "make one picture look like my dog", and step 3 is innocent.

*(The endpoints are pinned; the ~15 frames between them are Wan's, rendered at 704² and packed
into 256² sheet cells. A collar survives that; "lighter feathering on the chest" does not — see
§3's third bullet on what the promise is.)*

### 0.2 The prompt currently argues with the photo

`subject = animal or "pet"` (`app.py:822`), and the client never sends `animal`. So every
uploaded photo is redrawn at 0.85 denoise against:

> *"a cute cartoon **pet**, exactly **pet**, side profile view, facing right, standing, rich
> saturated colors, simple flat shading, white background, storybook style"*

`_remix_prompt` repeats the subject **deliberately** — *"emphasizing the description twice helps
it win over the source's original colors"* (`factory.py:322`). That mechanism works exactly as
designed, and what it is currently winning **against** is the user's dog.

---

## 1. The finding this revision turns on

```python
def _remove_bg(img: Image.Image) -> Image.Image:     # factory.py:112
    from rembg import remove
    return remove(img.convert("RGB"), session=_rembg())   # birefnet, GPU, ~12× faster than CPU
```

**The tool for isolating an animal from a photograph is already installed, already
GPU-accelerated, and already used in this pipeline** — on the *output* frames, where the call is
already the exact shape §2.2 needs:

```python
a = _remove_bg(orig).convert("RGBA").split()[3]     # factory.py:353 — birefnet alpha matte
```

The upload path never touches it. All an uploaded photo gets is:

```python
def _prep_reference_image(src) -> Path:        # factory.py:294 — the whole function
    img = Image.open(src).convert("RGBA")
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    ...
```

Pad to a square on white. No segmentation, no crop.

> So a dog in the corner of a garden photo is padded and denoised at 0.85 with most of the
> latent being **grass** — while `make_pet_zip`'s own docstring states the precondition,
> *"show one animal, side profile, facing right"* (`factory.py:512-525`), and nothing in the
> pipeline moves toward it.

Rev.1–4 proposed a language model to *describe* the dog before anyone had tried removing the
lawn. **Fix the pipeline first; measure; then decide whether anything else is needed.**

---

## 2. Four levers, none of which need anything installed

| | Lever | Cost |
|---|---|---|
| **A** | **Send the noun.** The user's typed animal reaches the redraw prompt | ~1 line |
| **B** | **Isolate and crop the subject** before img2img, with `_remove_bg` | ~40 lines, worker-side |
| **C** | **Say what a good photo is**, at the moment it can be acted on | copy only |
| **D** | **Keep the rolls.** Every draw stays pickable instead of being thrown away | UI only, **zero extra GPU** |

**All four were chosen because they survive step 2.** That is the selection rule, not an
afterthought — see §3.

### 2.1 A — send the noun

The typed field is already on the page (`SPEC_STEP1_SOURCE_RAIL` §1.1), and the backend path
already exists and is documented:

> *"`animal` alongside an upload is a HINT ('what is this a photo of?'), not a second door"*
> — `_resolve_reference_door`, `app.py:706`, which routes `["upload","txt2img"] → "upload"`
> deliberately.

`drawFrom`'s upload branch (`Designer.tsx:170-177`, where `typedDraft` is already in scope at
`:63`) appends `animal` when the typed draft is non-empty. `exactly pet` becomes
`exactly golden retriever`.

**The user's own word is ground truth, not an inference.** No model can beat the owner at
naming their own dog, and the field is already on screen.

It recovers two more things for free:

- `surface=_resolve_typed_surface(animal) if animal else None` (`app.py:841`) means an uploaded
  pet currently gets **universal design axes only** — upload a dog and you silently lose the
  coat axis that typing "dog" would have given you.
- Step 2's redraw prompt takes `species = name.strip() or ref["description"]` (`app.py:966`),
  and an upload's description is `subject.lower()` — i.e. `"pet"`. **The noun is wrong in both
  redraws, and A fixes both.**

And it makes `ReferenceBox.tsx`'s header comment true at last: *"the left-hand 'or type any
animal' field already asks exactly that question, so a photo dropped here simply borrows it as
the redraw hint."* It never did. Putting that field on the page is what made the sentence
buildable.

**One product decision A forces, and a stale draft is worse than no draft.** The typed field is
*also* the typed door's own draw input, and `choose()` does not clear it on a new source — by
design (`SPEC_STEP1_SOURCE_RAIL` §5.1 lifts the draft so it survives a lock). So: type
`blue jay`, draw it, then drop a photo of a retriever, and A would send `animal="blue jay"` with
that photo. The prompt becomes *"a cute cartoon blue jay, exactly blue jay"* over a dog —
**actively worse than today's `"pet"`**, because `_remix_prompt` repeats the subject to make it
win (§0.2).

Guidance alone does not fix this: a line saying *"name the animal on the left"* does not tell
the user that the name currently there is wrong. **Echo the value**, so the mistake is
impossible to miss rather than merely possible to notice:

> `using "blue jay" — change it on the left`

Copy, not code, and not a second field — which `ReferenceBox`'s header comment already rejects
("two fields asking *which animal?* … were the same question wearing two hats"). Clearing the
draft on upload was considered and rejected: the flow this feature most wants to encourage is
*type the animal, then drop the photo*, and clearing would delete the word the moment it became
useful.

### 2.2 B — isolate and crop *(the main event)*

On the worker, for uploads only. **Two functions, not one** — the ML call and the geometry are
separated because the geometry is where the failure rules live, and they have to be testable
without a GPU (§7):

```python
def _remove_bg(img) -> Image.Image          # factory.py:112 — EXISTS. birefnet, GPU, ML
def _crop_to_subject(rgba) -> Image.Image   # NEW. Pure PIL: alpha bbox + margin + crop
```

`_crop_to_subject` returns the input **cropped to its alpha bbox plus ~8% margin**, or — in
every failure case — **the input unchanged**. It never composites and never pads: the existing
tail of `_prep_reference_image` already does both, so the fallback is "return the input" and the
caller's behaviour is then byte-identical to today by construction.

```python
def _prep_reference_image(src, *, isolate: bool = False) -> Path:
    img = Image.open(src).convert("RGBA")
    if isolate:
        try:
            img = _crop_to_subject(_remove_bg(img).convert("RGBA"))
        except Exception as e:
            # Never take out the upload door for a segmentation failure (§2.2 table).
            print(f"[pet_factory] subject isolation failed, using the raw photo: {e!r}", flush=True)
    # …today's composite-onto-white + pad-to-square, unchanged…
```

**What it buys:** the animal occupies the frame instead of a corner; the background is gone
before it can contribute to the latent; the result finally approaches `make_pet_zip`'s stated
precondition. On a typical phone photo this is the difference between redrawing *a dog* and
redrawing *a garden containing a dog*.

**And a synergy worth naming, because it may be the larger half of the effect:** the tail
composites onto **white**, and `_remix_prompt` already ends `"white background"`. Isolation does
not merely delete distractor pixels — it makes the entire non-subject latent *already the
target* the prompt is asking for.

**Failure handling is not optional** — segmentation fails on ambiguous images, and the model
itself can refuse to load:

| Case | Behaviour |
|---|---|
| Empty alpha (no subject found — a wall, a screenshot) | `_crop_to_subject` returns the input → today's pad-to-square. Never emit a blank |
| bbox below ~5% of frame area | Return the input — a 40 px crop upscaled to 1024 is worse than the original |
| bbox above ~95% of frame area | Return the input — the crop is a no-op, so skip the work |
| Two animals in frame | The mask spans both; the crop covers both. Better than the whole garden. Largest-connected-component selection is a later refinement, not this spec |
| **`_remove_bg` raises** | **Caught in `_prep_reference_image`, logged once, pad-to-square.** See below — this row is why the `try` exists |

> **Why the raise row is load-bearing.** `_rembg()` **raises** on a node that declares
> `PET_FACTORY_REQUIRE_GPU=1` whose CUDA provider failed to load (`factory.py:107-111`) — the
> 2026-07-21 pool-watchdog incident, where CPU birefnet blew the timeout. Today the upload door
> never touches rembg at all: the eager `_rembg()` init lives at build time (`factory.py:342`).
> **Lever B moves that dependency onto the upload door**, so on a misconfigured node — the exact
> `LD_LIBRARY_PATH` failure `CLAUDE.md` warns about — the door would regress from *works* to
> *hard-fails*. Catching it is what keeps B a strict improvement.
>
> The eager fail-fast at `:342` **stays where it is**. Ops must still learn about a bad node
> from the build path, which is where the incident actually bit; the upload door degrading
> quietly is the right behaviour *there* and the wrong behaviour *there*.

**On a CPU-only node** (`PET_FACTORY_REQUIRE_GPU` unset) `_rembg` keeps its graceful CPU
fallback. One cutout fits inside `pet_preview`'s 180 s timeout against a ~10 s warm redraw — but
it is the reason the isolate step runs **exactly once per upload** and never per-frame. (The
2026-07-21 incident was CPU birefnet across *every frame of every pose*; one call is a different
order of magnitude. Measure the actual CPU latency in Phase 2 rather than inheriting the number.)

**The cost nobody has priced yet: cropping spends resolution.** The client already downscales
uploads to 1024 px on the long edge (`prepareUpload.ts`), and the crop happens *after* that on
the worker. A dog occupying 30% of frame crops to ~300 px and is then loaded at 1024²
(`VHS_LoadImagePath`, `custom_width/height: 1024`) — a ~3× upscale of real detail.

The §3 argument says this should still win — at 0.85 denoise composition beats fidelity, and a
sharp garden is worth less than a soft dog — and the 5% floor catches the extreme. But the
**5–40% band is a genuine tradeoff that is asserted, not measured**, and Phase 2's corpus is
exactly where it becomes visible: include small-in-frame subjects deliberately and compare
against the uncropped render.

> **If it bites, the lever is upstream and cheap:** raise `prepareUpload.ts`'s `MAX_PX` for the
> upload door (1024 → 1536) so the crop has pixels to spend. That is a one-constant change on
> the client, and the server's 12 MB cap is nowhere near threatened at 1536 (§`SPEC_STEP1_SOURCE_RAIL`
> §1.10). Do **not** pre-emptively raise it — a 1536 px upload is ~2× the bytes for every user,
> including the majority whose subject already fills the frame.

**It must be opt-in, not sniffed.** `_prep_reference_image` is shared: `factory.py:436` uses it
for the img2img remix and `:444` for the as-is path, and **step 2's preview redraw runs over an
already-clean sprite** where a cutout is pointless work and a real risk of eating the subject.
The caller knows it holds a photograph; the function must not guess. So `isolate=True` is set on
exactly one path — `app.py`'s `door == "upload"` branch. This is the engine-vs-content rule
applied: no branching on where the image came from inside the renderer.

**Threading it, and the deployment gate.** The flag rides `render_design_still(...)` on the local
path — an additive keyword on a signature that already ends in optionals
(`description, reference_image=None, strength=None, seed=None`, `factory.py:450`) — and
`params["isolate_subject"]` on the pool path. **A new pool param is a hard contract change**:
`pet_preview_handler`'s `params_schema` sets `"additionalProperties": False`
(`pet_preview_handler.py:69`), so an unknown param is a 422, not a silent no-op. The handler
goes **v2 → v3** (`METADATA["version"]`, `:44`), and the flow spec records the lesson:
*"Omitting these two IS the v2 shape — it hard-fails 422 on a v1 node, which is why both nodes
must be v2 first"* (§10.1, quoted at `app.py:664`). So:

> **Build and validate on `PET_GEN_BACKEND=local` first** (direct call, dev box has the GPU),
> **then** roll the handler to the fleet, **then** enable the pool path. Same fleet gate as §10.1.

v3 ⊇ v2 for existing traffic (the new param is optional and defaults to today's behaviour), so
rollback is safe — but no `isolate_subject` traffic may ship until every node is v3.

### 2.3 C — say what a good photo is

The pipeline wants one animal, side-on, well lit. Nothing tells the user that.

Put it in the upload door's **pending** state — after a photo is chosen, before Draw is
pressed — because that is the moment it can be acted on: the door's header is still a button
that reopens the picker. It is also where §2.1's stale-draft risk is resolved, so it is **two
lines: one about the animal, one about the photo.**

| Typed draft | Line 1 |
|---|---|
| present | `using "blue jay" — change it on the left` (§2.1: echo it, don't merely point at it) |
| empty | `name the animal on the left for a closer match` |

> Line 2, always: `side-on, whole animal, good light works best`

Line 1 carries a correctness job and line 2 carries a quality job; collapsing them into one
sentence would bury the first behind the second at the moment it matters most.

Free, and it moves the **input distribution**, which dominates every downstream lever. Do not
put it on the closed door: `SPEC_STEP1_SOURCE_RAIL` §1.11 established that a door's description
must not morph, and the closed door is already three lines.

### 2.4 D — keep the rolls

Each press of **Draw again** currently replaces the box and the previous render is gone. The
user already paid ~10 s of GPU for it.

**Keep the last N (≈4) rolls as a thumbnail strip under the box; click one to make it the
base.** Re-rolling is already the natural response to a poor result (a new seed is the cheapest
lever in diffusion, and `_base_sprite` picks a fresh one per call) — this just stops throwing
away the good ones.

> **Best-of-N with the ground truth in the loop, at zero extra GPU cost.** Not "render 3 and
> charge everyone 30 s" — the user re-rolls at their own pace, and the candidates they already
> bought stay pickable. The owner is the correct judge of whether it looks like their dog.

**The backend is already done, which is why this is UI-only.** Every roll is its own reference
record: the PNG and its meta sit in `PREVIEW_DIR` under a fresh id, nothing deletes them on
re-draw, the janitor sweeps them at **24 h** (`TRANSIENT_MAX_AGE_S`, hourly), and
`/api/reference/{id}.png` already serves them owner-scoped. **D is "stop dropping the ids".**

Two rules it must state, because they belong to `designFlow.ts` — the reducer where "the
invalidation rules are the product":

- **The strip is source-agnostic.** It holds the last N *drawn references*, whichever door drew
  them. A typed "blue jay" and an uploaded dog sit side by side; they are both "things you drew,
  and might want back". Keying it per door would mean a re-roll silently emptied the strip.
- **Picking from the strip is a fill, not a new draw.** It reuses `referenceFilled` with the
  existing record — same seq bump, same invalidation of the preview and both locks. A picked
  roll must not be cheaper *in state* than a drawn one, or step 2 could stay locked against an
  outgoing base.

Applies to typed animals as well. Independent of A–C; it could ship on its own.

---

## 3. Why these four levers, and what is deliberately not fixed

**The selection rule: a lever only counts if it survives step 2's mandatory redraw.** Step 2 is
img2img at up to 0.9 (`app.py:967-975`), it mints a **new** reference (`source="design"`), and
step 3 animates *that* one as-is (`app.py:1238`, `remix_strength` always `None`).
`SPEC_STEP1_SOURCE_RAIL` §1.12 already used this to delete the faithful↔sprite chooser: at 0.9
the second pass wins outright, and photographic fidelity is *gone before anything is animated*.

A–D pass that test, and this is the whole reason they are the four:

- **A** rides `ref["description"]` straight into step 2's own prompt (`app.py:966`) — the noun
  is fixed in *both* redraws, not one.
- **B**'s gain is **composition**, not pixels. A well-framed dog on white redraws as a
  well-framed dog; a garden redraws as a garden. Framing survives a 0.9 denoise; fidelity does
  not.
- **C** moves the input distribution, which is upstream of everything.
- **D** puts the owner's judgement after the render, where no amount of denoise can erase it.

Earlier revisions proposed render paths that differed only in *how much of the photo's pixels
they preserved*. That is exactly the quantity §1.12 proved cannot reach the finished pet.

What remains unfixed:

- **The double redraw itself.** Folding design and likeness into one pass would remove a
  generation of drift and **breaks "what you locked is what gets designed"** — that trade
  deserves its own spec. Stated here so the ceiling is known: everything above improves the
  input to a lossy step it does not remove.
- **Orientation.** The prompt says *facing right*; a photo facing left fights it. There is no
  reliable non-model test for facing direction. The honest options are a user-facing **flip**
  toggle or leaving it — not a guess. Out of scope; noted so it is not mistaken for an oversight.
- **Photoreal likeness.** The deliverable is *"your dog, as a cartoon pet"* — breed, colour,
  markings, collar. Z-Image has no IP-Adapter, so visual identity is not available at any price
  in this pipeline; promise what it can keep. And note §0.1's packing chain: a red collar
  survives to a 256² sheet cell, chest feathering does not.

---

## 4. Measuring it — and why this is cheap

A fixed corpus of ~20 real pet photos: dogs, cats, a bird, a rabbit, deliberately including the
bad cases — dim indoor, 3/4 and head-on angles, two animals, a person holding the pet, animal
small in frame. Committed under `docs/corpus/upload_likeness/` (photos the author owns), so the
measurement is re-runnable rather than a one-off sitting.

**Each lever is independently checkable, and B's effect needs no animation at all:**

| Lever | The question | Artifact to judge | How |
|---|---|---|---|
| **B** | *Is the animal isolated and filling the frame?* | the **prepped still** (`_prep_reference_image` output) | Yes/no in a second, 20 images — no render, no GPU |
| **A** | Does naming the animal change the redraw? | the **step-1 reference** | Render with/without the noun, same seed |
| **A+B** | Is the pet recognisable? | the **step-2 output** — the `source="design"` record | Contact sheet, human judgement |
| **Final** | Does it animate cleanly? | the **built pet** | Animate only the finalists |

> **The A+B row judges the step-2 output, not the step-1 sprite, and that is not a detail.**
> Step 2's redraw is what actually gets animated (§3). Judging step 1's sprite would measure an
> artifact no user ever receives — the same error, one level up, that sent the AI scorer out of
> this spec.

> **This is the whole reason the AI scorer left the plan.** Rev.1–4 needed one because it was
> comparing three render *paths* across 20 photos and animating everything — ~60 animations.
> Here, B is verifiable from a still, so the measurement is an afternoon with a contact sheet,
> and the expensive step is reserved for the finalists.

The contact-sheet harness already exists in shape: `scripts/calibrate_design_axes.py`,
`animal_catalog/generate_candidates.py` → `promote_candidate.py`. Note what transfers and what
does not: those render **stills** (`render_design_still`) and that covers rows B, A and A+B. The
final row animates through `make_pet_zip` and has no precedent — budget it as new harness code
over a handful of finalists, not over the corpus.

---

## 5. Build order

| Phase | | Ships without |
|---|---|---|
| **1** | **A + C** — send the noun, add the pending-state line (which also resolves §2.1's field ambiguity) | anything else. Hours |
| **2** | **B (local)** — `_crop_to_subject`, `isolate=` on `_prep_reference_image`, wired through `render_design_still`, on `PET_GEN_BACKEND=local`. Guard tests (§7) land with it. Verify rows B/A/A+B against the corpus | the fleet |
| **3** | **B (pool)** — `isolate_subject` param → `pet_preview_handler` **v3** → roll to the fleet → enable. §10.1 fleet gate | — |
| **4** | **D** — the candidate strip | B |
| **5** | **Measure** (§4) end to end, then decide whether anything in §8 is warranted | — |

**Phase 1 is worth doing this week regardless of everything else.** One line on the client,
kills `exactly pet` in *both* redraws, recovers the coat axis, and makes a stale comment true.

**Sequencing note for Phase 4.** D lands in `designFlow.ts`, whose `referenceRequested` and
`baseUnlocked` cases are under active edit at the time of writing — and those are precisely the
transitions §2.4's two rules constrain. Land that work first, then build D on top of it; do not
develop the two in parallel against the same reducer.

---

## 6. Decisions

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Does step 3 need to change? | **No** | `start_image` *and* `end_image` are the step-1 still; step 3's prompt drives motion only (§0.1). Likeness is a one-still problem |
| 2 | Does this spec need AI? | **No — nothing new installed at all** | The isolation tool is already on the box and unused on input (§1). Fix the pipeline before adding a model |
| 3 | Where does the animal's name come from? | **The user's typed field** | Ground truth, already on screen, free. No inference can beat the owner naming their own dog (§2.1) |
| 3a | Two fields asking "which animal?" | **No — one field, and §2.3's line disambiguates it** | `ReferenceBox`'s header comment already rejected a second field; the pending-state line is on screen at the exact moment the question is live (§2.1, §2.3) |
| 4 | Does the cutout run on every reference? | **No — `isolate=True` on the upload path only** | `_prep_reference_image` is shared with step 2's preview, whose reference is already a clean sprite. The caller knows it holds a photo; the renderer must not sniff (§2.2) |
| 4a | One function or two? | **Two — `_remove_bg` (ML, exists) + `_crop_to_subject` (pure PIL, new)** | The failure rules live in the geometry and are the part most likely to be wrong. A pure function makes all four of them testable with no GPU and no ML import, which this repo's test gate requires (§7) |
| 5 | What if segmentation finds nothing? | **Return the input unchanged → today's pad-to-square** | An empty or 5%-of-frame bbox must never produce a blank or a 40 px upscale. "Return the input" also makes the byte-identity guard true by construction (§2.2) |
| 5a | What if the cutout **raises**? | **Catch, log once, pad-to-square** | `_rembg()` raises on a GPU node whose CUDA provider failed to load (`factory.py:107-111`, the 2026-07-21 watchdog incident). B puts rembg on the upload door for the first time; without the catch, a misconfigured node turns a working door into a broken one (§2.2) |
| 5b | Does the build path keep its eager fail-fast? | **Yes, unchanged at `factory.py:342`** | Ops must still learn about a bad node loudly, from the path where the incident bit. Degrade quietly on the door; fail fast on the build |
| 6 | Can B ship straight to prod? | **No — local first, then the fleet, then the pool path** | `params_schema` sets `additionalProperties: false`, so a new param is a hard 422 on a v2 node. Handler goes v2 → v3; §10.1's fleet gate exists for exactly this (§2.2) |
| 7 | Best-of-N? | **Yes — by keeping rolls, not by rendering 3 up front** | The user re-rolls anyway; the candidates are already paid for. Zero extra GPU, and the owner is the right judge (§2.4) |
| 7a | Is the roll strip per-door? | **No — source-agnostic, last N drawn references** | A per-door strip would empty itself on a re-roll from the other door. It holds "things you drew and might want back" (§2.4) |
| 8 | Is the promise "your dog"? | **"Your dog, as a cartoon pet"** | Z-Image has no IP-Adapter; semantic identity is deliverable, visual identity is not (§3) |
| 9 | How is success measured? | **Contact sheet; B from the prepped still, A+B from the step-2 output, animation only for finalists** | Cheap because the levers are independently visible — but the recognisability row must judge what actually gets animated (§4) |
| 10 | Where does AI go? | **After §5's measurement, if a gap remains** — §8 | If B alone closes it, none of it is needed |

---

## 7. Guard tests

**All of these run on the standard `pytest pet_factory/tests webui/tests` invocation — no GPU,
no rembg, no onnxruntime.** That is the point of §2.2's split: `_crop_to_subject` is pure PIL,
so its fixtures are synthetic RGBAs whose alpha channel is authored by hand, and the ML import
stays inside `_remove_bg`/`_rembg` where it already is.

Against `_crop_to_subject` (pure, no ML):

| Fixture (alpha authored by hand) | Expected |
|---|---|
| Opaque 100×100 subject in the corner of a 1000×1000 transparent field | Returns a crop whose subject bbox is ≥ ~80% of the result's area |
| Fully transparent alpha | Returns the input **unchanged** (identity, not a copy-equal) |
| Opaque subject covering ~3% of frame area | Returns the input unchanged |
| Fully opaque alpha | Returns the input unchanged |
| Subject touching the frame edge | Margin clamps to the bounds; no crash, no black border |

Against `_prep_reference_image`:

- With no `isolate` argument it behaves **byte-identically** to today. This is what lets Phase 2
  ship without re-verifying step 2's preview path, and it is the test that fails loudest if
  someone later makes isolation the default.
- With `isolate=True` and `_remove_bg` monkeypatched to raise, the output is byte-identical to
  `isolate=False` — the §2.2 catch, exercised without a GPU.
- With `isolate=True` and `_remove_bg` monkeypatched to return a hand-authored RGBA, the output
  is square, white-backed, and the subject fills it.

And the standing gate, unchanged:

- `webui/` and `pet_factory`'s data subpackages import with **numpy absent**. The cutout is
  worker-side; B must not leak an ML import into the web tier.

Pool-side, one contract test with no fleet required:

- `pet_preview_handler`'s `params_schema` accepts `isolate_subject` and still rejects an unknown
  key — i.e. `additionalProperties: false` survived the edit, and `METADATA["version"]` is `"3"`.

---

## 8. Where AI could help — later, and only on evidence

Nothing in this section is proposed for build. It is recorded so the sequence is deliberate:
**ship §5, measure §4, and then ask whether a model adds anything the pipeline did not.**

If the measurement shows the gap is closed, this section stays unbuilt — that is a success, not
an omission.

If a gap remains, the candidates, in the order their value is provable:

1. **A scorer in the harness** (`SPEC_DATSPET_AI_ENGINE` + a `likeness_score` purpose). Its
   value is highest where **there is no user in the loop** — sweeping a corpus after every
   prompt change, which a human sitting cannot do repeatably. Note this is a *tooling* use, not
   a product feature, and it is the one use §2.4 does not displace: the candidate strip puts the
   owner in the loop at runtime, and the owner is a better judge of their own dog than any model.
   *(If it is ever built: `likeness_score` takes **two** images, and
   `SPEC_DATSPET_AI_ENGINE` §4's `call_purpose(..., image=…)` takes one. That signature has to
   widen before the purpose can exist — a real edit to that spec, not a contribution under it.)*
2. **A captioner for the empty case** — only when the user uploads a photo and types nothing.
   With A shipped, the population that needs it is whoever declined to type one word, and the
   cheaper fix may simply be asking them.
3. **Everything else** — per-photo render-path selection, automated retry ladders, quality
   gates — is downstream of 1 and 2 and should not be designed before them.

**The rule that sends AI to the back of this spec:** the pipeline had an unused segmentation
model, a documented precondition nothing enforced, and a prompt naming the wrong animal. A
language model on top of that would have been measuring a problem the pipeline was creating.
