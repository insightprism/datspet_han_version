# SPEC — Build Your Avatar

**Status:** proposed, 2026-07-26. **Rev.1.**

**Depends on:** `SPEC_UPLOAD_LIKENESS` (the upload door, subject isolation, the captioner —
Phases 1/2/2.1 built), `SPEC_PET_DESIGNER_FLOW` (the step shell this borrows its *feel* from),
`SPEC_PET_DESIGN_AXES` (the axis registry mechanism, not its content).
**Repos touched:** `datsme-pet-factory_wu` — `web/`, `webui/`, `pet_factory/`, one pool handler.

A person uploads a photo of themselves, or types what they want to be, and gets **one
downloadable cartoon image of themselves** to use as their DatsMe profile picture.

It is not a pet. It does not animate. It does not enter the pet house.

---

## 1. Why this is a separate product, not a designer mode

The pet designer exists to produce an **animated bundle**: a reference is locked so it can be
animated as-is, poses are chosen and priced, a motion profile decides how limbs move, and the
output is a `.zip` the host plays forever. Every one of those facts is load-bearing there and
**absent here**.

If this were a mode of `/design/general`, `designFlow.ts` would grow an `isAvatar` branch and
every future change to the pet flow would have to be re-reasoned against the avatar case. That
is the engine-vs-content rule pointed at a product boundary: *things that change for different
reasons live in different places.* The pet flow changes when animation changes. The avatar flow
changes when profile pictures change. They will never change together.

**Decision:** its own route (`/avatar`), its own state module, its own backend endpoints. It
shares *presentational primitives* and nothing else (§4).

## 2. Scope

**In:**
- Two source doors: **upload a photo**, or **type a description**. (No catalog gallery — there
  is no curated base for "a person"; §3.1.)
- A design step: adjust the look of the avatar produced in step 1.
- A **download** of the final PNG.
- A credit charge of **10** per accepted avatar (§7).

**Out, deliberately:**
- Animation of any kind. No poses, no Wan, no anchors, no sprite sheet, no manifest, no bundle.
- The pet house. An avatar is not persisted as a pet, does not appear in `/api/pets`, and has no
  DPP writeback.
- Automatic upload to a DatsMe profile. The user downloads and uploads it themselves (§8).

## 3. The flow — two steps

Same *shape* as the designer, so it feels like the same family of product, with step 3 removed.

### 3.1 Step 1 — "Choose your starting point"

Two doors, not three:

| door | cost | what it does |
|---|---|---|
| **Use my own picture** | ~10 s | upload → optional subject isolation → redrawn as a cartoon |
| **Or describe yourself** | ~10 s | txt2img from the typed description |

The pet designer's third door — *"Use an existing base animal"* — has **no analogue** and is
omitted. It exists because the catalog ships human-approved `base.png` files per breed; there is
no curated base for a person, and a gallery of stock avatars would be a different feature.

Everything else about the step carries over: the drawn result shows in a box to the right, the
last two results are kept as clickable history, and the step locks with a confirm button before
step 2's controls mount.

### 3.2 Step 2 — "Design your avatar"

Axis pickers over the step-1 image, same interaction as the pet design step: pick a value, the
image is redrawn (img2img) toward the composed description, lock when satisfied.

The **axes are different content** (§5) — hair, outfit, expression, accessory — because a pet's
vocabulary (coat/plumage/scales, four-legged body shapes) does not describe a person.

### 3.3 There is no step 3

Step 2's lock reveals the **Download** button and the credit cost. That is the end of the flow.

## 4. Module boundary — what is shared, what is forked

The rule: **share what has no opinion about the product; fork what encodes the flow.**

