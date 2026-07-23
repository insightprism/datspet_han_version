# SPEC — "That's my dog": making the upload door produce a recognisable pet

**Status:** proposed, 2026-07-23. **Rev.7 — the captioner comes back, as a consumer.** Rev.5
sent the AI out of the plan ("fix the pipeline first, measure, then decide"); Phases 1–2 shipped
and a real uploader's parakeet — redrawn as a mammal because the noun field was empty — supplied
the evidence §8 asked for. So AI returns as **lever E / Phase 2.1 (§2.5): automate the noun.** It
does not fold the AI engine into this spec — `SPEC_DATSPET_AI_ENGINE` stays a **separate** spec
that this one merely consumes (two purposes + one call site). Rev.6 remains the record of the
code-accurate corrections (the isolation function's real name, the raise-failure row, the no-GPU
guard suite).

**Dependency is per-phase.** **Phases 1, 2, 3 depend on nothing new** — no model, no API key.
**Phase 2.1 (E) depends on `SPEC_DATSPET_AI_ENGINE`** (built, and on `DATSPET_AI_API_KEY`); with
the key unset, E is inert and the upload door is exactly Phase 1.

**Amends:** `SPEC_PET_DESIGNER_FLOW` §3.5, §3.4. **Depends on:** `SPEC_STEP1_SOURCE_RAIL` §1.12;
**and — for Phase 2.1 only — `SPEC_DATSPET_AI_ENGINE`.**
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

## 2. The levers

| | Lever | Cost |
|---|---|---|
| **A** | **Send the noun.** The animal named in the upload door's own field reaches the redraw prompt | ~1 line |
| **B** | **Isolate and crop the subject** before img2img, with `_remove_bg` | ~40 lines, worker-side |
| **C** | **Say what a good photo is**, at the moment it can be acted on | copy only |
| **D** | **Keep the rolls.** Every draw stays pickable instead of being thrown away | UI only, **zero extra GPU** |
| **E** | **Automate the noun.** AI reads the photo, names the animal, and fills A's field for the user | the AI engine (a **separate** spec) + 2 purposes + 1 call site |

**A–D need nothing installed** — that is the discipline of §1: fix the pipeline before adding a
model, and A–D do exactly that. **E is the one that crosses that line, deliberately, on the
evidence §8 required** — a real uploader's parakeet redrew as a generic mammal because A's field
was left empty (the whole point of the upload door is that you shouldn't have to type what the
photo plainly shows). E does not replace A; it **automates** A, filling the same field. So E
inherits A's slot and survives step 2 for the same reason A does (§3).

**All of A–D were chosen because they survive step 2** — that is the selection rule, not an
afterthought (§3).

### 2.1 A — send the noun

The typed field is already on the page (`SPEC_STEP1_SOURCE_RAIL` §1.1), and the backend path
already exists and is documented:

> *"`animal` alongside an upload is a HINT ('what is this a photo of?'), not a second door"*
> — `_resolve_reference_door`, `app.py:706`, which routes `["upload","txt2img"] → "upload"`
> deliberately.

`drawFrom`'s upload branch appends `animal` when the upload door's noun field is non-empty.
`exactly pet` becomes `exactly golden retriever`.

**The user's own word is ground truth, not an inference.** No model can beat the owner at
naming their own dog.

It recovers two more things for free:

- `surface=_resolve_typed_surface(animal) if animal else None` (`app.py:841`) means an uploaded
  pet currently gets **universal design axes only** — upload a dog and you silently lose the
  coat axis that typing "dog" would have given you.
- Step 2's redraw prompt takes `species = name.strip() or ref["description"]` (`app.py:966`),
  and an upload's description is `subject.lower()` — i.e. `"pet"`. **The noun is wrong in both
  redraws, and A fixes both.**

