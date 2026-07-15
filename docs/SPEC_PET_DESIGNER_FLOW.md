# SPEC — Pet Designer Flow (archetype → design → animation)

**Status:** **Rev.6** (2026-07-15). **§1–§5 and §8 are AS-BUILT** — they describe the shipped
three-step designer, rewritten from it after many rounds of review against a running app.
§6, §7 and §9–§13 are design, reconciled to them.

**Implementation:** build steps 1, 2, 3, 5 and 6 are **done and green** — 213 tests, `tsc`
clean. Step 4 is a fleet deploy (§10.1). Step 7 is **blocked on step 8** (§10). Decision #5
— does img2img at 0.9 actually move a silhouette — is the one open gate, and body shape
does not ship until it is answered.

A UX consolidation of the designer surface. Sits under
**`docs/SPEC_PET_DESIGNER_PLATFORM.md`** (the umbrella — landing, themed pages, base
catalog, tiers) and reuses the movement layer of **`docs/SPEC_MOTION_PROFILES.md`**
(implemented) and the fleet-cutover discipline of **`docs/SPEC_V3_FLEET_ROLLOUT.md`**.
Grounded against the working tree at `3c2c071`; line numbers cited below were verified
against that tree and predate this spec's own changes.

**Repos touched:** `datsme-pet-factory_wu` only (frontend, web tier, `pet_factory`, one pool handler).
`shared_gpu_cpu` and `datsme_me` are **not** modified.

---

## What changed in Rev.6 — **the flow is THREE steps, and they are all as-built**

Rev.5 rewrote §3 from the shipped step 1. Rev.6 does the same for the rest: the whole
designer is now as-built, and the biggest change is that **there are three steps, not
five** — which is the model §0 has described since Rev.2.

| Rev.1–5 said | Built instead | Why |
|---|---|---|
| Five cards: your animal · design it · **see it** · poses · create | **Three: base animal · design your pet · its moves** | A preview is not a step — it is the ANSWER to step 2, the way the box is the answer to step 1. Rev.1–5 split them "because the redraw takes ~10 s and deserves its own beat", which put the picture on a different screen from the swatches producing it (§4) |
| One lock (`baseConfirmed`, §3.7) | **Two — `designConfirmed` mirrors it** | Seeing a preview is not choosing it. Both steps now read identically: work → look → lock (§4.7) |
| Step 2 stacked: controls, then the picture | **Split — controls left, your pet right, sticky** | A result you must scroll away from to adjust is a result you cannot compare against (§4.8) |
| The finished pet **replaces the page** | **It lands in step 3's card** | Steps 1 and 2 used to vanish the instant the build finished. The result is step 3's artifact, exactly as the base is step 1's (§8.1) |
| Poses: walk/idle ghosted, picks indigo | **Green = will be built.** Deep = always, lighter = you chose it | The ghosting read as *disabled* — the two poses every pet is guaranteed to have looked unavailable (§8.2) |
| Header: two nav buttons + a blurb | **The three steps, numbered** | Both destinations are in the global nav already; the header now names what each step gives you |

**§0's model finally IS the interface.** Archetype → design → animation, three steps, three
cards. It took six revisions to build the three steps the spec opened by describing.

**Also (testing, revert before launch):** `tiers.json` `plus.max_poses` 5 → **10**, flagged
in three greppable places (§9.21). `default_tier` is `"plus"`, so this is what every user
gets — at 50 credits an extra pose a 10-pose pet charges 500.

---

## What changed in Rev.5, and why — **§3 rewritten from what was built**

Rev.1–4 specified step 1 three times and were wrong three times. Rev.5 does not specify it
a fourth time: **§3 now describes the screen that exists**, built through six rounds of
review against a running app, and says why each piece is the way it is. Everything below
§3 was reconciled to it; the corrections are in §13.

**Implementation status:** build steps 1, 2, 3, 5 and 6 are **built and green** (213 tests,
`tsc` clean). Step 4 is a fleet deploy; step 7 is blocked on step 8 (§10). Decision #5 (the
silhouette calibration) is still the one open gate.