| Component | Shared? | Why |
|---|---|---|
| `Step.tsx` | **shared** | A collapsible numbered step shell — `index/title/summary/artifact/expanded/reachable`. Zero pet knowledge. |
| `ModalOverlay`, `ConfirmModal`, `FieldHelp` | **shared** | Generic primitives; already used across admin and designer. |
| The `.card` / pill / rail styling | **shared** | This is what "same feel" means. Achieved through the existing CSS vars and classes, not through shared logic. |
| `SourceRail.tsx` | **forked** | Its props are the three-door model (`PendingSource["kind"]`, the catalog gallery). Two doors with different copy is a new, simpler component — not a `showCatalog?: boolean` flag. |
| `BaseGalleryDialog.tsx` | **not used** | No catalog door. |
| `designFlow.ts` | **forked** | The reducer IS the pet flow's invalidation rules — lock/unlock across three steps, pose menu, tier caps. The avatar's rules are a strict subset and will diverge. A new `avatarFlow.ts`. |
| `DesignStep.tsx` | **forked** | Same interaction, different axis content and no `surface` gating. |
| `PoseStep.tsx` | **not used** | No animation. |
| `render_design_still` | **shared** | The engine call is genuinely the same operation. |

**The test:** adding a pose type to the pet designer must not touch an avatar file, and changing
the avatar's axes must not touch a pet file. Any shared item above that would break that test is
in the wrong column.

## 5. Avatar design axes — new content, existing mechanism

`pet_factory/design_axes/` is already a registry of one-JSON-per-axis with a `prompt_fragment`
per option, composed at fill time and never exposed to the browser. That mechanism is right and
is reused. Its **content is not**: `coat`/`plumage`/`scales` are gated on an animal's `surface`
tag, and `body` describes four-legged silhouettes.

**Decision:** a sibling registry, `pet_factory/avatar_axes/`, with the same file shape, the same
guard tests, and the same "adding an option is one JSON edit" property. Proposed Tier 1 axes:

| axis | kind | examples |
|---|---|---|
| `emotion` | suffix clause | happy, angry, excited, sad, surprised, determined, tired, smug, … |
| `hair` | suffix clause | short, long, curly, braided, bald, … |
| `outfit` | suffix clause | casual, formal, armour, lab coat, hoodie, … |
| `accessory` | suffix clause | glasses, hat, headphones, mask, none |
| `framing` | **template**, not a clause | face only · head and shoulders · full body |

**`emotion` is the richest axis here, and the one most likely to work.** The pet `expression`
axis was MEASURED (Phase 3, 2026-07-16) as *"the STRONGEST axis… all five options live at 0.85
on every cartoon-styled animal"*, and its only recorded weakness was semantic rather than
strength-related: *"a beak can't smile."* A human face is the inverse of that failure — faces
are exactly what these models render most expressively. So the avatar's emotion set can be
wider than the pet's five, and should be measured the same way (§11).

**`framing` is different in kind and must not be a suffix clause.** Face-only vs full-body is a
*camera* property, not a property of the subject, and img2img cannot reliably re-frame an image
it is denoising — it redraws what is already in the frame. Framing therefore selects a
**template variant** (§6) and re-renders from the *source* (the upload, or the text), not from
the current still. Consequence for the UI: changing framing invalidates the current image the
way a step-1 change does, whereas changing emotion or hair is an in-place redraw. `avatarFlow.ts`
owns that distinction — it is exactly the kind of invalidation rule the reducer exists to hold.

A shared *engine* over two axis registries is a candidate for later — but not before a third
instance exists (three-instances rule). Two registries with identical shape is the correct
amount of duplication today.

## 6. The prompt template — an avatar is not a sprite

**This is the one engine change the feature genuinely needs.**

`prompt_templates.BASE_STILL_TEMPLATE` hardcodes `side profile view, facing right`, because a
pet is a sprite that walks across a page and DatsMe mirrors it for leftward travel. A profile
picture in side profile is wrong — an avatar faces the viewer.

**Decision:** add `AVATAR_STILL_TEMPLATE` (and its remix counterpart) to `prompt_templates.py`,
front-facing, head-and-shoulders or full-body framed for a profile picture. The module is pure
strings with no ML imports (extracted 2026-07-26), so this is a constant plus a render function,
readable by the GPU-less web tier, and it appears in the admin's Prompt templates tab for free.

Consequence: the avatar path does **not** consume a motion profile's `base_pose`, because
`base_pose` describes a posture for walking. The avatar template carries its own framing. This
also sidesteps the `pet_preview` base_pose parity gap (§9) entirely.

## 7. Credits

**10 credits** per accepted avatar, charged once on download — not on each redraw, or every
adjustment in step 2 would meter the user mid-decision.