**Where the field lives — reversed on evidence (decision 3a).** The first build of A shipped
**no field on the upload door**: the noun was borrowed from the "type any animal" door across
the page, on the theory (`ReferenceBox`'s old header comment) that two "which animal?" fields
were "the same question wearing two hats." A real uploader disproved it — they read the two
doors as *unrelated*, never filled the far field, and their parakeet redrew against `"pet"` and
came back a generic winged mammal. So the noun now lives **inside the upload door, in its own
`what animal is it?` field** (`SourceRail.tsx`, its own `uploadNoun` state, separate from the
typed door's `typedDraft`). They are genuinely different questions: the typed door's field is
its *whole input* — "draw this from nothing"; the upload door's field *labels a photo the user
already holds*. A field in each is correct, not redundant.

**This also deletes a hazard the borrowed field created.** When the upload borrowed the typed
draft, a leftover `blue jay` from an earlier typed draw would ride along with a dog photo — and
because `_remix_prompt` repeats the subject to make it win (§0.2), a *wrong* noun was actively
worse than `"pet"`. The old design fought this with an echo line (*"using 'blue jay' — change it
on the left"*). A dedicated, independent field removes the cross-talk entirely: the upload door's
noun is only ever the one typed into the upload door, so there is no stale value to echo and no
"left" to point at.

### 2.2 B — isolate and crop *(the main event)*

On the worker, for uploads only. **Two functions, not one** — the ML call and the geometry are
separated because the geometry is where the failure rules live, and they have to be testable
without a GPU (§7):

```python
def _remove_bg(img) -> Image.Image          # factory.py:112 — EXISTS. birefnet, GPU, ML
def _crop_to_subject(rgba) -> Image.Image   # NEW. Pure PIL: alpha bbox + margin + crop
```

`_crop_to_subject` returns the input **cropped to its alpha bbox plus a 5%-per-side margin**, or
— in every failure case — **the input unchanged**. It never composites and never pads: the
existing tail of `_prep_reference_image` already does both, so the fallback is "return the input"
and the caller's behaviour is then byte-identical to today by construction.

> **Why 5% and not the looser figure an earlier draft used.** Margin trades directly against §7's
> "subject fills the frame" bar. A square subject of side `S` with margin fraction `m` per side
> occupies `1/(1+2m)²` of the result: **5% → 82.6%** (clears §7's ≥80%), **8% → 74.3%** (fails
> it). The implementation pins `_CROP_MARGIN = 0.05` for exactly this reason — the constant is the
> spec, not an illustration.

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

**VRAM contention is real and was observed on the dev box (Phase 2 finding).** The isolate step
runs *before* the img2img, so on a node where ComfyUI is already resident (~21 GB of a 24 GB
3090 in the local dev stack), birefnet's ~800 MB allocation can **OOM** — and it did, on the
first real-hardware run. The `try/except` caught it and degraded to the raw photo (exactly §2.2),
so the door stayed up — **but a node that OOMs every time silently no-ops the whole lever via
the fallback.** This is not a correctness bug; it is a *"did the benefit actually happen"*
question, and it is Phase 2's to answer:

> Measure the **fallback rate** on a representative node, not just the visual quality. A cutout
> that logs `subject isolation failed` on most uploads is a lever that isn't pulling. If the rate
> is high, the levers are (in order): run the cutout on the second GPU where the box has one
> (`CUDA_VISIBLE_DEVICES`, proven to work on the dev box); or free ComfyUI's VRAM around the
> one-shot cutout; or accept CPU birefnet for this single call (one image, inside the 180 s
> budget — unlike the 2026-07-21 per-frame case).

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
that reopens the picker.

It is the **helper line under §2.1's `what animal is it?` field**:

> `side-on, whole animal, good light works best`

(An earlier design carried a *second*, correctness line here — echoing the borrowed typed
draft, *"using 'blue jay' — change it on the left"*. Decision 3a removed the borrowing, so
that line is gone: the field's own placeholder now asks the question directly, and there is no
cross-door value to echo. What remains is the one quality nudge.)

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

### 2.5 E — automate the noun with AI *(Phase 2.1, the captioner)*

A–D fixed the pipeline with nothing installed. E is the deliberate crossing into AI, and it
earns it on evidence: the upload door's whole promise is *"give me a photo, get your pet"*, and
requiring the user to type what the photo plainly shows breaks that promise — a real uploader
left A's field empty and got a generic mammal. **The owner is looking at a parakeet; the app
should not have to ask them what it is.**

**E does not add a new surface — it fills A's.** Lever A (Phase 1) put a `what animal is it?`
field inside the upload door (`uploadNoun`, `SourceRail.tsx`). E writes into that same field:
on upload, the AI identifies the animal and its description, prefills the field, and feeds the
description to the redraw prompt. The user stops typing. **The field is not removed** — it is
the AI's output surface, the correction handle, and the fallback all at once (see below). Once
the AI is reliable it *may* be collapsed to a "not quite right? fix it" affordance, but that is
a later, evidence-gated UI decision, not this phase.

**The AI engine is a SEPARATE spec, and this phase only consumes it.** `SPEC_DATSPET_AI_ENGINE`
owns the model catalog, the purpose registry, dispatch, usage and admin, and **ships and is
demonstrable without this feature** (its acceptance test is key → admin → *Test configuration* →
a usage row — no pet feature required). This phase changes for a different reason than the engine
does — a change to what the redraw prompt needs versus a model being retired — so they are
different specs and different PRs. The engine does not import this feature and is guard-tested
against doing so. **What this phase owns is small and precise:**

| Owned by the engine (`SPEC_DATSPET_AI_ENGINE`) | Owned by this phase |
|---|---|
| which models exist, their lifecycle and cost; `call_purpose(...)`; usage log; admin; key handling; degradation contract | `image_triage.json`, `pet_likeness.json`; the one call from the upload path; prefilling `uploadNoun`; the manual-override behaviour |

The two purposes this phase contributes into `pet_factory/ai_purposes/` (per the engine's
consumer model), both **one image**, so `call_purpose(image=…)` fits with no signature change:

| `purpose_key` | Tier | Input | Question |
|---|---|---|---|
| `image_triage` | `fast` | 1 image | *Is this an animal, and is it usable?* Cheap gate, runs first — makes the "not an animal" branch real |
| `pet_likeness` | `fast` | 1 image | *What animal, breed, coat, markings?* Runs only if triage passes; its answer prefills the field and extends the prompt. Identifying an animal is not hard — start on `fast`, bump the tier only if §4's corpus shows it's needed (`SPEC_DATSPET_AI_ENGINE` decision 17) |

**Where it runs, and why it is NOT fleet-gated like B.** The web tier, over HTTPS — no VRAM, no
per-worker install, the GPU-less posture `CLAUDE.md` calls load-bearing. Crucially, the call
happens at **reference-creation time on the web tier** (`app.py`'s `door == "upload"` branch),
and the resulting description is stored on the reference and flows to *both* the local and pool
render backends unchanged. So unlike B — which needs a handler v3 rolled to every node (§2.2,
Phase 3) — **E reaches production the moment the engine and this phase ship; it does not wait on
the fleet.** One new secret, `DATSPET_AI_API_KEY`, per the engine spec.

**Every failure degrades to A's manual field — which is exactly why A's field is not removed.**
Key unset, API down, rate-limited, a refusal, or **not an animal at all** → the field simply
stays as the user's own input, i.e. today's Phase-1 behaviour. A vision outage must never take
out the upload door. `DATSPET_AI_API_KEY` unset ⇒ the whole of E is inert and the door is exactly
Phase 1 — the standalone-first posture `datsme_integration.py` already uses for its own secret.

**The owner's word still wins (decision 3, unchanged).** The AI prefills; the field stays
editable; if the user corrects it, their value is used and the AI's is discarded. E moves typing
from *required* to *rarely needed*, it does not overrule the owner.

**One open decision for the build (not settled here):** whether the call fires **eagerly on
photo-select** (prefill ~1–3 s later, so the user sees and can correct the identification before
drawing) or **lazily folded into Draw** (no extra perceived latency, but no chance to correct
first). Eager fits the "see it, fix it if wrong" model better; lazy is cheaper. Decide against
the real latency in the build.

**The honest ceiling, restated.** E fixes the **descriptor** — the input to the redraw. It brings
the non-typing majority up to the quality a correct hand-typed noun already reaches (the parakeet,
once named). It does **not** fix the double-redraw drift or a bad input pose (§3). If results are
still off *with a correct AI description*, the next lever is the pipeline, not more AI.

---

## 3. Why these levers, and what is deliberately not fixed

**The selection rule: a lever only counts if it survives step 2's mandatory redraw.** Step 2 is
img2img at up to 0.9 (`app.py:967-975`), it mints a **new** reference (`source="design"`), and
step 3 animates *that* one as-is (`app.py:1238`, `remix_strength` always `None`).
`SPEC_STEP1_SOURCE_RAIL` §1.12 already used this to delete the faithful↔sprite chooser: at 0.9
the second pass wins outright, and photographic fidelity is *gone before anything is animated*.

The levers pass that test, and this is the whole reason they are the levers:

- **A** rides `ref["description"]` straight into step 2's own prompt (`app.py:966`) — the noun
  is fixed in *both* redraws, not one.
- **B**'s gain is **composition**, not pixels. A well-framed dog on white redraws as a
  well-framed dog; a garden redraws as a garden. Framing survives a 0.9 denoise; fidelity does
  not.
- **C** moves the input distribution, which is upstream of everything.
- **D** puts the owner's judgement after the render, where no amount of denoise can erase it.
- **E** writes into A's slot, so it rides the same path A does — it changes *who* fills the
  descriptor (the AI, not the user), never *where* the descriptor goes.

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
| **1** | ✅ **DONE** (`f81bb2c`, + the inline-field refinement — decision 3a). **A + C** — the animal is named in the upload door's **own** field (`uploadNoun`), with the quality line under it | anything else. Hours |
| **2** | ✅ **CODE DONE.** **B (local)** — `_crop_to_subject`, `isolate=` on `_prep_reference_image` → `_base_sprite` → `render_design_still` → `_render_still`, upload branch sets `isolate=True`. 8 guard tests (§7) + the upload-isolates / preview-does-not assertions. Real-GPU verified: cat-in-grass → tight crop on white; a real OOM degraded to the raw photo. **Note: this is live on `PET_GEN_BACKEND=local` ONLY — prod runs `pool`, whose branch does not forward `isolate`, so uploads in prod are unchanged until Phase 3.** **Remaining: the corpus measurement — rows B/A/A+B + the fallback-rate finding above** | the fleet |
| **2.1** | **E — the captioner (§2.5).** ***Requires `SPEC_DATSPET_AI_ENGINE` built (its phases 1–5) — a separate spec this one only consumes.*** Contribute `image_triage.json` + `pet_likeness.json`; call `call_purpose(image=…)` from `app.py`'s `door == "upload"` branch; prefill `uploadNoun` + extend the redraw prompt with the caption; degrade to the manual field (Phase 1) on any failure or not-an-animal; human's word wins on override. **Web-tier — reaches prod WITHOUT the Phase 3 fleet gate**, and independent of B and D | the AI engine (hard dependency); Phase 3; the fleet; B; D |
| **3** | **B (pool)** — `isolate_subject` param → `pet_preview_handler` **v3** → roll to the fleet → enable. §10.1 fleet gate. **Before enabling: the §2.2 VRAM-contention decision is a fleet gate, not a Phase 2 note** — a pool worker runs birefnet on the same card as a resident Z-Image model (`vram_gb: 20` advertised), the exact shape that OOM'd on the dev box. Pick the mitigation (second GPU / free ComfyUI's VRAM / CPU birefnet for the one call) and confirm the fallback rate is low on a real worker, or every pool upload silently no-ops through the catch | — |
| **4** | **D** — the candidate strip | B |
| **5** | **Measure** (§4) end to end, then decide whether anything **still** in §8 is warranted | — |

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
| 2 | Does this spec need AI? | **A–D do not; E does** | A–D fix the pipeline with nothing installed (§1). E (Phase 2.1) crosses into AI deliberately, on evidence, to automate A — and it is the *only* part that needs a model (§2.5) |
| 3 | Where does the animal's name come from? | **The user, via the upload door's own field** | Ground truth, free. No inference can beat the owner naming their own dog (§2.1). When AI lands it fills this same field on an empty submit; the human's word still wins (§8) |
| 3a | Does the upload door get its own noun field, or share the typed door's? | **Its own — reversed on evidence** | The first build shared the typed door's field ("two hats, same question"). A real uploader read the two doors as unrelated, never filled the far field, and their parakeet redrew as a generic mammal. They ask *different* questions — "draw this from nothing" vs. "label this photo I already have" — so each door owns its field. A dedicated field also deletes the stale-draft hazard the borrowed one created (§2.1) |
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
| 10 | Does the user type the animal, or does AI? | **AI (Phase 2.1) — filling the field the user could type** | The upload door's promise is "give me a photo"; making the owner type what the photo shows breaks it (§2.5). The typed field is not removed — it is the AI's output surface, the correction handle, and the fallback |
| 10a | Does the manual field survive AI? | **Yes — AI prefills it; the owner can override; it may later be hidden, not deleted** | Not-an-animal, a wrong guess, and decision 3 (owner's word wins) all need the field. Hiding it once AI is reliable is a later UI call, not this phase (§2.5) |
| 10b | Does this spec own the AI engine? | **No — `SPEC_DATSPET_AI_ENGINE` does; this spec consumes it** | A model retirement and a change to what the redraw prompt needs are different reasons to change. The engine ships and is demonstrable without this feature and is guard-tested against importing it; this spec contributes two purposes and one call site (§2.5) |
| 10c | Does E wait on the pool fleet like B? | **No — E is web-tier** | The caption is computed at reference-creation on the web tier and flows to both render backends. E reaches prod when the engine + Phase 2.1 ship, without the Phase 3 handler roll (§2.5) |
| 10d | What if the vision API is down or the key is unset? | **Degrade to the manual field (Phase 1)** | A vision outage must never take out the upload door; `DATSPET_AI_API_KEY` unset ⇒ E is inert and the door is exactly Phase 1 — the standalone-first posture (§2.5) |
| 11 | Anything else in §8 (scorer, retry ladders)? | **Still deferred** | The captioner graduated to Phase 2.1 on evidence; the rest waits on the captioner's real-world results, same discipline (§8) |

---

## 7. Guard tests

**All of these run on the standard `pytest pet_factory/tests webui/tests` invocation — no GPU,
no rembg, no onnxruntime.** That is the point of §2.2's split: `_crop_to_subject` is pure PIL,
so its fixtures are synthetic RGBAs whose alpha channel is authored by hand, and the ML import
stays inside `_remove_bg`/`_rembg` where it already is.

Against `_crop_to_subject` (pure, no ML):

| Fixture (alpha authored by hand) | Expected |
|---|---|
| Opaque 350×350 subject in the corner of a 1000×1000 transparent field (**12% area — comfortably above the 5% floor**) | Returns a crop whose subject bbox is ≥ ~80% of the result's area |
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

## 8. Where AI could help — and what is now adopted vs. still deferred

**The captioner has graduated from this section into Phase 2.1 (lever E, §2.5).** §8 used to
hold *all* AI candidates behind an evidence gate — "fix the pipeline first, then ask whether a
model adds anything." That gate has now fired for **one** of them: a real uploader's parakeet
redrew as a mammal because the noun field was empty, which is exactly the evidence §8 demanded
that the empty-noun case is common and worth automating. So the captioner is adopted (§2.5), on
the engine that is its own separate spec.

The rest of this section stays deferred — recorded so the sequence remains deliberate, not
because the model is assumed useless:

1. **A scorer in the harness** (`SPEC_DATSPET_AI_ENGINE` + a `likeness_score` purpose). Its
   value is highest where **there is no user in the loop** — sweeping a corpus after every
   prompt change, which a human sitting cannot do repeatably. A *tooling* use, not a product
   feature, and the one use §2.4 does not displace: the candidate strip puts the owner in the
   loop at runtime, and the owner is a better judge of their own dog than any model.
   *(If it is ever built: `likeness_score` takes **two** images, and `SPEC_DATSPET_AI_ENGINE`
   §4's `call_purpose(..., image=…)` takes one. That signature has to widen before the purpose
   can exist — a real edit to that spec, not a contribution under it. The captioner in Phase 2.1
   does **not** hit this: `image_triage` and `pet_likeness` are one image each.)*
2. **Everything else** — per-photo render-path selection, automated retry ladders, quality
   gates — is downstream of the captioner and the scorer, and should not be designed before the
   captioner's real-world results are in.

**The rule that ordered this spec, and still holds:** the pipeline had an unused segmentation
model, a documented precondition nothing enforced, and a prompt naming the wrong animal. A
language model on top of *that* would have measured a problem the pipeline was creating — which
is why A–D came first. The captioner is adopted now because the pipeline is fixed underneath it
and the evidence for the empty-noun case came in, not because the discipline was abandoned.