| Rev.1–4 said | Built instead | Why |
|---|---|---|
| Cascading `species → breed` dropdowns | **A gallery of the base images** | The bases are pictures on disk. Making someone read "Cat → Tabby" to learn what a tabby looks like inverts the point of curating them, and contradicts platform §4.3 in its own words (§3.3) |
| Two/three doors on the page; a separate dropzone; a "Change" button | **One dialog behind the box** | The box is the interface. Every extra affordance was a second door into the same room (§3.1) — and it is the author's original framing, recovered from Rev.1's own preamble |
| Pre-filled, chooser opt-in via "Change" | **Pre-filled, and the picture is the control** | Same intent; "Change ▸" beside an already-clickable picture was the redundancy (§3.1) |
| Uploads redrawn at a fixed 0.85 | **The user picks faithful ↔ sprite** | Likeness vs animation quality is a real trade and only the user knows which side they want (§3.5) |
| One button that draws *and* commits (decision #9) | **Draw, then Use** | Once selection began executing immediately, the two stopped being one act (§3.6) |
| Step 2 opens as soon as a picture exists | **The LOCK gates it** | Filling the box is not choosing. This is what finally delivers "3 controls at first paint" — the number Rev.1/Rev.2 claimed and could not reach (§1.1, §3.7) |
| — | **`<ModalOverlay>`, a new shared primitive** | There was no overlay to reuse: `ConfirmModal` was itself a hand-rolled `fixed inset-0` missing all four things `CLAUDE.md` names. It was migrated onto the new primitive (§3.8) |
| — | **`cat/black` deleted from the catalog** | "Black" is a colour, and colour is a step-2 input — a Black Cat base is a cat already designed (§2.1/§3.4). The archetype rule governs content, not just controls |
| — | **Flat-directory idea rejected** | The gallery needs a flat *list* and already has one; the disk tree is invisible to the UI (§3.3, #17) |

**What this cost:** ~6 → ~7 actions. The lock is a click auto-advance would not have
charged. It is the right trade — but it is a trade, and §1.1 says so rather than burying it.

---

## What changed in Rev.4, and why

Rev.3's numbers were right and its **rule was missing.** §7.6 stated disclosure in one direction only —
"steps past the frontier unmount" — and never said what happens to steps *behind* it, so §1.1 (peak
~21) and §12 ("completed steps stay mounted") each assumed a different answer. The largest new file in
the spec (`Step.tsx`) could not be written from it.

| Gap | Fix |
|---|---|
| The disclosure rule was one-directional; peak was undefined | **One symmetric rule** (§7.6): *every step always renders its artifact; a step renders its controls only when expanded.* First paint = 18 and peak = 21 now follow as arithmetic. Rev.3's figures were right; only its reason (§12) was wrong |
| **`frontier()` deadlocked the flow.** Once a preview existed, `frontier` was 4 forever, so step 2's controls — which mount only at `frontier === 2` ("design untouched") — could never reopen. **The user could not change their mind after seeing the preview** | §7.6: separate the **gate** (`frontier`, derived, never stored) from **which panel is open** (`expanded`, clamped to the frontier). "Never store the current step" was right about reachability and wrong about disclosure |
| §4.6 cited a §10.2 pin that did not exist | Added to §10.2 |
| Editorial: `(+ text if #4 = yes)` after #4 resolved; decision #14 pointing at §10 for a §11 list | Fixed |

The deadlock is the important one: it was a **product** bug hiding in a state-management sentence, and
it would have shipped as "the design step goes read-only once you preview."

---

## What changed in Rev.3, and why

Rev.2 was right about the architecture and **wrong about what the redesign buys the user.** Two of its
UX claims did not survive verification against the working tree:

| Rev.2 claim | Reality | Fix |
|---|---|---|
| *"Controls at first paint: 29 → **3**"* (§1.1) | **Not achievable.** §3.1 and §10.3 both land the box pre-filled **with step 2 open**, and step 2 holds ~25 controls. First paint was always going to be **~26**. The claim and the layout contradict each other — an error inherited from Rev.1 | §1.1 rewritten with real numbers |
| *"today's page opens with 29 controls **and no picture**"* (§0.3), billed as *"the point of the whole redesign"* | **False.** `PetDesigner.tsx:340-349` renders the curated base at 160 px on load (breed is pre-selected), and `:594` renders it again as "original". The picture is already there | §0.3 rewritten — step 1 does not *add* the picture, it **names and protects** it |

Correcting those exposed the real finding: **on every metric the user cares about — controls, actions,
decisions — Rev.2 was flat against today.** It bought legibility and correctness, not a smaller page.

**Rev.3's answer: the page is big because the _vocabulary_ is big, not because the flow is wrong.**
17 colours + 25 accessories + 3 strengths *is* the page, and no amount of restructuring around them
shrinks them — Rev.2 added two more. So Rev.3 puts the vocabulary itself in scope (§4.6), which is the
first change in three revisions that actually answers the author's opening complaint.

The unlock is decision #4: **free text is what makes trimming safe.** 8 swatches + "anything else" is
*more* expressive than 16 swatches alone, and ~8 controls smaller. The two changes are one change.

| | Today | Rev.2 | **Rev.3** |
|---|---|---|---|
| Controls at first paint | 29 | ~26 | **~18** |
| Peak controls | 32 | ~30 | **~21** |
| Actions to a pet | ~7 | ~6 | **~6** |

Also fixed in Rev.3: the archetype rule's two seams — it does not describe door 2 (§2.1), and §4.4's
central argument does not cover the long tail (§4.4). Corrections to Rev.2's claims are in §12.

---

## What changed in Rev.2, and why

Rev.1 was structurally right about the architecture (one `reference_id`, §6) and wrong about **which
step owns "what the pet looks like."** It put body shape in step 1, as an input to *generating the
reference*. That single misplacement is what produced most of Rev.1's complexity: a shape-dependent
fast-path rule, a "load-bearing invariant" protecting a consistency that didn't exist, a
`compose_species()` helper, a third door, and a design-guard exception keyed on where the reference
came from.

Rev.2 moves every "what should it look like" input into step 2, where the user already believes it
lives. The following all **disappear** rather than get rewritten:

| Rev.1 concept | Rev.2 |
|---|---|
| `body_shape` as a step-1 input | A step-2 design attribute, beside color and accessories (§4) |
| The fast-path rule keyed on `is_default(body_shape)` | Gone. Step 1's cost depends only on *which animal*, never on the design (§3.3) |
| "Load-bearing invariant: default `prompt_fragment` must be `""`" | Gone. It existed only to keep two step-1 paths agreeing; there is now one (§7.2) |
| `compose_species(species, body_shape)` | Gone. Shape rides `compose_design` like every other modifier (§7.2) |
| Three doors (Describe / Pick / Upload) | **Two** (§3.2). "Describe" was never a door — it is the long-tail branch of "name your animal" |
| §3.2's relaxed design guard when `ref.source == "txt2img"` | Gone — and it had to go: it was a *provenance* branch, which §6's own rule forbids (§4.2) |
| Upload redraw framed as "a live prod bug", shipped standalone as step 0 | Reframed as the product decision it is, and folded into the redesign (§3.4) |

**Net:** Rev.2 is smaller than Rev.1, deletes more, and adds one genuinely new capability instead of
two. Corrections to Rev.1's factual claims are recorded in §11.

---

## 0. The user's model (read this first)

Three steps. **Each produces exactly one artifact, and the user can see it.**

```
  STEP 1 ─ THE BASE          "What does a blue jay look like?"
           produces ▸        a picture of a TYPICAL blue jay.  Generic. Not yours yet.
                             │
  STEP 2 ─ THE DESIGN        "What should MY blue jay look like?"
           produces ▸        a picture of YOUR pet.  Yellow, chubby, wearing a hat.
                             │
  STEP 3 ─ THE ANIMATION     "Bring it to life."
           produces ▸        your pet, moving.
```

**Step 1 answers a question about the world. Step 2 answers a question about you.** That is the whole
design, and everything else in this document follows from it.

### 0.1 The one rule

> **Step 1 takes exactly one input: _which animal_. Every "what should it look like" input is step 2.**

Colour, body shape, age, accessories, free-form embellishment — all step 2. If a control in step 1
is not answering *"which animal am I starting from,"* it is in the wrong step. This is a rule you can
test a mock against, not a guideline.

**Why it is a rule and not a preference.** A curated base image is a *fixed, human-approved asset*
(§3.3). The moment step 1 accepts a modifier, that asset can no longer satisfy step 1 — a "chubby
corgi" cannot be served by the corgi file — so the system must silently abandon the curated asset and
generate a fresh, unvetted one. The user experiences this as "I nudged one slider"; the system
experiences it as "throw away the good picture and roll the dice." **The rule exists to make that
impossible by construction**, not to be tidy.

### 0.2 The engine already believes this

This is not a new invention — it is the model `pet_factory` was written around, which Rev.1 was
fighting. Two prompt builders, deliberately different (`factory.py:294` and `:302`):

```python
def _base_prompt(animal):     # step 1 — the archetype
    return (f"a cute cartoon {animal}, side profile view, facing right, standing, "
            "soft pastel colors, muted palette, simple flat shading, white background, "
            "storybook style")

def _remix_prompt(animal):    # step 2 — the design applied to an archetype
    return (f"a cute cartoon {animal}, exactly {animal}, side profile view, "
            "facing right, standing, rich saturated colors, simple flat shading, "
            "white background, storybook style")
```

`_remix_prompt`'s own comment says why they differ: it *deliberately drops* `_base_prompt`'s
`"soft pastel colors, muted palette"` clause, because "a remix description is usually about changing
the color, and the pastel clause fights the requested color."

Read that again as UX: **`_base_prompt` is deliberately un-opinionated** — pastel, muted, neutral —
because its job is to show you what a blue jay *is*, before anyone has designed anything.
`_remix_prompt` is saturated and emphatic because its job is to make it *yours*. Step 1 and step 2
already exist in the engine, correctly separated. Rev.2 stops the web tier from blurring them.

### 0.3 Why the user needs step 1 at all

Step 1 is not a technical prerequisite dressed up as a screen. It does two jobs at once, and both are
real:

- **For the user** — it answers "what am I working with?" You cannot design a blue jay you have never
  seen. Step 1 gives you a picture to react to.

  > **Rev.3 correction — do not oversell this.** Rev.2 claimed *"today's page opens with 29 controls
  > and no picture; the new one opens with a picture and three controls,"* and called it *"the point of
  > the whole redesign."* **Both halves are false.** Today's page already renders the curated base at
  > 160 px on load (`PetDesigner.tsx:340-349` — `base.kind === "catalog" && breedKey && speciesKey`,
  > all true at first paint because breed is pre-selected), and renders it a second time as "original"
  > at `:594`. And the new page cannot show three controls while step 2 is open (§1.1).
  >
  > **Step 1 does not add the picture. It names it, gives it a job, and protects it.** Today the
  > picture is a thumbnail beside a dropdown — an accessory to a form control, with no stated contract
  > and nothing stopping a design input from silently replacing it with an unvetted roll (§3.3). Rev.2's
  > contribution is that the picture becomes **the subject of a step with a rule attached**. That is
  > worth doing. It is not worth claiming a blank screen that never existed.
- **For the system** — it is the img2img source step 2 redraws from, and (transitively) the thing that
  guarantees step 3 gets a side-profile, right-facing, correctly-scaled still. Platform §4.1: the
  animator animates whatever the still gives it, and no prompt fixes a bad base.

One artifact, two jobs. That is why step 1 is worth a step.

---

## 1. The flow

```
   ┌──────────────────────────────────────────────────────────┐
   │  1. SELECT THE ANIMAL TO DESIGN                          │
   │                    ┌───────────┐                          │
   │                    │  [🐈 img] │ ← the box IS the control │  PRE-FILLED on load
   │                    └───────────┘   click it to choose     │
   │              [ Draw it · ~10 s ]  [ Use this animal → ]   │
   └──────────────────────────┬───────────────────────────────┘
                              │  clicking the box opens ONE dialog
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐    ┌──────────────┐   ┌────────────────┐
   │ EXISTING    │    │ MY OWN       │   │ TYPE THE       │
   │ BASE ANIMAL │    │ PICTURE      │   │ ANIMAL         │
   │ the gallery │    │ file dialog  │   │ a text box     │
   │ free · draws│    │ ~10 s ·      │   │ ~10 s · Confirm│
   │ on click    │    │ PREVIEWS     │   │ draws          │
   └──────┬──────┘    └──────┬───────┘   └───────┬────────┘
          └──────────────────┼───────────────────┘
                             ▼
                      ONE  reference_id           ← nothing downstream branches again
                             │
                     🔒 Use this animal →         ← THE GATE. Step 2 does not exist
                             │                       until this is pressed (§3.7)
   ┌───────────────────────────▼──────────────────────────────┐
   │  2. DESIGN YOUR PET                                       │
   │                                                           │
   │   colour · body shape          ┌───────────┐              │
   │   accessories · anything else  │ [🐈 yours]│ ← sticky     │
   │   how far to push it           └───────────┘              │
   │                                 from a tabby              │
   │   [ Preview my pet · ~10 s ]  [ Use this as my pet → ]    │
   └───────────────────────────┬──────────────────────────────┘
                               │  🔒 THE SECOND GATE (§4.7)
   ┌───────────────────────────▼──────────────────────────────┐
   │  3. ITS MOVES           walk+idle always · +N · cost      │
   │     [ Bring it to life · ~3 min ]                         │
   │      …and the finished pet lands HERE, in this card       │
   └──────────────────────────────────────────────────────────┘
```

**Three steps, matching §0's model exactly: an archetype, a design, an animation.** Rev.1–5
drew five boxes — splitting "design it" from "see it", and "poses" from "create" — and both
splits were the same mistake: **an answer is not a step.** The preview is what step 2 gives
you; the pet is what step 3 gives you. Each step now holds its own question, its own work,
and its own answer, in its own card.

**Strictly linear, no branches, two gates.** Each step is locked before the next exists
(§3.7, §4.7), so **preview is unconditional** — `/api/generate` *always* animates a
previewed still, and the web tier *always* uses the engine's **as-is** branch. The remix and
text branches survive for the CLI (`make_pet.sh`, `examples/cli.py`) and are not deleted
(§7.1).

### 1.1 What this actually buys — stated honestly

Measured on "yellow chubby blue jay, wizard hat, +run pose":

| | Today | Rev.2 (flow only) | Rev.3 (flow + §4.6) | **Rev.6 (as built)** |
|---|---|---|---|---|
| Actions to a finished pet | ~7 | ~6 | ~6 | **~8** |
| Controls on screen **at first paint** | **29** (verified) | ~26 | ~18 | **3** |
| **Peak** controls on screen at once | **32** (verified) | ~30 | ~21 | **~21** |
| Total controls that exist | 29 | ~30 | ~21 | **~21** |
| Decisions to make | ~8 | ~8 | ~8 | ~8 |

*Rev.6 actions, counted honestly: `Use this animal →` · colour · `Preview my pet` ·
`Use this as my pet →` · a pose · `Bring it to life` — plus the base pick if the pre-filled
default is not wanted. **Two of those eight are the locks**, which no auto-advancing flow
would charge.*

**Rev.6 reaches "3 controls at first paint" — the number Rev.1 and Rev.2 claimed and could
not deliver.** Not by disclosure: by the LOCKS (§3.7, §4.7). Steps 2 and 3 are not mounted
until the base is committed, so the opening screen is a picture, a draw button and a use
button. Rev.2 promised this while its own §3.1 opened step 2 immediately, which is why the
claim was arithmetically impossible (§12).

**It costs two actions** — ~6 → ~8, one per lock, and worse than today's ~7 on that count.
State it plainly rather than hide it: **the flow got longer and better.** A step that
advances the moment you touch it cannot be iterated in, and iterating — try a tabby, type
"blue jay", preview, tweak the colour, preview again — is what steps 1 and 2 are *for*. The
locks are what make those loops safe to run forever, and the honest trade is two clicks for
two loops.

The count was never the real metric anyway (see the caution below the counting method): 29
controls at first paint was never 29 decisions, and 8 actions is not 8 decisions. **Peak is
unchanged at ~21** and still occurs at step 2, where the work is.

**Read the Rev.2 column first, because it is the honest one about restructuring.** Moving the flow
around bought **nothing** on any count. Rev.2 claimed 29 → 3 at first paint; that was arithmetically
impossible next to its own §3.1 ("the box lands pre-filled, **with step 2 open**"), because step 2 is
~25 controls. Restructuring a page does not shrink it. **Only §4.6 does.**

So there are two independent changes here and they must be judged separately:

- **The flow redesign** (§0–§3, §5–§8) buys **legibility and correctness**: a model the user can state,
  a cache-hit guarantee (§3.3), design that survives an animal change (§7.6), a fixed preview race, and
  a preview failure path. It does **not** shrink the page. Do not claim that it does.
- **The vocabulary trim** (§4.6) buys **the size**: 29 → ~18 at first paint. This is the only change in
  three revisions that answers the author's actual complaint — *"too many buttons."*

*Counting method (reproducible): interactive controls inside `<main>`, excluding global nav and the two
non-interactive required-pose chips. Today's 29 at first paint = species select + breed select +
"natural" + 16 colour swatches + accessory select + 3 strength + 4 optional poses + preview + submit.
Peak is 32: three accessory remove-chips render while the select stays mounted. **A caution on the
metric itself:** 16 swatches is one visual scan, not 16 decisions — which is why the "decisions" row is
flat everywhere and why §4.6 targets scan-load, not the counter.*

An empty-box-first design would have *added* an action (~8) by making you choose a door before reaching
a breed dropdown that today is pre-filled. **Pre-filling the box (§3.1) is what keeps actions under
today's.**

This is the platform spec's §3.4 ("Uncluttering is the point": *"shows every control at once… that
reduction in decision-load is the product value"*) delivered by **disclosure for the flow and deletion
for the vocabulary** — because disclosure alone, as Rev.2 proves, moves nothing.

---

## 2. What each step must produce (the contract)

The test for each step is *"can the user say what they just got?"*

**Three steps. Each one asks a question, does some work, and hands back an artifact you
can see** — and each holds all three in one card. Rev.1–5's five-box flow split two of the
answers onto screens of their own; §1 explains why that was the same mistake twice.

| Step | The user's question | **Its artifact** | Cost | Locked when |
|---|---|---|---|---|
| **1. Select the animal to design** | "What does a blue jay look like?" | A still of a **typical, undesigned** specimen: side profile, facing right, standing, neutral colouring, plain background | **Free** if curated · ~10 s if drawn or uploaded | *Use this animal →* |
| **2. Design your pet** | "What should mine look like?" | A still of **your pet** — the archetype redrawn toward colour · shape · accessories · anything else | ~10 s per preview, pressed as often as you like | *Use this as my pet →* |
| **3. Its moves** | "What can it do, and what does that cost?" | The finished **DatsMe pet bundle**, alive in the card | ~3 min | — (the last step; nothing gates after it) |

Every step has the same shape — **work → look → lock** — and the lock is what makes the
work above it safe to repeat forever (§3.7, §4.7).

Three properties this table enforces:

- **Step 1's artifact carries no design this flow applied.** See §2.1 — the naive phrasing
  ("it is generic") is wrong, and wrong in a way that matters.
- **Step 2's artifact is what gets animated.** Not step 1's. The reference the *animator*
  consumes is the previewed still, which is why step 1 never needs to be chubby, yellow, or
  wearing anything.
- **Each artifact stays visible once locked.** Step 3 does not replace the page: the pet
  lands in step 3's card with steps 1 and 2 still above it, green and holding their own
  pictures (§8.1). A flow that forgets its own history the moment it finishes is a flow the
  user cannot check their work against.

### 2.1 The rule is about authorship, not genericness (Rev.3)

Rev.2 phrased the first property as *"step 1's output is never the user's pet. It is generic on
purpose. If a user can look at the box and say 'that's my pet,' the rule is broken."*

**That phrasing is false for door 2.** Upload a photo of your dog and the box holds *your dog* — the
most specific, least generic image in the system. By Rev.2's own words door 2 breaks the rule on every
use. And §3.5 rejects the house-pet source because *"a house pet is somebody's finished design, not an
archetype"* — an argument that **indicts uploads identically**, yet uploads stay. Two sections of Rev.2
disagree about what step 1 is.

The distinction that actually holds is **authorship, not genericness**:

> **Step 1's output must carry no design that _this flow_ applied. Where the picture came from is
> irrelevant; what matters is that step 2 has not run on it yet.**

| Source | Generic? | Designed by this flow? | Door? |
|---|---|---|---|
| Curated `base.png` | yes | no | ✅ door 1 |
| `_base_prompt("blue jay")` | yes | no | ✅ door 1 (long tail) |
| An uploaded photo | **no** | **no** | ✅ door 2 |
| A house pet | no | **yes** — colour and accessories are already baked in | ❌ §3.5 |

This is why uploads are legitimate and house pets are not, and it is a sharper rule than "generic":
a house pet is excluded because **step 2 already ran on it**, so starting there means designing a
design — the modifiers compound invisibly and the user cannot get back to the archetype. An uploaded
photo has never been through step 2. It is raw input, not output.

It also re-grounds §0.1 correctly. The rule *"every 'what should it look like' input is step 2"* is
about **inputs this flow accepts**, not about the aesthetic character of the picture. A photo of a
chubby dog is fine; a **"chubby" checkbox in step 1** is not — because the checkbox is this flow
applying a design, and it is the thing that would discard a vetted asset (§3.3).

---

## 3. Step 1 — select the animal to design

**Rev.5 — rewritten from what was built.** Rev.1–4 specified this section three times and
were wrong three times; what follows describes the screen that exists, and says why each
piece is the way it is. The corrections are recorded in §13.

The single place a starting picture is chosen. Every way in produces one `reference_id`
the rest of the flow consumes identically.

### 3.1 The box is the interface

**The base animal has exactly one home — a box — and the box is also the control.**
Click it and a dialog asks the one question step 1 exists to ask:

> **Where should the base animal come from?**
> · **Use an existing base animal** — the gallery *(free · instant)*
> · **Use my own picture** — the OS file dialog *(~10 s)*
> · **Type the animal I want** — a text box *(~10 s)*

Nothing else is on screen. No dropdowns, no second dropzone, no "Change" button beside a
picture that is already clickable. Rev.1–4 accumulated all three, and every one of them
was a second door into the same room.

This is the author's original framing, recovered: *"have a box that will hold the
reference picture. The user can click on this box and will be given a choice for getting
the reference picture."* It was in the spec's own preamble from Rev.1, and Rev.1–4
specified a dropdown form instead.

**The box lands pre-filled** with a curated base and the step open (§1.1: an empty box
would cost every user an action to learn something most do not care about). It is also a
drop/paste target, because a box you can drop onto needs no second box to drop onto.

### 3.2 Selecting executes — except where a decision is attached

| Door | On selection | Why |
|---|---|---|
| **Existing base animal** | **draws immediately** | It is a file. ~6 ms, no GPU, and the result *is* the thing you clicked — there is nothing to approve first |
| **Type the animal** | **Confirm draws immediately** | A typed animal does not exist until it is drawn. A preview step would show an empty box asking the user to approve nothing |
| **My own picture** | lands as a **preview, undrawn** | The one door with a decision attached (§3.4). Drawing on selection would burn a ~10 s render at whatever strength happened to be the default |

Two of three execute on selection; the one that has a decision attached waits for it.
That asymmetry is not an inconsistency — it is the rule *"never ask for a confirmation
that has nothing to confirm"* applied honestly to three different situations.

### 3.3 The gallery shows the bases; it does not describe them

The curated bases are **images on disk** (`animal_catalog/<animal>/<breed>/base.png`,
served by `/api/catalog/.../base.png`). The gallery renders them, grouped by animal.

Rev.1–4 specified cascading `species → breed` dropdowns. **That inverts the entire point
of curating them.** Making someone read "Cat → Tabby" to discover what a tabby looks like
contradicts platform §4.3 in the same words it uses — *"the user starts from a picture,
not a blank screen"* — and hides the curation behind a noun. These are human-approved
best-of-N stills (`generate_candidates.py` → `promote_candidate.py`); the whole reason a
curated pick is worth preferring over a cold roll is that you can **see** it is better.

Grouped by animal rather than flattened: four entries would read fine flat, but the
catalog grows one folder per animal (platform §4.5), and a group header costs nothing now
and keeps fifty legible later.

> **The on-disk layout stays a tree, and the flat-directory idea is REJECTED (§9.17).**
> A flat *list* is what the gallery needs, and it already has one: `/api/catalog` +
> `catalogBaseOptions()` hand the UI a flat array today, and the frontend has never seen
> the directory. Flattening the disk would rewrite `animal_catalog/__init__.py`, all three
> promote scripts, `generate_sample.py`, the `_candidates/` staging mirror, the samples
> dir, and `catalog.json`'s structure — which pins `motion_profile` per animal *and* per
> breed, the thing guaranteeing a curated corgi animates at least as well as typing
> "corgi" would. It would also require encoding species+breed into a filename and parsing
> it back out, which is ambiguous the moment a name contains the separator. Species and
> breed are already structured fields; a filename is a worse place to keep them.

### 3.4 What step 1 costs

> curated breed exists → **copy `base.png`, zero GPU, ~6 ms**
> otherwise → `_base_prompt(animal)` → **txt2img, ~10 s**
> a photo → **img2img redraw, ~10 s**

**Cost is a property of _which animal_ and nothing else.** Rev.1 keyed it on
`is_default(body_shape)` too, which let a design choice silently change what step 1 cost
*and what it was worth*. There is no design input in step 1, so nothing can.

**A curated base is a human-vetted cache of `_base_prompt(breed)`** — literally so: N
candidates rolled, a person picks, `promote_candidate.py` writes it. So "corgi" is a
cache **hit** (free, instant, vetted) and "blue jay" is an honest cache **miss** (~10 s,
unvetted — there was never a curated blue jay to lose). Rev.1's shape rule turned hits
into misses; nothing here can.

**Content rule (Rev.5): a base is a species + a breed, and nothing else.** `cat/black`
was removed from the catalog because **"black" is a colour, and colour is a step-2
input** — a "Black Cat" base is a cat someone already designed, which is exactly what
§2.1 forbids step 1 from holding. The archetype rule is not only about controls; it
governs the content too. *Open: `tabby` is a coat pattern, not a breed, and fails the
same test (§9.18).*

### 3.5 Uploads — redrawn, at a strength the user picks

**Today an uploaded photo is animated as-is.** The upload branch (`app.py:890-895`) never
sets `remix_strength`, so `make_pet_zip` (`factory.py:474`) takes its as-is branch and Wan
I2V animates a raw photograph.

**This is a product decision, not a bug fix**, and Rev.1 was wrong to ship it to prod as a
"stopgap". The as-is branch is documented intentional behaviour with a stated precondition
(`factory.py:429-437`: "should show one animal, side profile, facing right"), `/make`
advertises it (`make/page.tsx:144`), and the "silently ignored" `strength` field is
unreachable from any shipped UI. What exists is a **product gap** — users upload photos
that violate the precondition and nothing says so.

**Rev.5: the user chooses how far to redraw, because the trade is real and only they know
which side they want.**

| | keeps | costs |
|---|---|---|
| **faithful** (0.4) | your actual dog | photographic pose/lighting — which is what Wan I2V animates badly. Today's bug, chosen deliberately |
| **balanced** (0.65) | — | — |
| **sprite** (0.85, default) | reliable animation | looks redrawn: recognisably *a* dog, not *your* dog |

Defaulting to `sprite` because **the animation is the product** — a faithful still that
loops badly is a worse pet than a stylised one that moves right. The user can disagree;
they just cannot do it by accident. The server clamps to [0.3, 0.9] and does not decide.

This is why the upload door previews rather than draws (§3.2): the control has to be
visible *before* the 10 s is spent, and pressing **Draw it again** after moving the slider
is how you find the one you want.

### 3.6 Draw, then use — two buttons, and why not one

Below the box:

- **Draw it · ~10 s** / **Draw it again · ~10 s** — press as often as you like. A typed
  animal re-rolls to a different blue jay (new seed); a photo re-redraws at whatever
  strength is set. **Absent for a curated base** — it is a file, so pressing draw would
  re-copy the same bytes to the same picture, a button whose only honest label is "do
  nothing, slowly". Absent once locked.
- **Use this animal →** — the commit (§3.7).

*Rev.4 specified ONE button doing both (decision #9). That was answered and then
superseded: once selection began executing immediately, "draw" and "commit" stopped being
the same act. Drawing is the loop; committing ends it.*

### 3.7 Locking is the gate — step 2 does not exist until it is pressed

**`reference` means "what is in the box"; `baseConfirmed` means "and I am happy with it".**
Every new fill resets it — a new picture is a new question.

The frontier gates on it (`designFlow.ts`), so until it is pressed **step 2's controls are
not mounted at all**: not reachable, not tabbable, not scrollable past. That is what makes
the draw loop above safe to run forever. A step that fires you into the next one the
moment you touch it cannot be iterated in, and iterating is the whole point of step 1.

**It is a toggle.** Locked: the section tints green
(`rgba(52,211,153,0.07)` — a tint, not a fill; a literal light green on a near-black page
would blow out the contrast of the sprite sitting on it), and the header reads
**🔒 Locked — click to change**. Clicking it unlocks *and* reopens the chooser, because
wanting to change the base and wanting to see the chooser are the same wish.

> **The toggle's two halves live in different places, for a structural reason.** Locking
> moves the frontier to 2, which collapses step 1 and **unmounts its body** — so a locked
> button living there would vanish the instant it was pressed. "Use this animal →" sits in
> the body (visible while deciding); "🔒 Locked" sits in the header, the one part that
> survives the collapse.

**Unlocking clears the preview but keeps the design.** Colour and shape were never
properties of the base (§0.1), so they survive; the preview cannot, because it is a
function of (base × design) and the base is back in play.

### 3.8 The dialog uses the shared overlay primitive

`<BaseAnimalDialog>` composes **`<ModalOverlay>`** (`web/src/components/ModalOverlay.tsx`),
**new in Rev.5** — there was no shared overlay to reuse. `ConfirmModal` looked like one but
is a fixed title/body/confirm/cancel shape with no children, and was *itself* a hand-rolled
`fixed inset-0 … flex` with **no body scroll-lock, no safe-area insets, no height cap and
no inner scroller** — the exact four things `CLAUDE.md` says hand-rolled overlays always
miss.

`ModalOverlay` owns those four plus Escape-to-close and focus-return. **`ConfirmModal` was
migrated onto it**, which fixed all four for `/house` and `/admin/motions` for free and
makes the primitive genuinely shared rather than a third parallel path. Both callers are
untouched — same props.

### 3.9 The house-pet source is not a door

"Redesign a house pet" is backend-complete (`extract_base_frame`, `app.py:210`) but
unreachable from any UI — `/house`'s Redesign button links to `/design?base=<id>`
(`house/page.tsx:87`) and the landing never reads `?base`. Commit `74c1783` deliberately
removed the house roster as the designer's base source.

That decision stands, **and §2.1 explains why**: a house pet is somebody's finished
design, not an archetype — step 2 has already run on it, so starting there means designing
a design and the modifiers compound invisibly. If revived it arrives pre-resolved via
`?base=<pet_id>` as an explicit deep link, never a fourth choice in the dialog.
**Deferred to §11.**

## 4. Step 2 — design your pet

**Everything that makes the pet yours lives here** — and so does the picture of it. This is
the step the user thinks of as "designing a pet"; step 1 exists to serve it and step 3 to
animate what it produces.

**Rev.6: "See it" is not a separate step.** Rev.1–5 gave the preview a card of its own,
reasoning that *"the redraw takes ~10 s and deserves its own beat"*. It doesn't: **a preview
is the ANSWER to this step**, exactly as the box is the answer to step 1. Splitting them put
the result on a different screen from the ~17 swatches that produce it, which is the one
place they must never be — the loop here is *tweak → look → tweak*, and it only works if
both halves are visible at once (§4.8).

So step 2 has the same shape as step 1: **work → look → lock.**

| Control | Vocabulary | Status |
|---|---|---|
| Colour | **8** swatches + "natural" — trimmed from 16 (§4.6) | Was `PetDesigner.tsx:37-54` |
| Body shape | thin · normal · chubby | **New** (§7.2), data-fed from `/api/body-shapes` |
| Accessories | **12**, max 3 — trimmed from 25 (§4.6) | Was `:57-63` |
| Anything else | free text | **New** (§4.3) — what makes the trims safe |
| How far to push it | subtle · balanced · strong | Exists (`:69-73`) |
| **Preview my pet · ~10 s** | — | The loop. Press after every change |
| **Use this as my pet →** | — | The gate (§4.7) |

Body shape and free text are the only additions. They are additions *to step 2*, which costs nothing
architecturally: `compose_design` (`app.py:181`) already turns structured picks into a prompt, and the
design step is already an img2img redraw at strength 0.78–0.9. A shape is one more clause; free text
is one more clause.

### 4.1 Always required

The server keeps its *"Pick a colour or at least one accessory"* 400 (`app.py:467-468`), widened to
*"pick at least one thing"* now that shape and free text are also design inputs. A user who picks a
tabby and changes nothing is asking to *adopt*, not to *design* — and the zero-GPU adopt path exists
for exactly that (platform §4.4). Keeping the design step mandatory keeps the flow linear with no
skip-ahead branch.

### 4.2 No exceptions — and this is a fix, not a simplification

Rev.1 relaxed this guard "when `ref.source == "txt2img"`", because free text like *"a purple dragon"*
already contained the design and forcing a colour pick was nonsense.

**That exception was a bug in Rev.1, not a kindness.** It is a branch on *where the record came from* —
precisely what §6's headline rule forbids (*"the engine reads the record and acts; it never asks where
the record came from"*). Rev.1 violated its own core rule three sections after stating it.

Rev.2 has nothing to relax. You type "dragon" → you get the archetype dragon → step 2 is where purple
happens. The guard is uniform because the flow is uniform, and no record carries a `source` that
anything downstream is allowed to test. **`source` stays on the record for support and telemetry; no
runtime path may branch on it.**

### 4.3 "Anything else?" — the free-text field

Step 2's vocabulary is finite (16 colours, 25 accessories, 3 shapes). Free text is not. Today `/make`
lets someone type *"a dragon made of clockwork gears"*, and no combination of chips expresses that.

**A free-text field in step 2 preserves that capability and puts it in the right step.** It also
decides `/make`'s fate honestly (§10): with it, `/make`'s free-text half folds into step 2 and its
upload half folds into door 2, and the page can go. Without it, the product narrows and `/make` must
survive as a separate escape hatch.

Mechanically it is one more clause in `compose_design`. **Where** the clause goes needs calibration:
`compose_design:188-191` records that clause ordering was tuned on real stills (*"with the recolor
clause in the middle, the accessory gets dropped; with accessories last, the colour loses"*). Budget
one GPU session for this, the same way colour and accessory ordering were budgeted.

**This is decision #4 (§9) and needs an explicit yes/no** — it is the one open product question in
Rev.2.

### 4.4 Body shape and the silhouette question — the one real risk

Rev.1 rejected img2img-from-the-curated-base for shape changes: *"a shape change is a silhouette
change, and img2img at 0.85 would let the normal-corgi source fight it."* Under Rev.2 that concern
relocates to step 2, and it must be named plainly: **it is possible that a redraw at 0.9 from a normal
corgi produces a corgi that is only somewhat chubbier than asked.**

Three reasons this is the right risk to take:

1. **It is an empirical calibration question, and this codebase settles those by running them.**
   `PetDesigner.tsx:67` records *"below ~0.85 the base image's original colors win over the requested
   ones."* `compose_design:188-191` records the clause-ordering result. Same class of question, same
   method. If 0.9 under-delivers, the answer is prompt wording — the way `"recolored entirely {color}"`
   was the answer for colour — not architecture.
2. **The failure mode is far better than Rev.1's — for curated animals.** Redrawing from the curated
   base **preserves exactly the properties the catalog exists to guarantee** — side profile, facing
   right, framing, scale, flat shading (platform §4.1) — and risks only the single property the user
   explicitly asked to change. Rev.1's txt2img risked *all* of them to change one. **A weak "chubby"
   beats a different, unvetted animal that animates badly.**

   > **Rev.3 — state the limit of this argument.** It holds **only where a curated asset exists.** For
   > "chubby blue jay" there is no vetted file to protect: Rev.1 would have run
   > `txt2img("chubby blue jay")` — **one** pass, ~10 s, silhouette nailed by construction — where Rev.3
   > runs `txt2img("blue jay")` then img2img toward chubby: **two** passes, ~20 s, silhouette
   > negotiated against a normal-shaped source it did not need to fight. **On the long tail, Rev.3 is
   > strictly slower and strictly worse at shape.** That is a real cost, not a rounding error.
   >
   > It is still the right call, for a reason that has nothing to do with image quality: the
   > alternative is *"shape is a step-1 input iff the animal is uncurated"* — a **provenance branch**
   > (§6, §4.2), and one the user would *see*, because the shape control would migrate between steps
   > depending on which animal they typed. A uniform rule that is slightly worse on the minority path
   > beats a split rule that is better on it and incoherent everywhere. **Pay the long-tail cost
   > knowingly; do not pretend reason 2 covers it.**
3. **The mechanism for "push harder" already exists.** `compose_design` returns `min_strength`, today
   forced to `0.9` when the species name contains a conflicting colour word (`app.py:204-205`). A
   silhouette change is the same class of conflict against the source, so it is the same trigger:
   **non-default shape → `min_strength = 0.9`.** One more condition in a function that already does
   this.

**Gate (§9, decision #5):** one GPU session — redraw `dog/corgi/base.png` at 0.9 toward
`"chubby and round corgi"` and at 0.9 toward `"slender and slim corgi"`. If the silhouette moves
recognisably while identity holds, ship. If it doesn't, the fallback is **prompt wording first**, and
only if that fails does body shape leave this spec for its own (where the cost of curating
`<breed>/<shape>/base.png` can be decided by whoever pays it). **Body shape does not ship on a
hypothesis.**

### 4.5 `min_strength` must stop lying

`app.py:204-205` forces `min_strength = 0.9` on a colour-word conflict, and `:489-491` silently raises
the user's pick. A user who chose "subtle" gets "strong" with no indication — and Rev.2 *adds a second
trigger* (§4.4), which makes it worse, not better.

**The record carries `min_strength`; the strength control shows the clamp** — *"strong — required to
change a red panda's colour"*, *"strong — required to change body shape"*. Pre-existing latent
surprise; adding a trigger is the moment to surface it, not the moment to double it.

### 4.6 The vocabulary is the page (Rev.3 — the change that answers the complaint)

Everything before this section restructures. **Nothing before this section makes the page smaller**
(§1.1). The author's opening complaint was *"too many buttons and actions"*, and after two revisions the
count was flat — because the buttons were never in the flow. They are in the **vocabulary**:

| | Today | Controls | The real cost |
|---|---|---|---|
| Colour | natural + **16** swatches | **17** | A 17-target visual scan, always mounted |
| Accessories | **25** in a `<select>` | **1** | Not a control problem — a **scroll-and-scan** problem inside the dropdown |
| Strength | 3 | 3 | Fine |

**Colour is 17 of today's 29 first-paint controls. 59% of the page is one decision.** Trimming it is
the highest-leverage change in this document and the only one the author would feel.

**Decision #4 is what makes trimming safe, which is why they are one change.** A free-text field
("anything else?") is an unbounded escape hatch. With it, **8 swatches + free text is _more_ expressive
than 16 swatches alone** — "teal with gold spots" was never in the palette — while costing 8 fewer
controls. Without it, trimming is a straight capability cut and must not happen.

> **Rev.3 resolution:** trim the palette to **~8** high-contrast, prompt-legible colours + "natural".
> Keep the accessory `<select>` **as a control** (it is already 1) but trim its *list* to the ~12 that
> read clearly at sprite scale — that is scan-load, not control-count, and worth doing for the same
> reason. Free text (#4 = **yes**) covers everything cut, in both vocabularies.

**Which 8 is a content decision, not an architectural one**, and it belongs to whoever owns the look.
The engine's constraint: each must survive `compose_design`'s `"recolored entirely {colour}"` clause and
read unambiguously at 160 px. A reasonable starting set — red, orange, yellow, green, blue, purple,
pink, brown — plus "natural" is **9 controls against today's 17**.

**Do not make this data-fed yet.** `COLORS`/`ACCESSORIES`/`STRENGTHS` are hardcoded arrays
(`PetDesigner.tsx:37-73`) and stay that way here. `body_shapes` is data because it is *new* and has no
array to inherit; colour and accessories have shipped arrays and no second consumer. `CLAUDE.md`'s
"three instances before consolidating" is the same rule that keeps the modifier registry out of §7.2.
**Trimming an array is a one-line diff; promoting two arrays to data is a refactor this spec does not
need.**

**Gate: taste, not tests.** Land it inside §10's step 6 with the palette on screen and judge it by
looking. The only pin that matters is §10.2's — a trimmed palette must not change `compose_design`'s
output for a colour that survived the cut.

### 4.7 The second lock — `designConfirmed` (Rev.6)

**The exact mirror of §3.7, one step down.** `preview` means "what your pet currently looks
like"; `designConfirmed` means "and that is the pet I want". **Seeing a preview is not
choosing it**, the same way filling the box is not choosing an animal.

Any change to any design value resets it — a new design is a new question — which is the
same rule that makes a new fill reset the base. The frontier gates on it, so **step 3's
poses and the 3-minute build do not exist until the user has SEEN this pet and said yes.**
That is what makes the preview loop above safe to run as many times as they like.

It is a toggle, and it collapses green with a **🔒 Locked — click to change** header, exactly
as step 1 does. One asymmetry, and it is deliberate:

| Unlocking | Preview | Why |
|---|---|---|
| **the base** (§3.7) | **cleared** | The base is back in play, and a preview is a function of (base × design) |
| **the design** (here) | **kept** | Nothing changed — the user only reopened the question. Editing a *value* is what clears it, and that is the design-change cases' job, not the unlock's |

### 4.8 Controls left, your pet right — and sticky (Rev.6)

Step 2 is the one **split** step (`<Step layout="split">`): controls on the left, your pet on
the right, **sticky** so it stays in view while you scroll the controls that change it.

This is not decoration. The loop is *tweak → preview → tweak*, and **a result you have to
scroll away from in order to adjust is a result you cannot compare against**. Stacking the
picture above ~17 swatches put the answer off-screen from the question.

Step 1 stays centred: it has three controls, so there is no distance to close.

**The base animal moved underneath, small** — a 44 px thumbnail reading *"from a tabby"*. It
stays on screen because "what did I change?" must be answerable at a glance, but it is
reference material now, not the subject, so it is sized like it. Rev.1–5 showed it
side-by-side at near-equal weight, which gave a decided question the same prominence as a
live one.

---

## 5. The preview — step 2's answer, not a step of its own

*(Rev.1–5 titled this "Step 3 — see it" and gave it a card. §4 explains why it doesn't get
one. The mechanics below are unchanged and still load-bearing.)*

One ~10 s img2img redraw of the archetype toward the design. Mints a **new reference**
(§6.1). Pressed as often as the user likes — each press is a fresh render at whatever the
controls now say, which is the whole loop step 2 exists to run.

**Unconditional.** It follows from §4.1 — if a design always exists, a preview always makes sense — and
it removes the `previewId ? "Create my design (from the preview)" : "Create my design"` fork at
`PetDesigner.tsx:638`. ~10 s is cheap insurance against a 3-minute build of a look the user would
reject, and the deploy spec's §7 E2E gate already treats preview→create-from-preview as **the** flow
(*"the generated pet matches the preview, not a text-only pet"*).

### 5.1 The parity contract

> **The previewed still IS the base sprite `make_pet_zip` would have produced.**

Today this holds by *duplication* — `factory.py:387-392` and `:468-473` independently repeat the seed,
`_prep_reference_image`, the `min(0.9, max(0.3, …))` clamp, `_img2img_wf(_remix_prompt(…))`, and
`_wait_stable`. Two copies of a contract drift; §7.1 makes it structural, and a test pins it (§9.2).

### 5.2 Preview must have a failure path

**New in Rev.2.** Making preview unconditional removes the user's only bypass. Today a preview failure
is survivable — the `previewId ? …` fork means you can still create. Under this spec, a failed or
timed-out preview **blocks the flow with no way forward**, and every pet now consumes **two** pool jobs
(`pet_preview` at 180 s + `pet_factory` at 900 s) instead of one, on a two-node fleet.

Required: a preview failure surfaces as *"couldn't draw that — try again"* with a **retry**, and the
step-3 gate is "the user has seen a preview **or** explicitly dismissed a failure," never "a preview
exists." Capacity impact is a deploy consideration, not a blocker, but it must be stated rather than
discovered.

### 5.3 Preview must not block the event loop

`preview_design` (`app.py:446`) is **`def`, not `async def`** — load-bearing. FastAPI runs sync path
operations in a threadpool; this handler blocks ~10 s in `render_design_still` or in `pool_client`'s
poll loop. Adding an `UploadFile` tempts `async def` + `await image.read()`, **which would stall the
event loop for ~10 s per preview**, freezing `/api/job` polling for every concurrent user. Read
uploads synchronously: `body = image.file.read()`.

Note the asymmetry: `start_job` (`:747`) *is* `async def` and *does* `await image.read()` (`:891`) —
correct there, because it spawns a thread at `:905` and never blocks. **Preserve both.**

---

## 6. The architecture this produces

Everything above is UX. This section is the consequence, and it is short because the UX model did the
work.

**Every way of starting a pet ends in the same artifact: a reference still.** A name draws one (or
fetches a cached one), an upload supplies one. Today the web tier treats these as unrelated origins
and re-derives everything downstream from each one — **three separate per-origin chains**: the motion
profile at `app.py:806-807`, the description at `:835-865`, and the reference image + strength at
`:870-895`.

Make the artifact explicit — **one `reference_id` handle, minted by every source** — and everything
downstream stops caring where it came from:

| Concern | Today | Under this spec |
|---|---|---|
| Where the base image comes from | 3 origins × 3 chains, re-derived per origin | 2 doors, each minting one `reference_id` |
| What `/api/preview` accepts | house-pet id **or** catalog animal+breed (never an upload, never a name) | a `reference_id`, and nothing else |
| What `/api/generate` accepts | 9 base-related form fields across 4 branches + a fallthrough | a `reference_id` |
| Where "which branch" is decided | three chains at build time | at **fill** time, once, in `POST /api/reference` |

**The engine reads a record and acts; it never asks where the record came from.** This is the
repo-wide engine-vs-content rule (`CLAUDE.md`) applied to the reference layer. The chains are not
relocated — they are **deleted**, because the record carries what they used to re-derive.
§4.2 is the same rule pointed at the design guard.

Consequence: adding a third way to fill the box (a webcam, a DatsMe avatar) is a new branch in
`create_reference` and **nothing else** — no change to preview, generate, the engine, or the pool.

### 6.1 The reference IS the preview (one concept, not two)

`preview_id` already exists and already means "a server-side handle to a still" — `/api/preview` mints
one, `/api/generate` animates exactly that still. **`reference_id` is the same concept, and preview is
a function from one to another:**

```
archetype ──(design: colour/shape/accessories/text/strength)──▶ your pet's look ──(poses)──▶ your pet
reference₁ ─────────────────────────────────────────────────▶ reference₂ ────────────────▶ pet
```

So `/api/preview` **takes a reference and returns a reference**. Two concepts would force the frontend
and `start_job` to branch on which kind of handle they hold — precisely the source-agnosticism this
spec buys. One store, one TTL, one URL shape, one record.

The user's mental model maps onto it exactly: **reference₁ is "a blue jay", reference₂ is "my blue
jay", and step 3 animates reference₂.** Step 1 never needs to be chubby because nobody animates
reference₁.

---

## 7. What changes underneath

### 7.1 Engine — one base-sprite selector (`pet_factory/factory.py`)

Extract today's 3-branch fork (`:468-479`) into the one place the base image is decided:

```python
def _base_sprite(animal, reference_image=None, remix_strength=None, seed=None, on_stage=None) -> Path:
    """THE base-sprite selector.  remix (ref+strength) | as-is (ref alone) | text (neither)"""
```

`render_design_still` (`:381`) gains an optional `reference_image` **and an optional `seed`** and
delegates; `make_pet_zip` (`:421`) calls the same selector with `on_stage=lambda m: prog(m, 0.10)` to
keep its progress beats.

> **The `seed` parameter is not optional to the design.** Rev.1's parity test (§9.2) asserts
> byte-identical workflows "for identical args + seed", but both entry points mint their own seed
> internally today (`:387`, `:459`), so the test as written cannot be built. `render_design_still`
> must accept an optional seed for the pin to exist. Default `None` → random, as today.

**One selector, not a separate `render_base_still()`** — because §5.1's parity contract is currently
held by duplication, and a fourth copy of the txt2img branch makes drift a matter of time. The branch
is on **capability** (what inputs exist), not **provenance**, so §6's rule is intact — `make_pet_zip`
already branches exactly this way.

- Guard: `render_design_still` raises `ValueError` if `reference_image and strength is None` — as-is is
  meaningless for a *still* renderer; the caller already holds those bytes.
- **No branch is deleted.** `make_pet.sh "red panda"` and `examples/cli.py:21` still need remix and
  text. The web tier stops *using* them; the engine keeps *having* them.
- Reused unchanged: `_static_image_wf` (`:105`), `_img2img_wf` (`:123`), `_prep_reference_image`
  (`:278`), `_base_prompt` (`:294`), `_remix_prompt` (`:302`).

### 7.2 New data subpackage — `pet_factory/body_shapes/`

**Naming: `body_shape`, never "body type."** That term is already taken repo-wide for
quadruped/avian/serpentine (`CLAUDE.md`, `SPEC_MOTION_PROFILES` passim, `tiers.json`'s `_doc`). A
second meaning would confuse every future reader.

Mirrors `pet_factory/tiers/` exactly — one cached JSON, never-raises accessors, guard test. **Not**
`animal_catalog/` (that layer is archetype + breed; shapes are neither, and a global vocabulary inside
a per-animal tree invites duplication). **Not** `motion_profiles/` (that owns motion wording).

```json
{"_doc": "…", "default": "normal",
 "shapes": [{"key":"thin",   "label":"Thin",   "prompt_fragment":"slender and slim"},
            {"key":"normal", "label":"Normal", "prompt_fragment":""},
            {"key":"fat",    "label":"Chubby", "prompt_fragment":"chubby and round"}]}
```

API: `load_shapes()`, `default_shape_key()`, `list_shapes()`, `prompt_fragment(key) -> str` (unknown →
`""`), `is_default(key) -> bool` (empty → `True`).

**It feeds `compose_design`, not the archetype. The engine never learns the word "fat":**

```python
# app.py — beside the existing compose_design(:181). Shape is a modifier, like colour.
def compose_design(species, colour, accessories, body_shape=None, extra=None):
    ...
    frag = body_shapes.prompt_fragment(body_shape)          # "" for the default
    if frag:
        description = f"{frag} {description}"               # clause position: calibrate (§4.3)
        min_strength = 0.9                                  # a silhouette change fights the source (§4.4)
    ...
```

Exactly the existing precedent — `compose_design` already hands the engine composed free-form strings,
and `_base_prompt`/`_remix_prompt` take an opaque `animal`. Adding "lanky" is a one-line JSON edit.
`prompt_fragment` never reaches the browser (same posture, same reason, as the tier table, §5.3).

**What Rev.1 had here and Rev.2 deletes:**

- **`compose_species(species, body_shape)` — gone.** It existed only to inject shape into the
  *archetype* prompt. Nothing does that now.
- **The "load-bearing invariant" (default `prompt_fragment` must be `""`) — gone as an invariant.**
  Rev.1 said *"that invariant is the whole instant-base branch."* It never was. It guaranteed the two
  step-1 paths agreed on the *prompt string* for a normal corgi — while the paths could never agree on
  the *output*, one being a curated file and the other a fresh roll of the generator that file was
  selected from. It protected a consistency that did not exist. Rev.2 has one step-1 path per animal,
  so there is nothing to keep in agreement. The empty default is still **correct** (a default shape
  should contribute no words) and still **tested** — it is simply no longer holding the building up.

> **Age** ("make it young") is the obvious next modifier and lands the same way: its own data
> subpackage, one more clause, one more `min_strength` trigger. It is **not in this spec** — one new
> modifier is enough to prove the pattern, and `CLAUDE.md`'s "three instances before consolidating"
> says do **not** build a modifier registry until shape, age, and a third actually exist.

### 7.3 The reference store (`webui/app.py`)

Filesystem, not the DB — these are transient scratch bytes, not pets (`db.py`'s stated boundary).
`PREVIEW_DIR` (`:107`) holds a pair:

- `{id}.png` — the still
- `{id}.json` — `{id, owner, created_at, description, display_name, motion_profile, source, min_strength, generated}`

`_cleanup_transients` (`:1028`) already sweeps `PREVIEW_DIR` by mtime at `TRANSIENT_MAX_AGE_S`
(`:1025`, 24 h) — **the sidecar inherits that for free.** No schema migration, no new dependency
(stdlib `json`). A generate against a swept reference 400s with *"your reference expired — start
over"*, never a 500.

**Owner scoping is new and load-bearing.** `GET /api/preview/{id}` (`:529-530`) has **no ownership
check** today — only an `isalnum()` sanity check — and a reference can now be **a user's uploaded
photo**. The sidecar's `owner` gives file-backed content the rule `db._scope_clause` gives rows:
`owner is None or owner == caller`, else **404** — never 403; don't leak existence. Mirrors
`_can_access` (`:924`).

**The payoff:** because the record carries `description` / `display_name` / `motion_profile` — resolved
at fill time, where the animal and breed are known — all three chains collapse:

```python
ref = _load_reference(reference_id, owner)     # 404 not-yours/missing · 400 expired
reference_image, remix_strength = ref.path, None        # ALWAYS as-is
description  = ref.description
display_name = name or ref.display_name
motion_profile = motion_profile or ref.motion_profile
```

**A note on `description`:** it should be the **short species phrase** (`"blue jay"`), not the
~240-char composed design string `start_job:844` passes today. Since generate is now always as-is, it
steers only the motion prompts, the `breed_id` slug, and the default display name — and
`make_pet_zip:458` truncates at `[:60]`. The long composed prompt belongs in the preview step. Worth
one GPU validation run.

### 7.4 Endpoints

| Endpoint | Change |
|---|---|
| `POST /api/reference` | **New.** Multipart, **exactly-one-source** guard. Takes `catalog_animal`+`catalog_breed` \| `animal` \| `image` (+ `strength` for an upload, §3.5 — the user's faithful↔sprite pick, clamped to [0.3, 0.9] server-side). Returns a reference record |
| `POST /api/preview` | Takes `reference_id` + `colour`/`accessories`/`body_shape`/`extra`/`name`/`strength`. Returns the **same record shape**, new id. Drops `base_pet_id`/`catalog_*` |
| `GET /api/reference/{id}.png` | **New** — today's `:529-530` generalized, **plus the owner check** |
| `GET /api/body-shapes` | **New** — `{shapes:[{key,label,is_default}], default}` |
| `POST /api/generate` | Takes `reference_id`; **always** `remix_strength=None` |

One record shape, three endpoints:
`{reference_id, image_url, description, display_name, motion_profile, source, min_strength, generated}`.

`/api/body-shapes` is **separate from `/api/catalog`** because `fetchCatalog` (`api.ts:120`) returns
`data.animals ?? []` at `:124`, discarding the envelope — folding it in would churn `DesignLanding`,
`useCatalogAnimal`, and both designer pages. Mirrors `/api/motions`' precedent.

**The exactly-one-source guard closes an existing hole for free:** `:825-826` guards
`base_pet_id + image` but **nothing guards `catalog_* + image`** — and because `elif on_catalog:`
(`:882`) precedes `elif has_image:` (`:890`), catalog silently wins and the upload is dropped. One
guard at the fill point closes every pair by construction rather than by enumeration.

### 7.5 Pool handler — `pet_preview_handler.py` → v2

Make `reference_image_b64` optional: `"version": "2"` (`:25`), `"required": []` (`:45`), decode only
`if params.get("reference_image_b64")`. `needs` / `timeout_s: 180` / `preemptible` / `result_kind`
**all unchanged** — txt2img is the same Z-Image model at the same resolution, and the 180 s already
exists (`:30-33`) to cover a cold model load.

**Still required in Rev.2**, and for a cleaner reason than Rev.1's: the no-b64 path is now exactly
**the long-tail cache miss** (`_base_prompt("blue jay")` → txt2img), not "the Describe door."

**Extend, don't add a task.** The repo's "deliberately separate tasks" precedent (`CLAUDE.md`, and the
handler's own docstring) keys on *different params/results/timeouts* — `pet_preview` vs `pet_factory`
differ on all three; txt2img vs img2img differ on **params only, and only by omission**. That is the
weakest possible case for a split, and it would leave two ~95%-identical handlers to sync on two nodes
forever.

`pet_factory_handler.py` needs **no change and no rollout** — it simply stops receiving the optional
`remix_strength`.

### 7.6 Frontend (`web/src/app/design/general2/`)

**Progressive disclosure, not a wizard.** One column, one `<Step>` per phase. Wizard chrome would cost
~8-10 Next/Back controls — fighting the one thing this redesign buys — and the reference must stay
co-visible while designing and comparing (today's `original | preview` pair,
`PetDesigner.tsx:592-630`, depends on it).

That co-visibility is now doing UX work, not just layout work: **the archetype and the design sit side
by side, so the user can see what they changed.** "A blue jay" next to "my blue jay" is the clearest
possible statement of what steps 1 and 2 each did.

#### The disclosure rule (Rev.4 — this is what §1.1's numbers depend on)

> **Every step always renders its _artifact_. A step renders its _controls_ only when it is expanded.**

One rule, applied in both directions — Rev.2/Rev.3 stated only the forward half ("steps past the
frontier unmount") and left the backward half undefined, which is why §12 and §1.1 disagreed about
peak. The artifact is the picture (§2's contract column); the controls are the swatches. **Only the
picture needs to stay co-visible; 17 swatches never did.**

| Step (Rev.6 — three, §1) | Collapsed renders | Expanded adds |
|---|---|---|
| 1. Select the animal to design | the base + `🔒 Locked — click to change` (**1**) | the box, the draw button, `Use this animal →` (**3**) |
| 2. Design your pet | your pet + a design summary + `🔒 Locked — click to change` (**1**) | the vocabulary (**~17**, §4.6) + preview + `Use this as my pet →` (**~19**) |
| 3. Its moves | the chosen poses + price (**1**) | the pose menu + name + build (**~6**) — then the finished pet (§8.1) |

This is what makes §1.1's figures true, and they are arithmetic rather than estimate:

- **First paint = 3.** Step 1 expanded (the box + draw + use); steps 2–3 unmounted behind
  the lock (§3.7). This is the number Rev.1 and Rev.2 claimed and could not deliver — it
  comes from the GATE, not from disclosure.
- **Peak = ~21**, reached **at step 2**, not at the end: ~17 vocabulary + preview + use + 3
  accessory remove-chips, with step 1 collapsed to its picture.
- **Step 3 is smaller again** (~6), because steps 1 and 2 have collapsed to their pictures.
  The page is widest in the middle, which is where the work is.

> **Correction to §12:** it says *"completed steps stay mounted for the co-visibility §7.6 requires."*
> They do not, and they never needed to. Their **artifacts** stay; their controls collapse. §12's
> arithmetic (~21 peak) was right; its stated reason was wrong.

**State: a `useReducer` in a colocated `useDesignFlow()` hook.** The invalidation rules **are** the
product, and today they live implicitly across 12 `useState` + **5** `useEffect`s (`:157`, `:172`,
`:199`, `:227`, `:278`) — order-dependent, firing as separate renders. A reducer makes each transition
one atomic case.

#### The frontier is a gate, not a cursor

**Never store "where the user is."** Derive the **frontier** — the furthest step the state permits:

```ts
// StepId = 1 | 2 | 3  (Rev.6 — three steps, §1)
frontier(state) =
  reference not filled OR NOT baseConfirmed                    → 1   // the lock, §3.7
  · design untouched OR no preview OR NOT designConfirmed      → 2   // the lock, §4.7
  · else                                                       → 3
```

> **Both clauses gate on a LOCK, not on "a thing exists"**, and that symmetry is the whole
> flow in two lines. `baseConfirmed` is what earns §1.1's "3 controls at first paint" —
> step 2's ~17 controls are not mounted until the base is committed. `designConfirmed` does
> the same for step 3. Filling the box is not choosing; seeing a preview is not choosing.

> **Rev.4 fix — the derivation as written in Rev.2/Rev.3 deadlocks.** Once a preview exists,
> `frontier` is 4 *forever*: step 2's controls only mount when `frontier === 2`, which requires "design
> untouched", which a designed pet never is again. **The user could never change their mind after
> seeing the preview** — and "I don't like it, make it more purple" is the single most likely thing
> they do. The rule as stated made the flow one-way.

The fix is to separate the two things Rev.2 conflated:

```ts
frontier(state)                          // a GATE: the furthest step reachable. Derived, never stored.
expanded = min(expandedOverride ?? frontier(state), frontier(state))   // WHICH PANEL IS OPEN
```

`expandedOverride` is set by clicking `Edit ▸` / `Change ▸` on a collapsed step and cleared on any
advance. **It is not a wizard cursor** — it cannot point past the frontier (the `min` clamps it), so it
cannot desync from state; the frontier still gates everything. That is the real content of "never store
the current step": *never let a stored pointer decide what is **reachable**.* Deciding which of the
reachable panels is **open** is ordinary UI state, and pretending otherwise is what produced the
deadlock.

Re-expanding step 2 does **not** invalidate the preview — only *changing a design value* does (below).
Opening a panel is not editing it.

#### Invalidation rules (on reference change)

| | Behavior |
|---|---|
| Preview | **Cleared** — it is a function of (archetype × design) |
| Colour / accessories / **body shape** / **free text** | **Kept** — they are orthogonal design intent, and under §0.1 they were never properties of the reference. *"I want it chubby" survives changing my mind from corgi to labrador.* |
| Strength | Kept; show the `min_strength` clamp (§4.5) |
| Pose menu | **Key the transition on `motion_profile`, not `reference_id`** — cat/tabby → cat/siamese are both `quadruped`; don't refetch, don't touch picks |
| Pose picks | Intersect by name against the new menu, **re-apply the cap in the same transition**, and **notify on drop** ("swim isn't available for a corgi — removed") |

The "kept" row is a direct dividend of the archetype rule: because design inputs never lived in step 1,
changing step 1 cannot invalidate them. Rev.1 had to reason about this; Rev.2 gets it for free.

A silent pose drop changes the price with no explanation — that violates platform §5.2's disclosure
rule in spirit.

> **Correction to Rev.1:** it claimed *"today's code sidesteps this by resetting all optional picks on
> species change (`PetDesigner.tsx:187`)."* **That reset never fires on General.** The effect's deps are
> `[basePetName, catalogProfile, base.kind]` (`:196`) — species is not among them, and both catalog
> animals pin `"quadruped"`, so cat → dog leaves every dep unchanged. The line documents an intent the
> code does not implement. "Notify on drop" is therefore **new behaviour**, not a refinement of
> existing behaviour.

#### Two live bugs to fix here, not inherit

- **Preview has no cancellation** (`:254-274`). `makePreview` is a plain async click handler with no
  `cancelled` flag, no seq stamp, and an unconditional `setPreviewId` at `:268`. Change the reference
  during the 10 s redraw and the effect at `:157-160` clears the preview, then the in-flight promise
  re-sets it — from a still drawn from the **old** archetype. That stale id flows into the build at
  `:312`, so the user gets a **3-minute pet from a picture they never saw**, under a button that says
  "what you saw is what you get" (`:310-311`). `disabled={busy || previewLoading}` (`:618`) blocks a
  double-click but not this race. Stamp every async result with the `reference_id` it fired from; the
  reducer drops non-matching results. (The motions effect already has a `cancelled` flag at `:178`;
  the preview does not.)
- **`min_strength` silently overrides the user** — §4.5.

#### Files

**As built (Rev.6), colocated in `web/src/app/design/general2/`:** `designFlow.ts` (pure —
types, reducer, selectors), `useDesignFlow.ts`, `Step.tsx`, `ReferenceBox.tsx`,
`BaseAnimalDialog.tsx`, `UploadStrength.tsx`, `DesignStep.tsx`, `PoseStep.tsx`,
`PetDesigner2.tsx`, `page.tsx`.

**Shared, changed:** `web/src/components/ModalOverlay.tsx` (**new**, §3.8);
`ConfirmModal.tsx` (migrated onto it); `PetJobResult.tsx` (**+`bare`**, §8.1);
`globals.css` (**+`.input` / `.btn` / `.btn-ghost`** — the designer alone has five call
sites, and `color-scheme: dark` on `.input` is load-bearing: without it a `<select>`'s popup
renders with the OS's light defaults, i.e. white-on-white on this page).

*Rev.1–4 specified one file per door — `DoorDescribe.tsx`, then `DoorNameAnimal.tsx` +
`DoorUpload.tsx`. None survive: the doors are three answers to one question inside
`BaseAnimalDialog`, not three components (§3.1). Free text still appears twice, and that
is deliberate — "which animal" in the dialog, "anything else" in `DesignStep` (§4.3). Same
widget, two different questions; conflating them was Rev.1's mistake and remains one.*

**Rewritten:** `PetDesigner2.tsx`, 659 → ~280 lines (it is a verbatim fork of the live 649-line
`components/PetDesigner.tsx`). With `reference_id` as the spine, **`appendBaseFields` (`:245-252`) and
the `base` prop disappear entirely**, taking the dead `kind:"house"` branch with them (`housePets`
`:114`, `basePetId` `:115`, `listPets()` `:280`, the house `<select>` `:417-427`, `houseEmpty` `:352`,
the `DesignerBase` union `:104-106`, and the inert `?base` effect `:278-289`). That branch is
**verifiably unreachable** — every caller passes `kind:"catalog"` (`general/page.tsx:64`,
`cat/page.tsx:73-79`, `dog/page.tsx:67`), so the `:112` default never applies. `listPets` **stays in
`api.ts`** (`:62`) — `app/house/page.tsx:21` is still its live consumer.

**`web/src/lib/api.ts` — additive only**, so the live pages cannot regress. New: `PetReference`,
`BodyShape`, `createReference`, `referenceImageUrl`, `fetchBodyShapes`. Changed: `previewDesign`'s
return type (`{preview_id}` → `PetReference`). All credentialed (`credentials: "include"`) —
references are owner-scoped, so the launch cookie must ride.

**The body-shape control renders by mapping `/api/body-shapes`** — zero hardcoded keys, and only if ≥2
shapes come back. **Deleting the data deletes the control: that is the test that it is genuinely
data-fed.** (`COLORS`/`ACCESSORIES`/`STRENGTHS` at `:37-73` are hardcoded arrays — do **not** follow
that precedent here.)

**Reused verbatim:** `usePetJob`, `PetJobResult`, `timeHint`/`priceHint` (`:83-98`).
`/make`'s objectURL + paste logic (`make/page.tsx:24-44`) and its dropzone (`onDrop` at `:123-126`,
`dragover` at `:20`) are **copied** into `ReferenceBox` — not extracted to a shared hook, because
extracting would mean editing live `/make`, and "three instances before consolidating" says wait.

---

## 8. Step 3 — its moves, and the build

*(Rev.1–5 called these steps 4 and 5. Picking poses and pressing build are one question —
"what can it do, and what does that cost?" — and the pet is its answer, §1.)*

**The contract is unchanged.** The pose selector, cost hint, entitlement resolution, and
server-side cap clipping (`app.py:815-818`) are the motion spec's, and this spec does not
touch them: walk+idle always built, free pick up to `max_poses`, over-cap disabled with an
upsell tag, `triggered` poses hidden, browser never sees the tier table.

Poses come **after** the design is locked, so the price is disclosed once the user knows
exactly what they are buying.

`/api/generate` reduces to `{reference_id, name, poses, motion_profile}`. Everything else —
`image`, `base_pet_id`, `catalog_animal`, `catalog_breed`, `strength`, `color`,
`accessories`, `preview_id`, `text` — is gone, resolved at fill time.

### 8.1 The pet lands in the card — it does not replace the page (Rev.6)

`PetDesigner2` used to early-return `<PetJobResult>` when the job finished, **replacing the
whole page**. Steps 1 and 2 vanished the instant the pet appeared — so the thing the user
had just spent three minutes and two locked decisions on arrived on a screen with no memory
of either.

The result is **step 3's artifact**, exactly as the base is step 1's and the preview is
step 2's (§2). It renders inside step 3's card, with steps 1 and 2 still above it, green,
holding their pictures. Step 3 tints green when the pet lands.

`<PetJobResult>` gained a **`bare`** prop for this: `<Step>` already IS a card, so its own
`card` wrapper would nest two borders, two accent strips and doubled padding. The panel's
contents are what step 3 wants; the chrome is the caller's business. The prop is additive
and defaults to false, so `/make`, `SampleGallery` and the live `PetDesigner` are untouched.

It also carries the **progress bar**, so it covers the whole 3-minute build rather than just
its end — which let an ad-hoc progress line underneath the steps be deleted.

### 8.2 Green means "this pose gets built" (Rev.6)

The pill states, and why the old ones were wrong rather than merely inconsistent:

| Pose | Renders as | |
|---|---|---|
| **walk · always / idle · always** | **deep green**, filled, `cursor: default` | Always built (SPEC_MOTION_PROFILES §3.4), so they look built |
| **chosen optional** | **lighter green** | Same meaning, shade says "you added this" |
| unselected | ghost | |
| over cap | dimmed + upsell | Unchanged |

Rev.1–5 ghosted walk/idle at `opacity: 0.7` — which in this UI is exactly how a **disabled**
control looks. So the two poses every pet is *guaranteed* to have were the two that read as
switched off, while the optional ones the user picked lit up in a different colour entirely.
The visual said the opposite of the truth.

One colour, one meaning: **green = this pose gets built.** The shade carries the only
distinction that matters — the floor you always get versus what you added on top. The
always-pills are `<span>`s with `cursor: default`, not disabled buttons: they are not
unavailable, they are not negotiable.

---

## 9. Decisions

| # | Decision | Resolution | Why |
|---|---|---|---|
| 1 | **Which step owns "what it looks like"?** | **Step 2, always** | §0.1. This is the Rev.2 decision; everything else follows |
| **21** | **How many steps?** | **Three** *(revised Rev.6)* | §1. Rev.1–5 drew five by giving the preview and the build cards of their own. An ANSWER is not a step — §0's model was right from Rev.2 and took six revisions to reach the screen |
| **22** | **Does step 2 lock too?** | **YES — `designConfirmed` mirrors `baseConfirmed`** *(new in Rev.6)* | §4.7. Seeing a preview is not choosing it. Both gates read identically, which is why the flow is two lines of `frontier()` |
| **23** | **Where does the finished pet appear?** | **In step 3's card** *(new in Rev.6)* | §8.1. It used to replace the page and erase steps 1–2 — the user's own work, deleted at the moment of success |
| **24** | Pose-cap `plus.max_poses` | **10 — ⚠️ TESTING, revert to 5** *(Rev.6)* | `tiers.json`. `default_tier` is `plus`, so this is what EVERY user gets; at 50 cr/extra a 10-pose pet charges 500. Flagged in three greppable places. **The cap and the per-pose price were already data and already per-user** (`capability_tiers`) — there is nothing to build, only numbers to decide |
| 2 | Empty box or pre-filled? | **Pre-filled** | §1.1 — an empty box costs every user an action to learn something most don't care about |
| 3 | How many doors? | **Three, in a dialog behind the box** *(revised Rev.5)* | §3.1. Rev.2–4 said "two doors, and Describe is a branch of naming" — a distinction the user never had to care about, since all three now live behind one question. The box is the interface |
| **17** | **Flatten the catalog directory?** | **NO** *(new in Rev.5)* | §3.3. The gallery needs a flat LIST and already has one (`catalogBaseOptions`); the disk layout is invisible to the UI. Flattening would rewrite the loader, three promote scripts, the candidates mirror and `catalog.json`'s per-breed `motion_profile` pinning — and require parsing species+breed back out of a filename |
| **18** | **What may be a base?** | **A species + a breed. Nothing else.** *(new in Rev.5)* | §3.4. `cat/black` removed: "black" is a COLOUR, and colour is a step-2 input, so a Black Cat base is a cat already designed (§2.1). **⚠️ Open: `tabby` is a coat pattern, not a breed, and fails the same test** — removing it leaves Cat with one base, which is a content call |
| **19** | **Does locking gate step 2?** | **YES — and it is a toggle** *(new in Rev.5)* | §3.7. It is what earns "3 controls at first paint" and what makes the draw loop safe. Costs one action (~6 → ~7) |
| **20** | **Upload redraw strength** | **The user picks** *(new in Rev.5)* | §3.5. faithful (0.4) ↔ sprite (0.85, default). Likeness vs animation quality is a real trade and only the user knows which side they want |
| **4** | **Does step 2 get a free-text field?** | **YES** *(resolved Rev.3)* | §4.3. It preserves `/make`'s unbounded expressiveness in the right step, decides `/make`'s fate — **and it is the precondition for #15.** Trimming the palette without it is a capability cut |
| 9 | One button, or draw-then-commit? | **Two: draw, then use** *(superseded Rev.5)* | §3.6. Answered "one button" in Rev.4 and overtaken by §3.2 — once selection began executing immediately, draw and commit stopped being the same act. Drawing is the loop; committing ends it |
| **5** | **Does img2img at 0.9 actually change silhouette?** | **⚠️ OPEN — one GPU session** | §4.4. Body shape does not ship on a hypothesis. Fallback: **prompt wording, then drop it** *(resolved Rev.3 — no curated-shape-asset fallback; the curation cost is not worth it, and the cache rule stays absolute)* |
| **15** | **Does the vocabulary get trimmed?** | **YES — ~8 colours, ~12 accessories** *(new in Rev.3)* | §4.6. **The only change in three revisions that makes the page smaller** (29 → ~18 at first paint). Everything else buys legibility. Gated on #4 |
| **16** | Does the flow redesign reduce buttons? | **No — and stop claiming it does** | §1.1. Rev.2's "29 → 3" was impossible next to its own §3.1. Restructuring buys legibility + correctness; **only #15 buys size** |
| 6 | Can the user skip the design step? | **No** | Keeps the flow linear; "no changes" is what adopt-a-sample is for (§4.1) |
| 7 | …even for free text? | **No exception** | Rev.1's relaxation was a provenance branch violating its own §0 (§4.2) |
| 8 | Preview optional or required? | **Unconditional, with a retry path** | Follows from 6; removes the from-preview fork; 10 s vs 3 min (§5, §5.2) |
| 9 | Redraw uploads? | **Yes, in the designer — as a product decision, with `/make`'s copy** | Not a bug; not a step-0 stopgap to prod (§3.4) |
| 10 | "body type" or "body shape"? | **`body_shape`** | "body type" is taken repo-wide (§7.2) |
| 11 | Extend `pet_preview` or add a task? | **Extend to v2** | Params differ by omission only (§7.5) |
| 12 | `reference_id` and `preview_id` — one concept or two? | **One** | Preview takes a reference and returns a reference (§6.1) |
| 13 | Age, and other modifiers? | **Not in this spec** | One new modifier proves the pattern; three instances before a registry (§7.2) |
| 14 | Themed pages, `/make`, house source, samples | **Deferred** | §11 — decide once the studio is real and can be seen |

---

## 10. Build order

Each step is independently verifiable. Gates throughout:

```bash
.venv/bin/python -m pytest pet_factory/tests webui/tests
cd web && npx tsc --noEmit        # NEVER `next build` — it poisons the live dev server
```

| # | Step | Ships alone? | Fleet? |
|---|---|---|---|
| 0 | 🔬 **Calibration** — decision #5's GPU session (§4.4). Gates step 2 only | — | no |
| 1 | **Engine** — `_base_sprite`; `render_design_still(reference_image=None, seed=None)`; parity pin. CLI untouched | ✅ | no |
| 2 | **Data** — `pet_factory/body_shapes/` + guard test. No consumer yet. *Blocked by 0* | ✅ | no |
| 3 | **Handler** — `pet_preview` v2. File change only; inert until 4 | ✅ | → 4 |
| 4 | 🚩 **FLEET ROLLOUT** — v2 onto `omen-pet` + `dual-nvidia-pet` + gate | — | **YES** |
| 5 | **Web tier** — reference store, `/api/reference`, `/api/body-shapes`, `compose_design` gains shape **and free text** (#4 = yes), `reference_id` on preview+generate. Legacy fields still accepted | ✅ (local dev) | 4 gates prod only |
| 6 | **Frontend** — the flow in `/design/general2`; `api.ts` additions; **the §4.6 vocabulary trim** (taste gate, on screen) | ✅ | — |
| 7 | **Cleanup** — delete legacy params, the `has_image` branch, `:825-826`, the `preview_id` alias | ✅ | — |
| 8 | **Promote** — `general2` → `components/PetDesigner.tsx`; resolve cat/dog and `/make` (§11) | ✅ | — |

*Rev.1's step 0 (the upload stopgap to prod) is **deleted** — §3.4.*

**Step 8 is not optional and not §11's problem.** `CLAUDE.md`: *"Finish the refactor. Don't ship with a
dual-write/transition layer still in place."* Between steps 6 and 8 there are **two designer
implementations** — the new flow on General, the old shared `PetDesigner` on `/design/cat` and
`/design/dog`. The fork-into-`general2` posture is right for *building* and wrong for *resting*.
Rev.1 left promotion in its deferred list; Rev.2 makes it a numbered step.

**Frontend sub-order** (each verifiable alone): (a) `designFlow.ts` + `useDesignFlow.ts` against a
**stubbed** `createReference` returning a hardcoded catalog id — proves the entire state machine and
every §7.6 rule with zero backend; (b) `Step.tsx` + rewire `PetDesigner2` to render today's controls
through the disclosure shell; (c) `POST /api/reference` with door 1's curated branch + door 2 (pure
file I/O, no GPU, no fleet gate); (d) the long-tail txt2img branch last, behind the handler work.

### 10.1 The fleet gate (step 4)

**This blocks *deploying* the long-tail branch, not *building* it.** Dev is `PET_GEN_BACKEND=local`, so
steps 1–7 are fully buildable and testable without it. Curated animals never need it at all.

Clone `docs/SPEC_V3_FLEET_ROLLOUT.md`. v2 ⊇ v1 for existing b64 traffic (so rollback is safe), but
**new no-b64 traffic hard-fails 422 on a v1 node** — the same mixed-window 422 hazard v3 had
(runbook `:53-55`), with a *smaller* blast radius: the failure is a visible error on the long-tail
path, never a wrong pet. The real mitigation is **ordering, not a freeze** — no no-b64 traffic exists
until step 6 deploys. Back up both nodes, install back-to-back
(`pool-install-handler … --restart pool-worker-pet`) so the mixed window is seconds. Gate: version `2`
on both nodes + units restarted; `GET /api/tasks` shows `required: []`; **3–5 repeated no-b64 submits
all 201, never 422** (the fail-loud net proving no online node still advertises v1); a b64-carrying
submit still 201. Rollback is one file copy + one restart per node. **`pet_factory` is untouched — do
not reinstall it.**

### 10.2 Tests

| Test | Asserts |
|---|---|
| `test_still_branches.py` — **the parity pin** | For identical args **+ an injected seed**, `render_design_still`'s workflow is **byte-identical** to `make_pet_zip`'s base stage. This IS §5.1 (and requires §7.1's `seed` param) |
| `test_still_branches.py` | No ref → `EmptySD3LatentImage`, no `VHS_LoadImagePath`, prompt == `_base_prompt`; ref+strength → `_remix_prompt`, denoise clamps 0.1→0.3 / 5.0→0.9; as-is → `ValueError` |
| `test_body_shapes.py` | Default's `prompt_fragment == ""`; exactly one default; unknown key → `""` not a raise |
| **`test_compose_design.py`** | **The archetype rule, mechanised:** shape/text reach `compose_design` and **never** `_base_prompt`; non-default shape → `min_strength == 0.9`; default shape → description byte-identical to no-shape |
| **`test_compose_design.py`** — §4.6's pin | **A colour that survived the palette trim composes byte-identically to before the trim.** The trim is a UI-array edit; it must not touch prompt semantics. *(Rev.4: §4.6 cited this pin; it did not exist here.)* |
| **`test_step1_is_shape_blind.py`** | **`POST /api/reference` rejects (or ignores) any design field.** The `is_default`-fast-path regression Rev.1 would have shipped, caught by construction |
| `test_reference_flow.py` | `test_curated_pick_never_touches_the_gpu` — a curated breed fills with **zero** render calls, for **every** shape and colour the user later picks |
| `test_reference_flow.py` | `test_upload_reference_is_redrawn_not_animated_asis` (§3.4): render called with non-None strength |
| `test_reference_flow.py` | Exactly-one-source 400s **incl. the `catalog_*+image` hole**; MIME 400; oversize 413 |
| `test_reference_flow.py` | `test_reference_is_owner_scoped` — A's reference 404s for B on both the PNG and generate |
| `test_generate_is_always_as_is.py` | Pool submit params carry `reference_image_b64` and **`"remix_strength" not in params`**. **Web-tier level only** — not a factory assertion; the CLI still needs that branch |
| `test_pool_backend.py` (extend) | `pet_preview` METADATA version == 2, `reference_image_b64` not required; v2 still accepts v1-shaped params |

`test_step1_is_shape_blind.py` and `test_compose_design.py` are **the guard tests for §0.1**. The rule
is the product; an untested rule is a comment.

**Must stay green, untouched:** `test_pool_backend.py:289` (`test_pool_mode_never_imports_the_ml_factory`
— the GPU-less gate that also proves `body_shapes` is ML-free), `test_motions_endpoint.py:292-315`
(pose cap), `test_scoping.py`.

### 10.3 Manual E2E (`./start_all.sh`, `PET_GEN_BACKEND=local`, `:19955`)

1. `/design/general2` → box **pre-filled with a picture**, step 2 open, ~6 actions to a pet.
2. **The archetype reads as generic.** The box shows a plain tabby — not designed, not coloured, not
   wearing anything. A user asked "is that your pet?" should say *"no, that's just a cat."*
3. **Curated is always free, whatever you design:** pick corgi → base appears instantly, no GPU (watch
   `logs/`) → then pick Chubby + purple + wizard hat → **step 1 still never regenerates**. This is the
   Rev.1 regression, gone.
4. **Long tail:** type "blue jay" → "Draw it · ~10 s" → an archetype blue jay appears.
5. **Shape works:** Chubby → preview shows a chubbier animal that is still recognisably the same
   breed (decision #5).
6. **Strength stops lying:** pick Chubby with strength "subtle" → the control **shows** the clamp.
7. **Upload redraw:** upload a photo → the box shows a **redrawn sprite**, not the raw photo.
8. **The race:** start a preview, change the animal mid-flight → the stale preview must not land.
9. **Design survives an animal change:** set purple + Chubby, then switch corgi → labrador → **the
   design is kept** (§7.6), only the preview clears.
10. **Preview failure:** kill ComfyUI mid-preview → an error + retry, not a dead end (§5.2).
11. **Regression:** `/design/general`, `/design/cat`, `/design/dog`, `/make` all still work.

**GPU-less posture:** `import numpy` must still fail in the prod venv; `body_shapes` stays stdlib-only.
**Never add a module-top ML import** to `webui/` or a `pet_factory` data subpackage.

---

## 11. What this spec does NOT change

Deliberately deferred until the studio is real and can be seen. **Note that promoting `general2` over
the shared component is *not* on this list any more — it is build step 8.**

- **`/design/cat` and `/design/dog`.** Once the door set exists, a themed page either shows an
  incoherent "upload a photo of your ferret" door or locks the box to door 1 — and locking it is *a
  themed page owning a private copy of how generation works*, which platform §0 forbids. The likely end
  state is **merchandising + sample-adoption pages that hand off** via `?animal=cat&breed=tabby`. Not
  decided here, but decided at step 8.
- **`/make`.** Its two capabilities become door 2 and (if decision #4 is yes) step 2's free-text field.
  It has no external contract — the DPP launch targets `/design` only (`test_front_door.py:22-56`,
  `return=/design`) — so deletion is likely. **Decision #4 forces this call rather than deferring it.**
- **The house-pet source** (§3.5) and `/house`'s broken Redesign link (`house/page.tsx:87`). Note it is
  broken twice over: the only code that reads `?base` is `PetDesigner.tsx:283`, inside the dead
  `kind:"house"` branch.
- **`SampleGallery`** — renders nothing (`SampleGallery.tsx:36`) because `catalog.json` defines no
  samples. This is a **content gap, not a code gap**: a real dog sample sits staged at
  `_candidates/dog/samples/friendlypup.zip` (commit `b64dc3c`), one `promote_sample.py dog friendlypup`
  from rendering. It is also the zero-GPU business lever (platform §4.4) and the likely reason themed
  pages survive — so the themed-page decision and the sample decision are the same decision.
- **`SPEC_PET_DESIGNER_PLATFORM` §3.3's rewrite.** Its Rev.1–4 text mandates General = *"free-text,
  redesign-any-house-pet, no theming, everything exposed"* — but `53da4fd` moved free-text out to
  `/make` and `74c1783` replaced house pets with curated bases, and **`general/page.tsx:4` now cites
  §3.3 as authority for the opposite of what §3.3 says.** The misattribution is duplicated into
  `general2/page.tsx:11`. Both were deliberate product decisions; the spec was never updated, and its
  §8 "General never regresses" guard has now been silently broken twice. **Practical note for anyone
  reading §3.3 as a constraint on this work: it is not one — it has already been overridden in
  practice.** The rewrite belongs with the §11 decisions, in one commit, recorded rather than quietly
  amended.

---

## 12. Corrections to Rev.2's claims (Rev.3)

Rev.2's audit of Rev.1 was itself audited against `3c2c071`. **Its corrections all verified** — the
`_base_prompt`/`_remix_prompt` asymmetry (`factory.py:294-310`, comment and all), the `:187` reset never
firing (deps at `:196` genuinely exclude species), the unbuildable seed pin, the provenance-branch
self-contradiction, and the upload reframe. Rev.2 is a more rigorous document than Rev.1 and its
architecture stands.

These did not verify:

| Rev.2 claim | Reality |
|---|---|
| *"Controls at first paint: 29 → **3**"* (§1.1) | **Impossible next to its own §3.1**, which lands the box pre-filled *"with step 2 open"* — and step 2 is ~25 controls. First paint was ~26. Inherited from Rev.1, which made the identical error. Fixed: §1.1 |
| *"today's page opens with 29 controls **and no picture**"* (§0.3), *"the point of the whole redesign"* | **False.** `PetDesigner.tsx:340-349` renders the curated base at 160 px on load — `base.kind === "catalog" && breedKey && speciesKey` all hold at first paint because breed is pre-selected — and `:594` renders it again as "original". Fixed: §0.3 |
| *"Step 1's output is never the user's pet. It is generic on purpose"* (§2) | **False for door 2** — an uploaded photo of your dog is maximally specific. And §3.5's argument against house pets (*"somebody's finished design, not an archetype"*) indicts uploads identically while Rev.2 keeps them. The rule is about **authorship**, not genericness. Fixed: §2.1 |
| §4.4 reason 2: redrawing from the curated base *"preserves exactly the properties the catalog exists to guarantee"* | **Holds only where a curated asset exists.** On the long tail there is nothing to preserve, and Rev.2 is strictly slower (two passes) and strictly worse at silhouette than Rev.1 there. Still the right call — the alternative is a visible provenance branch — but the cost is real. Fixed: §4.4 |
| *"Peak controls: ~22"* (§1.1) | Undercounted — step 2 alone is ~25. ~30 without §4.6; ~21 with it. **(Rev.4: this row's stated reason — "completed steps stay mounted for the co-visibility §7.6 requires" — was itself wrong. Completed steps keep their *artifact*, not their controls; §7.6's disclosure rule now says so, and ~21 follows as arithmetic.)** |
| *"Rev.2 is smaller than Rev.1… adds one genuinely new capability instead of two"* | True of the architecture, **not** of the surface: Rev.2 *added* two step-2 controls (shape, free text) and removed none, taking total controls 29 → ~30. §4.6 is what makes the "smaller" claim true |

---

## 13. Corrections to Rev.1–4's step 1 (Rev.5)

§3 was specified three times and rebuilt six. What follows is what did not survive contact
with the running app — recorded because the *pattern* matters more than the individual
misses.

| Rev.1–4 claim | Reality |
|---|---|
| *"Two doors, not three"* (§3.2) — Describe is a branch of naming, not a door | True of the mechanism, irrelevant to the user. All three now sit behind ONE question in a dialog, so the distinction the spec argued for is one nobody has to hold (§3.1) |
| Cascading `species → breed` dropdowns | Never built. The bases are images; the gallery shows them (§3.3). The spec spent four revisions describing a picker that hid the thing being picked |
| *"'Change' reopens the chooser with the previous door pre-selected"* (§3.1) | The requirement was right and the first build broke it: `<Step>` unmounts its children on collapse, so the chooser's state was destroyed on every close and it reopened claiming Cat/Tabby over a corgi. Fixed by lifting the draft to the parent |
| Uploads redrawn at `UPLOAD_REDRAW_STRENGTH = 0.85` | Now the user's pick (§3.5). The constant survives as the default only |
| Decision #9: one button, "Use / Redraw" | Superseded by §3.2. Answered honestly, then overtaken by a later decision — which is what a decisions table is for |
| *"3 controls at first paint"* (Rev.1) → *"impossible, it is ~18"* (Rev.3) | **Both wrong.** Rev.1 could not deliver it because its own §3.1 opened step 2 immediately; Rev.3 was right about Rev.1 and wrong to conclude the number was unreachable. The LOCK reaches it — by not mounting step 2, not by disclosure (§1.1, §3.7) |
| `cat/black` shipped as a curated base | A colour is not a breed, and colour is a step-2 input (§3.4). The archetype rule was stated for controls and never applied to the content it governs |

**The pattern worth keeping:** every miss above is the same one — *specifying an interface
instead of describing the artifact and letting the interface follow*. The bases are
pictures; the box is the subject; the dialog is one question. Each correction removed
something the spec had invented and put back something the material already implied. §3 is
now written from the built screen for exactly that reason.

---

## Appendix — corrections to Rev.1's factual claims

Rev.1's grounding was audited against `3c2c071`. Most claims verified exactly, including the upload
mechanism, the duplicated redraw logic, the missing owner check, the sync/async asymmetry, the
`min_strength` override, the `catalog_*+image` hole, and the 29-controls-at-first-paint count. The
following did not, and are corrected in place above:

| Rev.1 claim | Reality |
|---|---|
| "a 5-way `if/elif` chain at `:870-895` … decides the reference image, the strength, the description, and the motion profile" | **Three separate chains**: motion profile `:806-807`, description `:835-865`, reference+strength `:870-895` (4 arms + a fallthrough). Rev.1's §6.3 got this right (`:870-895` *and most of* `:775-859`); its §0 headline did not. The corrected version **strengthens** the argument — three chains collapse, not one (§6) |
| "~12 `useState` + 4 effects" | 12 `useState` ✓, but **5** effects: `:157`, `:172`, `:199`, `:227`, `:278` |
| "Peak controls on screen: 29" | **32** — 3 accessory remove-chips render while the select stays mounted (§1.1) |
| "Today's code … resets all optional picks on species change (`:187`)" | **The reset never fires on General** — deps `[basePetName, catalogProfile, base.kind]` exclude species, and cat/dog both pin `quadruped` (§7.6) |
| "The `strength` form field is accepted and silently ignored" (upload) | True at the API level, but **unreachable from any shipped UI** — `/make` posts only `name`/`text`/`image`, and `strength` is absent from `api.ts` entirely (§3.4) |
| "Uploads are never redrawn — the bug this fixes" | Not a bug. The as-is branch is documented intentional behaviour with a stated precondition (`factory.py:429-437`) and `/make` advertises it (`make/page.tsx:144`). It is a **product gap**, and the fix is a **product decision** (§3.4) |
| Parity pin: "identical args + seed" | Unbuildable as specified — both entry points mint seeds internally (`:387`, `:459`). Requires §7.1's `seed` param |
| "That invariant is the whole instant-base branch" (default `prompt_fragment == ""`) | It protected agreement between two step-1 paths on the *prompt*, while their *outputs* could never agree (curated file vs fresh roll). Moot in Rev.2 (§7.2) |
| `/make` copy: "advertises this as a feature" | ✓, though the actual words are *"with an image, the animation is built from YOUR picture; without one, the pet is drawn from the description"* (`:144`); the dropzone is at `:123-126`, not in the cited `:24-44` range |