Follows the existing DPP posture: the host owns the ledger, the cost is a data knob (not a
constant in code), and the standalone instance with no `DATSME_HMAC_SECRET` is free and inert.

**Open:** whether a failed or abandoned flow refunds. Recommendation: never charge until the
download is issued, which makes refunds moot.

## 8. The download contract, and not foreclosing the DatsMe push

Download-only is the Rev.1 scope, and the reason is honest: it is the fastest path to a usable
feature, and a user who has the file can already set it as their DatsMe picture by hand.

The future automation must not be blocked by that choice, so **the avatar is produced as an
addressable artifact, not only as a byte stream**: the endpoint returns a PNG *and* a short-lived
reference the browser downloads from. When the DatsMe push lands, it sends that same reference
server-to-server — exactly the pointer pattern the pet writeback already uses (bundle_url +
sha256 + one-time token) — rather than needing the flow rebuilt around it.

## 9. Rollout

The pool `pet_preview` handler already returns PNG bytes and accepts `description`,
`reference_image_b64`, `strength`, `isolate`. Whether the avatar needs a **new pool task** or can
ride `pet_preview` depends on §6: a different prompt template means the template choice must
travel with the request.

**Recommendation:** a new `avatar_still` pool task rather than a param on `pet_preview`. Separate
tasks are already the pattern here (`pet_factory` vs `pet_preview` are deliberately separate with
different params, results and timeouts), and it keeps the pet preview's contract frozen while the
avatar's is still moving. Fleet-roll the handler **before** the web tier, per the deploy order
that `pose_anchor` v4 and the `pet_preview` v2/v3 rollouts established.

## 10. Open questions

1. **Likeness gate** — `pet_likeness` exists to judge whether a redraw resembles its upload.
   Should a poor-likeness avatar warn before the charge? (See §11 — this may become automatic.)
2. **Content safety** — this feature invites photographs of real people, and produces images of
   them. `image_triage` already exists on the upload door; the avatar door should reuse it, and
   the policy question (whose photo may a user upload) needs an answer before launch, not after.
   This is the one open question that should block launch rather than iterate after it.
3. **Style range** — one house style like the pet factory's storybook look, or a style axis?
   Rev.1 assumes one house style, matching the pets, so a user's avatar and their pets look
   like they belong together.

*(Framing was an open question in draft; §5 resolves it as a user-chosen axis rather than a
product decision.)*

## 11. Does the model actually do this? — measure before building the UI

Two unknowns decide whether this product is viable, and **neither needs the UI to answer**:

1. **Do the edits land?** Can the model put a specific emotion, hairstyle or outfit on an image
   on request, reliably enough to sell?
2. **Does the person survive?** img2img at a strength high enough for the edit to register also
   erodes the face. For a pet nobody notices; for an avatar it is the whole product.

That second tension is what makes this feature genuinely uncertain, and it is **new** — the pet
designer never had to care. The measurement machinery, however, already exists and needs no new
infrastructure:

- `scripts/calibrate_design_axes.py` + `calibration/matrix.json` renders every axis option
  against representative subjects at a given strength and records the result; the guard test and
  admin endpoint read the same manifest ("the one knower, three surfaces").
- `min_strength` per option and `effective_strength` already encode "this edit needs at least
  this much denoise to register" — that is question 1, quantified, per option.
- `pet_likeness` (an existing AI purpose) scores whether a redraw still resembles its source —
  that is question 2, scorable without a human.

**The experiment:** sweep `strength` across a grid of avatar axis options on a fixed set of
source photos; for each cell record (a) did the edit land, and (b) the `pet_likeness` score.
The product is viable iff a strength band exists where edits land *and* likeness survives. Report
that band as the avatar's `base_strength`; per-option exceptions become `min_strength`, exactly
as the pet axes already do.

**If no such band exists, stop here.** That is a cheap, honest kill — a calibration run, not a
built feature — and it is the main reason to answer §11 before writing `avatarFlow.ts`.

## 12. Iteration is the interaction — and a two-tier quality model

**Iterating is the point here, and it is cheap.** A pet build is ~3 minutes and eight Wan loops,
so the designer is built to lock decisions and commit once. An avatar redraw is ~10 seconds, so
the avatar step 2 should invite *tweak → redraw → tweak* freely. Two consequences:

- **Redraws are free.** The 10 credits are charged once, on the final render + download (§7).
  Metering redraws would make people ration exactly the behaviour the product depends on.
- **No lock-to-proceed gate in step 2.** The pet flow's *work → look → 🔒 lock* exists because the
  next step costs GPU minutes. Nothing downstream here is expensive, so step 2 stays open and the
  Finalize button is always available.

### 12.1 Draft quality vs final quality

Today's prompt asks for `soft pastel colors, muted palette, simple flat shading, storybook
style` — a deliberately flat cartoon, because pets are sprites. For a profile picture people
will want more. **The levers actually available on this box, in order of cost:**

| lever | cost | ceiling |
|---|---|---|
| **Style wording** — drop "flat shading / storybook", ask for rendered shading, detail, depth | **free** | large; this is most of the gap |
| **Resolution** — `EmptySD3LatentImage` is 1024²; 1280–1536² costs roughly with pixel count | ~2× time | more facial detail |
| **Hires second pass** — latent-upscale the draft, re-denoise at low strength | ~1.5× time | the classic detail lever; uses existing nodes, no new model |
| Steps — 8 today | — | **not a lever**: Z-Image-*Turbo* is distilled for ~8 steps; more does not help |
| A non-distilled checkpoint at cfg 5–7 | new model download + new workflow | true photographic quality — **out of scope for Rev.1** |

**Decision — two tiers:**

- **Draft** (every redraw): today's settings. ~10 s. This is what you iterate on.
- **Final** (one button, once): richer style wording, higher resolution, optional hires pass.
  Target ≤ 45 s — measured, not assumed (§11).

### 12.2 The final pass must refine the draft, not re-roll it

**Final is an img2img refinement of the approved draft at LOW denoise (~0.25–0.35), not a fresh
render.** If Finalize re-rendered from scratch with different style words, the user would tune an
avatar they liked and receive a different-looking one — having already agreed to pay for it.

This repo has already learned this lesson once, in the pet flow: `remix_strength` is *always*
`None` on the web path because *"the still is one the user has already SEEN and locked; redrawing
here would re-roll the look after they said yes to it."* Same rule, same reason.

So the final pass keeps composition, pose, framing and identity, and spends its denoise budget on
shading and detail. The style wording shifts; the person does not.

*(This also partly answers §10.3: the avatar's finished look is allowed to be richer than the
pets', because a profile picture and a walking sprite are not shown side by side.)*

### 12.3 There is no avatar Lab — the product is the lab

The Motion Lab exists because a pet build costs **~3 minutes and eight poses**: you need a cheap
way to see one pose before paying for all of them. It is a preview harness for an expensive,
irreversible operation.

This product has no such operation. A redraw is ~10 s (≤45 s finalised), redraws are free, and
there is no lock gate — so the avatar page **is** the preview surface. A lab for it would be a copy
of the product with a different button, and one more thing to delete under §13.

What the avatar does need is not a lab but the §11 **calibration sweep** — strength × axis option ×
source photo, scored for "did the edit land" and "did the likeness survive". That is a batch script
producing a table, run once before the UI exists, not an interactive surface.

## 13. Removability is a requirement, not an afterthought

This is an experiment. It must be deletable without archaeology, so every artifact it adds is
namespaced to it and nothing pet-side takes a dependency on it:

| added | removing it |
|---|---|
| `web/src/app/avatar/*` | delete the route |
| `avatarFlow.ts`, the forked rail/design step | delete the module |
| `pet_factory/avatar_axes/` | delete the registry + its guard test |
| `AVATAR_STILL_TEMPLATE` in `prompt_templates.py` | delete two constants |
| the `avatar_still` pool task | unregister the handler; the fleet keeps `pet_factory`/`pet_preview` untouched |
| the credit knob | set it to 0 or remove the product from the host's catalogue |

**Nothing under `pet_factory/motion_profiles/`, `design_axes/`, `webui/app.py`'s generate path,
or the designer flow changes to add this feature — and therefore nothing there changes to remove
it.** If a proposed implementation step breaks that property, it is the wrong step. That is the
concrete meaning of "a different product": the blast radius of deleting it is a list of files,
not a migration.
