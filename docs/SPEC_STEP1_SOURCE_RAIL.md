# SPEC — Step 1's source rail (the three doors move onto the page)

**Status:** **BUILT**, 2026-07-23. **Rev.8** — adds §1.12: the upload strength chooser is
removed, because step 2's mandatory redraw overwrote the choice before it reached the
animation. **Rev.7** — adds §1.11: every door owns its own controls,
so the upload's strength chips and **Draw it** move inside the upload door instead of sitting
at the foot of the column. **Rev.6** — adds §1.10: one intake gate for uploaded
photos — format checked on all three paths, oversized images downscaled client-side instead
of rejected. **Rev.5** — adds §1.9: the caption speaks only when it has
news, the drop hint is a hover overlay, and the two columns end on one line. **Rev.4** — Rev.2's design plus three rounds of correction
made against the running screen: the doors are buttons, not rows (§1.6); the commit sits under
the picture and only exists once one is drawn (§1.7); the card names its step, the rail's
preamble is deleted, and the three step-advancing buttons are filled (§1.8). Rev.2 inlined the
typed door and made the dialog gallery-only; see §12 for what changed from Rev.1 and why.
**Amends:** `SPEC_PET_DESIGNER_FLOW` §3.1, §3.2, §3.6, §3.8, §4.8, §1.1.
**Touches:** `web/src/app/design/general/` only. No backend, no engine, no contract change.

Step 1 asks one question — *where should the base animal come from?* — and today that
question is **not on the screen**. It lives behind an unlabelled click on a picture. This
spec puts it on the page, and gives the picture a more honest job.

---

## 0. The problem, stated from the running app

Step 1 lands pre-filled with a curated base (`Designer.tsx:93-106`). What a first-time
user sees is a cat, a **Use this animal →** button, and one line of faint mono caption
under the box:

> `click to change · or drop a photo`  — `ReferenceBox.tsx:135`

That caption is the *entire* disclosure of step 1's three doors. Read it as a new user:

| The door | What the caption tells you about it |
|---|---|
| Use an existing base animal | "change" — implies a list exists. Roughly honest |
| Use my own picture | "or drop a photo" — discoverable, if you notice 11 px of mono |
| **Type the animal I want** | **nothing at all** |

The third row is the problem. *Type an animal name, get a ready-to-use pet* is the
sentence this repo's `CLAUDE.md` opens with — it is the product — and in the shipped
designer it is **invisible until you click a picture that gives no sign it is a menu**.
A user who wants a blue jay has no evidence the app can draw one.

This is not a copy bug. It is what §3.1's *"the box is the interface"* costs when the box
lands pre-filled: **a filled box looks like an answer, so nobody clicks it to find the
question.** The pre-fill (§3.1, correctly, for the majority who want a normal cat) and the
click-to-discover chooser are individually right and jointly hide the product.

**The guardrail is hidden with it.** The sentence that stops users designing in step 1 —
*"This is just the starting picture — you'll make it yours in the next step"*
(`BaseAnimalDialog.tsx:70`) — is inside the same modal nobody opens. §3.2 calls the
archetype rule the highest-risk thing in the flow, and its only mitigation currently ships
behind a click that §0 has just established does not happen.

---

## 1. The design

### 1.1 The three doors move onto the page

Step 1 becomes a **split** step — the same layout step 2 already uses (§4.8) — with the
three sources stated in the left column:

```
┌─ Step 1 — Select the Animal to Design ───────────────────────────┐
│                                                                  │
│                                          ┌──────────────────┐    │
│                                          │                  │    │
│                                          │                  │    │
│  ┃┌────┬───────────────────────────┐     │    [ the base    │    │
│  ┃│ 🐾 │ Use an existing base animal│    │      animal ]    │    │
│  ┃│    │ free · instant             │    │                  │    │
│  ┃└────┴───────────────────────────┘     └──────────────────┘    │
│   ┌────┬───────────────────────────┐           Tabby             │
│   │ 📷 │ Use my own picture         │      drop a photo here     │
│   │    │ ~10 s · redrawn as a sprite│                            │
│   └────┴───────────────────────────┘     [ Use this animal → ]   │
│   ┌────┬───────────────────────────┐        ↑ only once drawn    │
│   │ ✏️ │ Or type any animal         │                            │
│   │    │ ~10 s · drawn from scratch │                            │
│   │ ┌──────────────┐ [ Draw it ]   │                             │
│   │ │ blue jay     │               │                             │
│   │ └──────────────┘               │                             │
│   └────────────────────────────────┘                             │
│                                                                  │
│   ── faithful ↔ sprite ──   ┐                                    │
│   [ Draw it again · ~10 s ] ┘ uploads only                       │
└──────────────────────────────────────────────────────────────────┘
   ┃ = the current-source edge, in that door's own colour
   [ Use this animal → ] is FILLED (`.btn-step`) — see §1.8
```

Two doors are buttons; **the third is the door standing open.** The rail is the only place
the source question is asked, and each button goes straight to its answer surface — it
does not open a menu that repeats what is already on screen:

| Rail slot | Goes to | Note |
|---|---|---|
| **Use an existing base animal** | the gallery dialog | skips a click that existed only to re-ask a visible question |
| **Use my own picture** | the **OS file dialog**, directly | no app dialog is involved at all |
| **Or type any animal** | *nothing — the field is right there* | the headline capability is demonstrated, not described |

The left column reads *where from → adjust → commit*, top to bottom: rail, then
`<UploadStrength>` when an upload is pending, then **Draw it** / **Use this animal →**.
That is the same reading order the step already has, made vertical.

### 1.2 Why the typed door is the one that inlines

The three doors are not equivalent, and treating them as three identical buttons answers
§0 only halfway — it makes the missing door *visible* while leaving it the least prominent
thing in a low-contrast column, and still two interactions deep.

The asymmetry that decides it is **how much surface each answer needs**:

| Door | Its answer surface | Fits a 280 px column? |
|---|---|---|
| Existing base animal | a grid of thumbnails, growing one folder per animal (§3.3) | **No** — decision #3 |
| My own picture | the OS file dialog | N/A — not ours to place |
| Type any animal | **one text input** | **Yes, trivially** |

A text input is the whole door. Putting it behind a button that opens a modal containing
one text input is ceremony around a control that could simply be present — and it is
ceremony in front of the exact capability §0 says users cannot find.

Inlining it also **moves the archetype guardrail onto the page**. The field, its
*"Or type any animal"* label, its `blue jay` placeholder and the *"Any animal. It gets
drawn from scratch"* sub-line are now permanently co-visible, as is the rail's
*"just the starting picture"* line. Today all four are inside the unopened modal. The
copy that protects §3.2's rule gets **more** exposure, not less — which is the answer to
the obvious objection that an always-visible text field invites people to type designs
into step 1 (§9, decision #4).

### 1.3 The dialog becomes the gallery, and only the gallery

`<BaseAnimalDialog>` today holds three views. The `"choices"` view
(`BaseAnimalDialog.tsx:76-94`) is **promoted onto the page** as the rail; the `"typed"`
view (`:128-168`) is **promoted onto the page** as the field. What is left is the gallery.

So the `View` union, the `view` state, and the `close()` reset all **disappear** — the
file goes from three views to none:

> **The rail asks the question. The dialog only ever shows one answer surface.**
> One room, one door: *"which source?"* is answered by the rail, *"which breed?"* by the
> gallery, *"which animal?"* by the field on the page.

This is the structural point of the whole change, and it is what makes the change
*smaller* than it looks: a one-view dialog needs no view plumbing, and the
`initialView`-prop design an earlier draft of this spec proposed is not merely unnecessary
but was **broken** — see §10, rejected alternative E. Deleting the state deletes the bug.

Because it is now a gallery and nothing else, the file is renamed
`BaseAnimalDialog.tsx` → **`BaseGalleryDialog.tsx`**. Its header comment describes three
doors and must be rewritten regardless; the name should stop claiming a job it no longer
has.

The `← other options` back-link (`BaseAnimalDialog.tsx:124, 187-193`) survives with a new
target: it **closes the dialog**, because closing is now exactly what reveals the other
options. Keeping a way back matters — the overlay covers the rail while it is open, and
Escape and backdrop-click (`ModalOverlay.tsx:45-48, 83`) are both undiscoverable.

### 1.4 The image keeps its click; the caption stops repeating the rail

Clicking the box opens the gallery. Click a picture, get more pictures — the box shows a
curated tabby, and clicking it shows the other curated bases. That is what a user expects
a clicked picture to do, and it must **not** reopen a three-choice menu.

**Drag, drop, and paste on the box are unchanged** (`ReferenceBox.tsx:60-68, 93-99`),
including the unlock-on-photo rule (`Designer.tsx:111-123`).

The caption changes job. With the rail on screen, *"click to change"* states something the
rail already states better, so the caption keeps only the one affordance nothing else on
the page reveals — **drop**:

| Where | Today | Becomes |
|---|---|---|
| Box caption (unlocked, nothing pending) | `click to change · or drop a photo` | **nothing at all** — see §1.9; the drop hint is a hover overlay |
| Box `aria-label` (`:80`) | `Your base animal — click to change it` | `Your base animal — click to browse the gallery` |
| Empty-box caption (`:123`) | `click to choose a base animal` | unchanged — still correct, and the rail is beside it |

The `aria-label` still describes the click because the box is a real focusable
`role="button"` (`:78-79`) and a focusable control must announce what it does. Sighted
discovery of the click is not lost — the rail's first button reaches the same gallery.

### 1.5 The rail marks the current source

The slot matching `pending?.kind` carries a **faint accent left edge**. The two buttons
also carry `aria-current="true"`.

The edge is `2px solid` in both states — `var(--accent)` when current, `transparent`
otherwise — so marking a slot never shifts the layout.

It is deliberately **not** styled as a selected radio (no fill, no check, no pressed
state). These slots open doors; they do not select. Decision #6 records the risk, and why
`aria-pressed` and `role="radio"` are both wrong here.

The typed row is marked with the edge only, no `aria-current`: its `<input>` already
carries the animal name as its value, which states the same thing more directly than an
ARIA flag on a text field would.

### 1.6 They have to read as buttons *(Rev.3 — from the built screen)*

The first build shipped the doors as **full-width rows with the hint pushed to the far
right**, inherited unexamined from the dialog's `Choice`, where a full-width row was
correct: it filled a modal that contained nothing else. On the page, beside a 200 px
picture, the same shape reads as *a table of text*. A control that spans its whole column
and carries no weight of its own does not invite a click — which reproduces §0's bug in a
new register: the doors were visible and still did not look operable.

Three changes, all cosmetic, none structural:

| | |
|---|---|
| **A glyph, in its own colour** | 🐾 existing · 📷 my own picture · ✏️ type any animal. A 34 px chip with a tinted fill and border. The glyph carries the colour and most of the visual weight, and it says *what kind of answer this door gives* before the label is read |
| **One brand colour per door** | `--green` (curated: free, instant, safe), `--accent` indigo (the primary-action colour, for upload), `--gold` purple (drawn from nothing). All three are **read from `globals.css`**; `color-mix(in srgb, …)` derives the soft fills, so the palette keeps exactly one home and this file re-declares nothing |
| **Label over hint, capped at `26rem`** | Stacking makes the block button-shaped instead of line-shaped, and the cap — a bit under half the card — stops it reading as a section header. The box it fills is 200 px; these should look like its siblings, not like the page |

**Colour does not become the current-marker.** §1.5's rule survives intact: current is still
a border treatment — the door's own colour on the left edge, mixed into the rest of the
border — and never a fill, check or pressed state. The per-door colours are *identity*, the
edge is *state*, and keeping those on different visual channels is what stops the rail
reading as a radio group.

### 1.7 The commit belongs to the picture, and only exists once there is one

**It moves out of the left column and under the box**, and it is **rendered, not disabled**.

*Where.* **Use this animal →** commits what the box is showing. Sitting at the bottom of a
column of source controls, it read as the last item in that list — one more thing to do
after typing — when it is actually the answer to the picture two feet to its right. Under
the picture it is unambiguous: this button is about *that*.

*When.* Its disabled rule was `!reference || busy || (pending && !pendingDrawn)` — exactly
"there is no finished animal on screen". A button greyed out for that reason asks the user
to work out why it is dead; the box directly above it already says `drawing…` or
`not drawn yet — press draw`. So the same predicate now decides whether it **exists**:

> `showsControls(state, axes, 1) && baseIsDrawn`

It appears the moment the picture does. At first paint the curated pre-fill is already
drawn, so it is there — the flow does not gain a step.

> **It sits in the `artifact` slot, which `<Step>` renders in EVERY state** — so it must
> gate on `showsControls` itself. Without that it would survive the collapse and offer to
> re-lock an already-locked step, which is the header toggle's job (§3.7). This is the one
> place the move costs something, and it is one clause.

The undrawn-typed-draft case (§9.15) is **unchanged**: a draft never touches `pending`, so
`baseIsDrawn` stays true and the button stays present and clickable. Everything §9.15 argues
about *enabled* now reads as *present*.

### 1.8 The card names its step, drops its preamble, and its exit button is filled *(Rev.4)*

Three changes made against the built screen. The first two are step 1's; the third is the
whole designer's.

**The heading names the step.** `Step 1 — Select the Animal to Design`, replacing a faint
mono numeral beside a title. The numeral read as decoration — a list marker — when the page
header directly above it promises *step 1 · step 2 · step 3*. Naming the step in the card's
own heading is what ties the two together. Applied in `<Step>`, so all three cards get it:
this is the shell's job, and a format that only step 1 used would be the engine branching on
which step it was rendering.

**The preamble is deleted.** `Where should it come from?` and `This is just the starting
picture — you'll make it yours in the next step.` are both gone.

> The heading asked a question the three doors answer in their own labels — *use an existing
> base animal · use my own picture · or type any animal*. A question above its own answers is
> a caption on a photograph of itself.

The second line was doing real work — it is §3.2's archetype guardrail, and §1.2 counted
moving it out of the modal as a win. Deleting it is a genuine cost, and it is **paid, not
absorbed**:

- The page header already frames step 1 as *"Start from what a typical animal looks like"* —
  the same guardrail, stated once, above all three cards rather than inside one.
- The typed door — the only door through which a design can actually be typed — still says
  **`Or type any animal`**, `~10 s · drawn from scratch`, and shows `blue jay`. The mitigation
  now sits on the control it mitigates instead of two inches above it, which is arguably
  where it belonged.

If typed-in designs ever show up in the logs, the fix is copy **on the typed row**, not a
restored paragraph over the whole rail.

**The step button is filled — `.btn-step`, and there are exactly three.**

| | |
|---|---|
| `Use this animal →` | step 1's lock (§3.7) |
| `Use this as my pet →` | step 2's lock (§4.7) |
| `Bring it to life · ~3 min` | the build (§8) |

Solid `--accent`, white text, semibold, where every other button on the page is outlined
(`.btn`) or ghosted (`.btn-ghost`). The designer is a spine of three locks surrounded by
**loop** buttons — *Draw it*, *Preview my pet*, *Try again* — which may be pressed any number
of times or never. Rendering both kinds as `.btn` made the flow's three real decisions look
like six equal options.

> **The rule that keeps it worth anything: `.btn-step` is for controls that can only be
> pressed once per step.** The moment a loop button wears it the signal is gone. This is
> stated in `globals.css` above the class, because that is where someone reaching for it will
> be standing.

### 1.9 The caption speaks only when it has news, and the two columns end on one line *(Rev.5)*

**The permanent caption is gone.** The box carried two lines under it in every state — the
animal's name, and `drop a photo here`. Both were noise once the rail existed:

- *the name* — you can see it is a tabby; you typed "blue jay" and a blue jay appeared. The
  one place it genuinely informs is the **collapsed** step, where `<Step summary>` already
  shows it.
- *`drop a photo here`* — a permanent line spent on a capability most users never reach for,
  sitting one line under `Tabby` where it read as a description of the tabby.

Three states remain, and each **explains something the picture cannot**:

| | |
|---|---|
| `drawing…` | a ~10 s render is in flight. The image dims, but dimming does not say *wait* |
| `not drawn yet — press draw` | **why there is no commit button** (§1.7). A button that vanishes with no explanation is precisely what that rule exists to avoid — this line is the other half of it |
| `🔒 locked in` | settled, step 2 open (§3.7) |

A drawn, unlocked animal — the common case — says nothing at all.

**The drop affordance became a hover overlay** *inside* the box: `drop your own image`, and
`drop to use it` in green while a file is actually over it. Two things about it are
deliberate:

> It is **inside** the box, not a caption line that appears below it. A line appearing under
> the picture on hover would shove the commit button down every time the pointer crossed the
> image.
>
> It is `pointer-events-none`. An element under the cursor that accepts pointer events fires
> `dragleave` as the file passes over it, and the drop lands on nothing — the overlay would
> have broken the very feature it advertises.

*Not a `title=` tooltip:* `CLAUDE.md` forbids native `title` and requires a shared tooltip
component, and none exists in this repo. Building one — portal, positioning, hover+focus,
touch — for a single call site is out of scope here, and the overlay needs none of it.
**If a third native-`title` call site ever appears** (`UploadStrength.tsx:51` and
`BaseGalleryDialog.tsx` are the two today), that is the moment to build the primitive and
migrate all three.

**The columns now end on one line.** Removing the caption block took 24 px out of the
artifact column; the remaining 22 px came from `-mt-3` on the artifact wrapper, which cancels
the split row's own `mt-3` (`Step.tsx:94`) so the picture sits flush with the header baseline.
Measured result: the commit button's centre is **6 px** from the rail's last button — the two
read as one row of work rather than a caption stack drifting below a form.

> **The `-mt-3` is scoped to `step1Open`.** Collapsed, `<Step>` wraps the artifact in its own
> `mt-3` beside a live *🔒 Locked* button; cancelling the gap there would crowd them. Same
> predicate as the commit button's existence, computed once.

### 1.10 One gate for uploaded photos — validate, downscale, then send *(Rev.6)*

Three ways in, and before this only one of them checked anything:

| Path | Was | Now |
|---|---|---|
| **Use my own picture** (OS picker) | `accept="image/png,…"` — matched the server | `accept={ACCEPT_ATTR}`, from the same constant that enforces it |
| **Drag & drop** | **nothing.** Verified by dropping a 4-byte `notes.txt` — accepted, strength slider and all | gated |
| **Paste** | `type.startsWith("image/")` — let HEIC, BMP, AVIF, SVG through | gated |

Every path already funnelled through `acceptPhoto`, so **one function covers all three**.
That is why this is small, and it is the same property §1.7 relied on.

**Size was the worse half.** The server's 12 MB cap is a hard `413` with no downscale
(`app.py:819`) — while `_encode_reference_image` (`app.py:302`) thumbnails every *accepted*
image to ≤1024 px four lines later. A 12.1 MB photo was rejected for exceeding a budget
nothing downstream cared about, **after** uploading in full. `prepareUpload` does on the
client what the server was always going to do, before the bytes move.

> **`MAX_PX = 1024` is not a number invented here** — it is `_encode_reference_image`'s own
> `max_px`. Downscaling to it costs nothing in output quality: the worker re-pads to a
> square canvas regardless.

**Re-encoding can lose, and the guard for that is the part worth remembering.** Measured: a
3000 px PNG at **548 KB** became a 1024 px PNG at **2.9 MB**. Resampling raises entropy, so
fewer pixels is not automatically fewer bytes. When the re-encode is not smaller and the
original already fits, **the original wins** — bytes are what this is fixing, and the server
downscales to the same 1024 px anyway.

Measured across the cases (dropped through the real UI, Playwright):

| Input | Result |
|---|---|
| 4000×3000 JPEG, 11.2 MB | **221 KB** JPEG — would previously have been a `413` |
| 3000×3000 PNG, 548 KB | **548 KB**, untouched — the re-encode lost, so it was discarded |
| 512×512 PNG, 22 KB | **untouched** — already inside `MAX_PX`, and re-encoding would only shed quality |
| `IMG_4821.HEIC` | rejected: *"iPhone HEIC photos aren't supported yet — save it as JPEG or PNG first…"* |
| `shot.bmp` | rejected: *"BMP images aren't supported. Use a PNG, JPEG, WebP or GIF."* |
| `notes.txt` | rejected: *"That doesn't look like an image…"* |

**What this deliberately does NOT do:**

- **It does not raise or remove the server's cap.** `MAX_UPLOAD_BYTES` is the security
  boundary and a direct API call never touches this file. What changed is that the UI can no
  longer produce something that trips it. Relaxing a server limit because the client became
  polite is the wrong lesson.
- **It does not convert HEIC.** No browser outside Safari decodes it, and a wasm decoder is
  ~1 MB for one door. It gets the one rejection message written for a specific audience.
- **It does not preserve GIF animation** — canvas flattens to frame one. Irrelevant: the
  upload is redrawn as a static sprite and the pipeline only ever uses the still.

**Output format:** JPEG in → JPEG out at q0.92; everything else → PNG. Always-PNG would turn
a phone photo into ~2 MB, working against the point; always-JPEG would land a transparent
PNG's alpha on black.

**Two states this adds.** `preparing…` in the caption — decode + resize is 100–300 ms on a
laptop and over a second on a phone, and without it a drop looks like a dropped frame. And an
**intake error**, held in local `useState` rather than the reducer: it is not a property of
the base animal, it is a note about a file we declined to send. A rejection leaves the current
base completely untouched — same picture, same commit button.

### 1.11 Every door owns its own controls *(Rev.7)*

The typed door had its field and its **Draw it** inside it. The upload door did not: choosing
a photo left the faithful↔sprite chips and a **Draw it · ~10 s** stranded at the *bottom of
the column*, below all three doors, describing a decision raised two cards higher up. Nothing
tied them to the door that produced them.

**Both doors that carry a decision now look alike, and the one that does not, does not.**
That is §3.2's own rule made visible:

| Door | Decision attached? | Shape |
|---|---|---|
| Use an existing base animal | no — picking *is* the answer | a plain button |
| Use my own picture | **yes** — how faithful? | a card: header, strength chips, **Draw it** |
| Or type any animal | **yes** — which animal? | a card: header, field, **Draw it** |

So the upload door has two shapes: a plain `<Door>` with no photo chosen, and a card once one
is. That is not a special case — it is the door acquiring a decision, which is exactly when
§3.2 says a door stops executing on selection and waits.

`UploadStrength` gains one prop, `action?: ReactNode`, rendered on the chips' own row: the
trade and the button that spends it belong on one line, the same shape the typed door has. It
is a **slot, not an `onDraw` callback** — the strength control must not learn what drawing is.

**`canRedraw` and `redrawLabel` are deleted, not moved.** They existed to decide which source
the ONE shared draw button was currently serving; with each door drawing its own, there is no
shared button left to arbitrate. Nothing in `Designer` renders a draw button now.

> **The door's hint must not morph.** A first pass replaced `~10 s · redrawn as a sprite`
> with `click to pick a different one` once a photo was pending — helpful-sounding, and it
> deleted the price at the exact moment the user is deciding whether to spend it (§3.3: the
> price is on the door *before* you commit). The hint is the door's description and stays
> constant; the header remains a button, and re-picking is the same click that got them there.

*Caught by `tsc` not catching it:* removing the bottom block left `canRedraw`, `redrawLabel`
and the `UploadStrength` import dead in `Designer.tsx`, and **nothing automated flagged them**
— `noUnusedLocals` is off and `npm run lint` has never run (§7). Dead-symbol sweeps after a
move are manual here.

### 1.12 The upload strength chooser is removed — it could not survive step 2 *(Rev.8)*

`SPEC_PET_DESIGNER_FLOW` §3.5 argues at length for faithful/balanced/sprite on the upload
door: *"the user chooses how far to redraw, because the trade is real and only they know
which side they want."* **The trade is real. The choice was not** — user-reported from the
running app, then traced:

```
step 1   photo ──img2img @ your strength (0.4 / 0.65 / 0.85)──▶ base reference
step 2   base ──img2img @ step 2's OWN strength──────────────▶ the pet that gets animated
```

Three facts compose into the failure:

1. **Step 2's redraw is mandatory.** `/api/preview` 400s unless a colour, accessory, axis or
   free-text change is present (§4.1, §4.2 *"No exceptions"*), and step 3 is gated on it.
   Every pet passes through it.
2. **Step 2 redraws at a strength step 1 never set** — `state.strength`, its own *"how far
   to push it"* control, defaulting to 0.85.
3. **`compose_design` can force it to 0.9** (`app.py:296`) whenever the design fights the
   source — a colour word against a differently-coloured species. The comment on that clamp
   says the quiet part: the redraw *"needs full strength (0.9) to win"*.

At 0.9 the second pass wins outright, so the photographic likeness a "faithful" base
preserved is destroyed before it is ever animated. §3.5's own table already conceded the
direction — *"faithful keeps your actual dog, costs the photographic pose/lighting Wan I2V
animates badly"* — and defaulted to sprite because **the animation is the product**. What it
did not account for is that the second redraw removes the choice regardless.

> **A control whose effect is erased downstream is worse than no control.** It charges the
> user a decision, implies the decision matters, and silently discards it. The honest UI for
> a value the user cannot really influence is no UI.

**What was done.** The chooser is gone from the upload door, which now shows only its Draw
button. The client sends **no `strength` at all** for uploads, so the server's own
`UPLOAD_REDRAW_STRENGTH = 0.85` (`app.py:155`, already the `Form()` default) is the single
owner — shipping a client copy of that number would be a second owner free to drift.
`UploadStrength.tsx` is **deleted**; `PendingSource` moved to `pendingSource.ts` and its
upload variant lost its `strength` field.

**Step 2's control is untouched and is the one that matters.** It governs the redraw that
actually produces the animated pet, it is where `min_strength` surfaces (§4.5), and nothing
here changes it.

> **`noUnusedLocals` did not catch this deletion's fallout** — `UploadStrength.tsx` became an
> unreferenced *module*, and the flag only sees unused locals and imports (§7). Found by
> grep. This is the exact limitation the `tsconfig.json` comment warns about, hit one commit
> after it was written.

*If per-upload faithfulness is ever wanted again, the fix is not to restore this chooser: it
is to let step 1's strength ride the reference record into step 2's redraw as a floor, so the
choice survives the second pass. That is a backend change, not a control.*

---

## 2. Why this is not Rev.1–4's second door

`SPEC_PET_DESIGNER_FLOW` §3.1 is the most-argued paragraph in the flow spec, and it says
the opposite of this document:

> Nothing else is on screen. No dropdowns, no second dropzone, no "Change" button beside a
> picture that is already clickable. Rev.1–4 accumulated all three, and **every one of them
> was a second door into the same room.**

**That rule is correct and this change keeps it.** What Rev.1–4 built, and what §13 records
as the repeating miss, was *duplication of an input*:

| Rev.1–4's second doors | Why each was redundant |
|---|---|
| A standalone "— or —" dropzone | The box already accepted drops |
| A "Change" button beside the picture | The picture was already clickable |
| Cascading species → breed dropdowns | The gallery already showed the bases |

Each added a **second control performing an action the first control already performed**.

The rail adds none. It performs an action nothing on the page performs today: **naming the
three sources.** Before this change the count of on-screen controls that state "you can
type any animal" is zero; after it, one, and it is the field itself. That is not a second
door — it is the first signpost.

The test §13 offers is the one to apply, and it passes cleanly:

> *specifying an interface instead of describing the artifact and letting the interface
> follow.* The bases are pictures; the box is the subject; the dialog is one question.

The artifact here is **the question itself** — §3.1 wrote it out as a blockquote because it
is the material step 1 is made of. Rev.5 put that question in a modal, where it is material
the user cannot see. The rail describes it. The dialog stops being "one question" and
becomes what it always physically was: an answer surface.

**And it removes doors on net.** The `choices` view and the `typed` view are both deleted;
`Use my own picture` no longer routes through an app dialog to reach the OS one. Surfaces
that ask "which source?": today **two** (the box's click, and the choice list it opens);
after, **one**.

### 2.1 The one overlap this spec accepts, stated rather than glossed

Two controls now reach the gallery: the rail's first button, and the box's click. By the
strict reading of §2's own criterion that is a second control performing an existing
action, and this spec **accepts it deliberately**.

The reason it is not Rev.1–4's "Change" button: that button's entire information content
was *"this is clickable"*, which the picture already said. The rail button's job is to be
**the third member of a complete set**. Delete it and the rail reads *"Use my own picture /
Or type any animal"*, from which a reasonable user concludes the curated bases are not a
thing — the door would be reachable but unnamed, which is §0's bug moved one seat over.
Completeness of the set is a real function, and no other control performs it.

The cost is paid down where it can be: §1.4 removes the *copy* duplication, so the two
entrances no longer say the same sentence in two places. The click survives as an
affordance, not a documented door.

---

## 3. What it costs, stated honestly

`Step.tsx:13` records the measured budget, and §1.1's headline metric is *controls at first
paint: 29 → 2*.

| | Today | After | Δ |
|---|---|---|---|
| **First paint** (step 1 open, pre-filled curated base, step 2 unmounted) | **2** — the box, **Use this animal →** | **6** — + 2 rail buttons, the typed field, its Draw button | **+4** |
| **Peak** (step 2 expanded) | **25** | **25** | **0** |
| Clicks to reach the gallery | 2 | **1** | −1 |
| Clicks to reach the file dialog | 2 | **1** | −1 |
| Clicks to reach the typed field | 2 | **0** | −2 |

**Peak is unchanged** because locking step 1 collapses it and `<Step>` unmounts its
children (`Step.tsx:109-111`) — the rail exists only while step 1 is open, which is the
only time its question is live.

So the headline becomes **29 → 6**. This spec asserts that is the right trade, and states
the reasoning rather than hiding the number:

- The metric was never "fewest controls"; §1.1 says so directly and §12 records Rev.2's
  29 → 3 claim as arithmetically hollow — *"controls at first paint was never 29
  decisions."* The rail adds **four controls and zero decisions**: the user already had to
  decide where their animal comes from, and was doing it blind.
- Four of the six controls at first paint are now *the flow's own opening question*. A
  page whose two visible controls are a picture and a commit button is small the way a
  locked door is quiet.
- Every path gets shorter, and the typed path — the product's headline — gets shorter by
  two, so the ~7-action budget §1.1 tracks **improves** most on the path that matters most.

---

## 4. What does not change (the contract)

This is a presentation change. Everything below is untouched, and "untouched" is
verifiable, not aspirational:

- **`designFlow.ts` — the reducer, its actions, and its invalidation rules.** `pending`,
  `pendingDrawn` and `dialogOpen` are local `useState` in `<Designer>`
  (`Designer.tsx:59-65`), not reducer state, so the rail wires to functions that already
  exist. **`designFlow.test.ts` must pass with zero edits** — that is the proof this spec
  is presentation-only, and a diff to it means the change went wrong (§7).
- **`reference_id` as the spine** (§6.1). No new field, no new endpoint, no `/api/*` change.
- **Selecting executes** (§3.2). The rail's buttons *open doors* and the field *draws on
  submit*; the existing `chooseAndDraw` (`Designer.tsx:154`) still fires on the pick, and
  the upload still lands as an undrawn preview.
- **Draw / Use this animal →** (§3.6), including the disabled rules on the commit button
  (`Designer.tsx:290-291`). `canRedraw` narrows — see §5.3 — but the rule it encodes
  ("the draw button only exists where drawing can change something") is unchanged. The
  commit's rule is unchanged **in code**, while the state space around it grew by one: an
  inline field can hold an undrawn draft. That the rule still holds over the larger space is
  argued, not assumed — §9.15.
- **The lock and its two halves** (§3.7) — body button, header toggle, unmount on collapse.
- **`<ModalOverlay>`** (§3.8). The dialog keeps composing it; nothing here hand-rolls an
  overlay.
- **The pre-fill** (§3.1) — the box still lands filled with the first curated base, and the
  rail still shows *Use an existing base animal* as current.
- **The house-pet non-door** (§3.9). Three doors, still. The rail is not an invitation to
  add a fourth — anything new arrives as a deep link, per §3.9.

---

## 5. Implementation

### 5.1 New — `web/src/app/design/general/SourceRail.tsx`

One presentational component: no state, no data fetching, no knowledge of the dialog. Its
`Door` button is the one moved out of `BaseAnimalDialog.tsx:173-185` (renamed from
`Choice`, plus the current-marker edge) — **moved, not copied**; the original is deleted in
the same change.

Its header comment cites this spec (`SPEC_STEP1_SOURCE_RAIL §1.1`) and carries the §2
argument in two lines, so the next person to read it knows it is not a §3.1 relapse.

```tsx
interface Props {
  /** Which source the box's contents came from — marks the rail (§1.5). */
  current: PendingSource["kind"] | null;
  /** A draw is in flight: the typed row's button is disabled and says so. */
  busy: boolean;
  /**
   * The typed draft. Lives in <Designer>, NOT here — <Step> unmounts its children on
   * collapse (Step.tsx:111), so a draft held here would be destroyed every time step 1
   * locked. That is the §13 miss ("reopened claiming Cat/Tabby over a corgi") exactly,
   * and Designer.tsx:55-58 already documents the rule for `pending`.
   */
  typedDraft: string;
  onTypedDraft: (text: string) => void;
  /** The draft is exactly what is currently drawn in the box → "Draw it again". */
  typedIsDrawn: boolean;
  onGallery: () => void;
  onUpload: () => void;
  /** Draw the typed animal — the typed door's "select, and it executes" (§3.2). */
  onTypedDraw: (animal: string) => void;
}
```

Body, in order (**no heading and no sub-line** — §1.8 deleted both; the component opens
straight onto the doors):

1. *(nothing)*
2. **Two `<Door>`s** — 🐾 `Use an existing base animal` / `free · instant` → `onGallery`;
   📷 `Use my own picture` / `~10 s · redrawn as a sprite` → `onUpload`. Labels and hints
   are the dialog's existing strings, unchanged (`BaseAnimalDialog.tsx:79-87`).
3. **The typed row**, in a container carrying the same shell as a `<Door>` (§1.6):
   - The same glyph + label + hint header as a `<Door>` — ✏️, **`Or type any animal`**
     (§9, decision #10), `~10 s · drawn from scratch`. Wearing the doors' own shape is what
     makes the three read as one set rather than two buttons and a form.
   - `<label htmlFor="typed-animal">` wraps the label text — associated by `id`, not by
     placeholder: `blue jay` is an example, and an example is not a label.
   - `<input id="typed-animal" className="input min-w-0 flex-1" placeholder="blue jay">`,
     value/onChange bound to `typedDraft`/`onTypedDraft`. **No `autoFocus`** — the dialog's
     copy has it (`:137`) and inline it would steal focus at page load and scroll the step
     into view.
   - `onKeyDown`: `Enter` + non-empty trimmed draft + `!busy` → `preventDefault()` and
     `onTypedDraw(typedDraft.trim())`. Mirrors `:140-146`.
   - A `className="btn shrink-0"` submit beside it: disabled on `!typedDraft.trim() || busy`,
     label `busy ? "Drawing…" : typedIsDrawn ? "Draw again" : "Draw it"`. Short, because it
     sits inside a capped row beside the field — the `~10 s` price is in the hint above it,
     stated once.

`Door` takes `{ glyph, tone, label, hint, current, onClick }` and renders `<Glyph>` + a
stacked label/hint. Both it and the typed row take their surface from one `shell(tone,
current)` helper, so the current-marker is defined once: `borderLeft: 3px solid` in the
door's own colour when current and `transparent` otherwise (never a width change — that
would shift the layout), plus that colour mixed into the border. `aria-current="true"` on
the two buttons only.

### 5.2 `BaseAnimalDialog.tsx` → `BaseGalleryDialog.tsx` — collapses to one view

`git mv`, then:

- Delete `type View` (`:28`), the `view` state (`:43`), and the `setView("choices")` reset
  in `close()` (`:47`). `close()` becomes `onClose` at the call sites; the local wrapper
  goes away.
- Delete the `typed` state (`:44`) and the whole `typed` branch (`:128-168`).
- Delete the `choices` branch (`:76-94`) and the `Choice` component (`:173-185`, moved).
- Delete the `onPickTyped` and `onPickFile` props (`:35-37`) — the rail owns both doors now,
  and the dialog no longer has a route to the OS picker or to a text field.
- The title and sub-line stop being ternaries (`:62-74`): `Pick an existing base animal` /
  `These are hand-picked, and free to use.`
- `Back` (`:187-193`) keeps its `← other options` label and calls `onClose`.
- Remaining props: `open`, `options`, `onClose`, `onPickCurated`.
- Rewrite the header comment — it currently enumerates three doors (`:3-23`). It becomes:
  this is the gallery; the source question is asked by `<SourceRail>`; the overlay shell is
  still `<ModalOverlay>` and must never be hand-rolled.

### 5.3 `Designer.tsx` — wiring

- **`dialogOpen` stays `useState(false)`** (`:59`). A one-view dialog needs no view state;
  see §10E for the `dialogView`/`initialView` design that was rejected.
- Add `const [typedDraft, setTypedDraft] = useState("")` beside `pending`, sharing the
  lifted-state comment at `:55-58` (extend it to name both).
- Add, near `canRedraw`:
  ```ts
  const typedIsDrawn = pending?.kind === "typed" && pendingDrawn
                       && pending.animal === typedDraft.trim();
  ```
- **Narrow `canRedraw` (`:165`)** from `Boolean(pending) && pending?.kind !== "catalog"` to
  `pending?.kind === "upload"`. Typed now redraws from its own row, so leaving the bottom
  button live for typed would put two identical "Draw it again" buttons on screen at once —
  the second door §2 forbids. Update the comment above it (`:159-164`): it explains why
  curated has no draw button; it now also explains why typed's lives in the rail, beside
  the field that feeds it. The upload's stays here, beside `<UploadStrength>`, for the same
  reason. **Every draw button sits beside the control that feeds it, and no source ever has
  two.** Note what that does *not* claim: with a photo pending *and* text in the field, both
  rows show an enabled Draw. That is correct — they draw different things from different
  inputs, and each sits beside its own. The rule forbids two buttons for **one** source,
  which is what sharing the bottom button with typed would have produced.
- The error line (`:298-300`) stays a child of the column and simply left-aligns. It reports
  at the bottom, away from the typed field that may have caused it; acceptable because
  `referenceError` is rare and the box's caption carries the live state. Do not duplicate it
  into the rail.
- Add, beside `typedIsDrawn`:
  ```ts
  const baseIsDrawn = Boolean(state.reference) && !state.referenceBusy
                      && !(pending && !pendingDrawn);
  ```
  — the old commit-disabled predicate, inverted, now deciding existence (§1.7).
- `<Step index={1} … layout="split">`.
- The children wrapper (`:251`) loses `mx-auto max-w-md items-center` and becomes
  `<div className="flex flex-col gap-5">` — left-aligned, matching step 2 (`:409`).
- **The `artifact` prop becomes a column**: `<ReferenceBox>` with the commit button under
  it, gated `showsControls(state, axes, 1) && baseIsDrawn` (§1.7). The commit button and
  its wrapping button-row are **deleted from the children**.
- **The upload block absorbs its draw button.** `<UploadStrength>` and the bottom **Draw**
  become one `max-w-[26rem]` column rendered only for `pending?.kind === "upload"` — the
  two controls are a pair (set the strength, press draw, look, repeat) and the draw button
  had no other reason to exist once typed and the commit both left.
- `<SourceRail>` is the first child:
  ```tsx
  <SourceRail
    current={pending?.kind ?? null}
    busy={state.referenceBusy}
    typedDraft={typedDraft}
    onTypedDraft={setTypedDraft}
    typedIsDrawn={typedIsDrawn}
    onGallery={() => setDialogOpen(true)}
    onUpload={() => fileRef.current?.click()}
    onTypedDraw={(animal) => chooseAndDraw({ kind: "typed", animal })}
  />
  ```
- `<BaseGalleryDialog open={dialogOpen} options={options ?? []} onClose={…}
  onPickCurated={…} />` — the two deleted props come off the call site (`:325-328`).
- **Rewrite the file-input comment (`:304-307`).** Its stated reason — *"the dialog unmounts
  the moment 'Use my own picture' is clicked"* — expires with the `choices` view. The input
  still belongs at `<Designer>` level, and the new reason is that it serves the rail, which
  `<Step>` unmounts when step 1 locks. A comment whose premise has been deleted is worse
  than no comment.
- **Update the STEP 1 block comment (`:211-214`)**: it already says *"a WORKSHOP, not a
  menu: the controls sit on the left and the animal they produce sits on the right"* —
  which describes the layout this spec builds and **not** the centred one shipped today. It
  becomes true rather than aspirational; the comment should say so and cite this spec.

### 5.3b New — `design/general/prepareUpload.ts` (§1.10)

Exports `ACCEPTED_IMAGE_MIMES` (mirrors `app.py:147`), `ACCEPT_ATTR` for the file input,
`MAX_PX = 1024` (mirrors `app.py:302`), `MAX_BYTES` (mirrors `app.py:146`), `UploadRejected`,
and `async prepareUpload(file): Promise<File>`.

Order of operations: reject by MIME (with a HEIC-specific message; an **empty** type is not a
rejection — some drag sources supply none, so the decoder decides) → `createImageBitmap` →
return the original untouched if the longest side ≤ `MAX_PX` → canvas downscale with
`imageSmoothingQuality: "high"` → `toBlob` → **return the original if the re-encode is not
smaller and the original fits** → new `File` with the extension corrected.

`Designer.tsx`: `acceptPhoto` becomes `async`, adds `preparing` and `intakeError` local
state, and the file input takes `accept={ACCEPT_ATTR}` and clears `e.target.value` after
each pick (or re-picking the same rejected file fires no change event and the page sits
silent).

**No unit test, same posture as `SourceRail` (§7)**: `prepareUpload` is browser-API-bound —
`createImageBitmap`, canvas, `toBlob` — and `vitest.config.ts` has no jsdom by design. Even
with one, jsdom's canvas is a stub, so a passing test would prove nothing about resizing.
The Playwright harness driving real drops through the real UI is the coverage, and it is what
caught the re-encode-loses case (#26).

### 5.4 `ReferenceBox.tsx` — copy, the caption, the hover overlay, and one deletion

- **The `<figcaption>` renders only when `busy || locked || isPending`** (§1.9), one line, and
  the animal-name line is deleted outright.
- **A hover overlay inside the box**: `hover` state on the box's `onMouseEnter`/`onMouseLeave`,
  rendered when `(hover || dragover) && !locked && !busy`, absolutely positioned
  `inset-x-0 bottom-0`, **`pointer-events-none`**, with the box itself gaining `relative` and
  `overflow-hidden`.
- The header comment's *"dropping auto-commits"* paragraph is **false** and must be replaced:
  a dropped photo lands undrawn and waits for **Draw**, which is what §3.2 specifies and what
  the code has always done. Verified by driving a real drop.

- `aria-label` (`:80`) and the caption (`:135`) per §1.4.
- **Delete the dead file input.** `inputRef` is declared (`:51`) and attached (`:102`) but
  nothing ever calls `.click()` on it — the hidden `<input>` at `:101-107` is unreachable
  from any interaction, a leftover from before the OS picker moved to `<Designer>`. This
  change puts the only live file input in the rail's path, which makes the dead one
  actively misleading. Remove `:51` and `:101-107`, and the now-unused `useRef` import.
- No other behaviour change: drop, paste, and keyboard activation all stay.

### 5.5 `Step.tsx` — the heading, and one prop-doc sentence

- The header renders **`Step {index} — {title}`** as one `<h2>`; the separate faint mono
  index span is deleted (§1.8). All three cards, no per-step branching.
- `layout="split"` already exists and already does exactly this (`:51-55, 93-105`). Its prop
  doc, however, states *"Step 1 stays centred — it has three controls, so there is no
  distance to close."* **That sentence must be updated**, and the same sentence in
  `SPEC_PET_DESIGNER_FLOW` §4.8 with it (§11).

### 5.6 `globals.css` — one new class

**`.btn-step`** (§1.8): `background`/`border` `var(--accent)`, white, semibold, 0.55/1.1rem
padding, `filter: brightness(1.12)` on hover, `opacity: 0.4` disabled. It joins `.input` /
`.btn` / `.btn-ghost` as the designer's fourth shared control style — worth a class rather
than three inline styles by the same "three call sites" test those three passed.

Applied at exactly three sites in `Designer.tsx`: `Use this animal →`, `Use this as my
pet →`, `Bring it to life · ~3 min`. **The comment above the class states the rule** — never
on a control that can be pressed twice — because `globals.css` is where the next person
reaching for it will be standing, not this document.

---

## 6. Accessibility and small screens

- The rail is two real `<button>`s plus a labelled `<input>` + `<button>`. DOM order in a
  split step is children-then-artifact (`Step.tsx:96-103`), so tab order reads
  **two doors → typed field → typed draw → (strength → upload draw) → box → commit**:
  every way of filling the box, then the box, then the one act that ends the step. The
  commit moving into the artifact (§1.7) is what puts it last, which is where it belongs.
- The field is associated by `htmlFor`/`id`, not a placeholder — `blue jay` is an example,
  and an example is not a label.
- Glyphs are decorative and marked `aria-hidden`: 🐾/📷/✏️ repeat what the label says, and
  an unlabelled emoji announced before every door is noise. The colour carries no meaning a
  screen reader needs — `aria-current` carries the only state (§1.5).
- `aria-current="true"` marks the current source on the two buttons (§1.5). Not
  `aria-pressed` — these are not toggles. Not `role="radio"` — see decision #6.
- The box keeps `role="button"`, `tabIndex={0}` and Enter/Space (`ReferenceBox.tsx:78-92`),
  and its `aria-label` now names the gallery it opens.
- **Narrow screens:** `Step`'s split is `flex-wrap` with `min-w-[280px]` on the controls
  column, so below ~600 px the artifact wraps **below** the rail. That is the same
  behaviour step 2 has today, and it is the right stacking order here — the question above
  the answer. The typed row wraps internally (`flex-wrap` on the field + button pair) so
  the button drops under the field rather than squeezing it.

---

## 7. Tests and verification

| Gate | What it proves |
|---|---|
| `cd web && npx tsc --noEmit` | Deleting `View`/`onPickTyped`/`onPickFile`, the rename, the new `SourceRail` props and the narrowed `canRedraw` are all type-visible; the compiler finds every caller. **Never `next build` while the dev server is live** (`CLAUDE.md`) |
| `npm test` (`vitest run`) | `designFlow.test.ts` passes **with zero edits**. A required edit means reducer state was touched and this stopped being a presentation change (§4) |
| ~~`npm run lint`~~ | **Not a gate — it has never run.** `next lint` prompts interactively to configure ESLint and no config has ever existed in this repo (`git log` finds none for `.eslintrc*`/`eslint.config.js`). It is in `package.json` and does nothing. Do not cite it as coverage |

`tsconfig.json` sets `strict` but **not** `noUnusedLocals`, so nothing automated catches a
half-done deletion like §5.4's `useRef` — that one is on review. Standing up ESLint is worth
doing and is deliberately **not** bundled here: it is a repo-wide change with its own diff,
and smuggling it into a step-1 layout change is how unrelated failures get attributed to the
wrong commit.

**No component test for `SourceRail`, deliberately.** `vitest.config.ts` states the rule:
there is no jsdom and no React testing here, and *"if a test ever needs a browser, that is
a signal the logic under it belongs in the reducer instead."* `SourceRail` is presentational
— its only logic is a `.trim()` — so there is nothing to move into the reducer and nothing
to assert without a DOM. Adding jsdom for it would contradict the config's stated posture
for a component with no decisions in it. The manual list below is the coverage.

Manual E2E — `./start_all.sh`, `PET_GEN_BACKEND=local`, `:19955`, appended to §10.3's list:

1. First paint: the rail is visible; **the typed field is on screen with its label and
   `blue jay` placeholder, without clicking anything.** This is the acceptance criterion
   for §0. Focus is *not* in the field and the page has not scrolled. The three doors read
   as buttons — glyph chips in three colours, capped well short of the column (§1.6) — and
   **Use this animal →** is under the picture, **filled indigo**, not in the left column
   (§1.7, §1.8).
1b. The card reads **`Step 1 — Select the Animal to Design`**, with **no heading or sub-line
   above the doors**; steps 2 and 3 read `Step 2 — …` / `Step 3 — …` (§1.8).
1c. Lock through to step 3: **`Use this as my pet →` and `Bring it to life · ~3 min` are the
   same filled treatment**, and every loop button on the page (*Draw it*, *Preview my pet*,
   *Try again*) is still outlined. Three filled buttons exist in the whole flow, never two
   at once.
2. **Use an existing base animal** → the gallery opens directly, no menu in between.
3. Click the **image** → the same gallery, same one click.
4. **Use my own picture** → the OS file dialog opens with no app dialog in between; the
   photo lands undrawn; the strength slider and its **Draw it** appear together in the left
   column; **Use this animal → disappears** while the photo sits undrawn, and returns when
   the draw lands (§1.7).
5. Type `blue jay` → press **Enter** → it draws. Press the row's **Draw it again** →
   a different blue jay (new seed). Both paths work; **there is no second Draw button
   on screen while a typed source is current.**
6. Type a new animal over a drawn one → the row's button reverts to **Draw it · ~10 s**
   (not "again"), because the draft no longer matches what is in the box.
7. **The undrawn draft (§9.15).** Type `blue jay` and do *not* draw. **Use this animal →**
   stays **present and clickable** — a draft never touches `pending`, so `baseIsDrawn` is
   still true — the current-edge stays on *Use an existing base animal*, the box still
   shows the tabby, and committing yields the tabby. Then press the row's **Draw it** →
   the blue jay lands and the edge moves to the typed row.
7b. **The commit tracks the picture (§1.7).** During any draw, the button is **gone** and
   the box reads `drawing…`; it reappears with the finished animal. It is never on screen
   greyed out.
8. `← other options` closes the dialog and the rail is there behind it.
9. The rail marks the current source after each of the three doors, and the mark does not
   shift the layout when it moves.
10. Drop a photo on the box while step 1 is **locked** → it unlocks, the rail reappears, the
    photo is pending and drawable (the `Designer.tsx:111-123` rule, re-verified under the
    new layout).
11. With a photo pending **and** text in the field, **both** Draw buttons are enabled and
    each draws its own source (§5.3) — this is the intended state, not a bug.
11b. **Upload intake (§1.10)**, via all three paths — picker, drop, paste:
    a multi-megapixel JPEG lands in well under a second and is sent at a fraction of its
    original size; a `.heic`, a `.bmp` and a `.txt` are each refused with their own message
    **and leave the current base untouched** — same picture, commit button still there; a
    photo already under 1024 px is sent byte-identical; `preparing your photo…` shows in the
    caption while a large file is being decoded.
12. Lock → step 1 collapses to summary + box, **rail gone and the commit button gone with
    it** (it lives in the always-rendered `artifact`, so this is the §1.7 gate doing its
    job); header reads *🔒 Locked — click to change*; clicking it reopens with the rail, the
    previous source still current, **and the typed draft still in the field** (the §5.1
    lifted-state rule).
13. Narrow the window to phone width → rail above, box below, the typed button under the
    field, nothing clipped.

---

## 8. Build order

1. `SourceRail.tsx` — new file, moved `Door`, no wiring. Compiles unused.
2. `git mv BaseAnimalDialog.tsx BaseGalleryDialog.tsx`; collapse to one view, delete the
   two props and the two branches, rewrite the header comment. **Type errors here are the
   checklist** for step 3.
3. `Designer.tsx` — `typedDraft` state, `typedIsDrawn`, `layout="split"`, mount the rail,
   narrow `canRedraw`, rewire the dialog, fix the two stale comments.
4. `ReferenceBox.tsx` — the two strings, and the dead input.
5. `Step.tsx` prop-doc sentence.
6. Gates (§7), then the manual list.
7. **Amend `SPEC_PET_DESIGNER_FLOW` (§11 below) in the same commit.** Cleanup is a phase of
   the work, not a follow-up (`CLAUDE.md`), and a flow spec that still says *"nothing else
   is on screen"* while the screen has a rail on it is the §11.3 trap repeating.

---

## 9. Decisions

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Does the rail duplicate the dialog's choice list? | **No — it replaces it.** The `choices` view is deleted | Two surfaces asking one question is §3.1's second door. One question, one place (§2) |
| 2 | Does clicking the image reopen a menu? | **No — it opens the gallery** | The menu is on screen already. Click a picture, get pictures (§1.4) |
| 3 | Does the **gallery** inline into the left column? | **No** | The catalog grows one folder per animal (§3.3, *"keeps fifty legible later"*). Fifty thumbnails in a 280 px column is worse than an overlay, and it would push the commit button off screen (§3) |
| 4 | Does the **typed field** inline? | **Yes** | Its whole answer surface is one text input, which fits trivially where the gallery does not (§1.2). It is also the door §0 is about, and inlining takes it from two interactions to zero. The archetype risk is *reduced*: the guardrail copy that mitigates it becomes permanently visible instead of living in an unopened modal |
| 5 | Does the typed row reuse the bottom **Draw** button? | **No — its own, and `canRedraw` narrows to uploads** | Sharing it would put two live "Draw it again" buttons on screen for a typed source. One draw button at a time, beside the control that feeds it (§5.3) |
| 6 | Does the rail show which source is current? | **Yes — faint accent edge + `aria-current` on the buttons, never a selected/radio look** | It explains the page's state. Risk: a filled or checked style would imply clicking *selects*, when it opens a door — hence not `aria-pressed`, and not `role="radio"`, which would additionally promise arrow-key navigation between three slots of which one is a text field. Styling is deliberately weak for that reason (§1.5) |
| 7 | Does first paint stay at 2 controls? | **No — 6, and the spec says so out loud** | The metric was never "fewest controls" (§1.1, §12). Four of the six are the question the flow exists to ask (§3) |
| 8 | Does any of this reach the reducer, the API, or `reference_id`? | **No** | `designFlow.test.ts` unedited is the proof (§4, §7) |
| 9 | Is `← other options` kept? | **Yes, retargeted to close** | The overlay covers the rail; Escape and backdrop-click are undiscoverable; changing your mind mid-dialog should cost one obvious click |
| 10 | Does the typed door's copy change? | **Label becomes `Or type any animal`; placeholder and sub-line unchanged** | §3.2 flags this as the flow's highest-risk copy, and the risk is precisely that it invites a *description*. `Or type any animal` says **animal**, and it is not an invention — it is the repo's own prior wording, quoted in `ReferenceBox.tsx:13` (*"the left-hand 'or type any animal' field"*). It is arguably safer than `Type the animal I want`, whose "want" leans toward desire. The two **button** labels are unchanged verbatim |
| 11 | Does the field autofocus? | **No** | Inline, `autoFocus` (the dialog's `:137`) steals focus at page load and scrolls the step into view. In a modal it was correct; on a page it is not |
| 12 | Where does the typed draft live? | **`<Designer>`, beside `pending`** | `<Step>` unmounts children on collapse (`Step.tsx:111`), so a draft in the rail dies on every lock — the §13 miss verbatim. `Designer.tsx:55-58` already states this rule for `pending` |
| 13 | Is the dialog renamed? | **Yes — `BaseGalleryDialog.tsx`** | It holds one view and one job. Its header comment must be rewritten either way, so the rename is nearly free, and a name that claims two deleted doors misleads (`CLAUDE.md`: specific names that communicate intent) |
| 14 | Does the rail open the door to a fourth source? | **No** | §3.9 stands: a revived house-pet source arrives pre-resolved via `?base=`, never as a choice |
| 15 | An inline field creates a state the modal made impossible — **text typed but never drawn, beside a commit button that ignores it.** Does the commit block on it? | **No. The box is the truth; a draft is not a choice** | See §9.15 below — this one needs more than a table cell |
| 16 | Do the doors keep the dialog's full-width row shape? | **No — glyph, colour, stacked label/hint, capped at `26rem`** | A full-width row was right in a modal that held nothing else; on the page beside a 200 px picture it reads as a table of text. Visible-but-not-operable is §0's bug in a new register (§1.6). Colour is per-door *identity*; the current-edge stays the only *state* channel, so the set never reads as a radio group |
| 17 | Where does **Use this animal →** live, and is it disabled or absent before a draw? | **Under the box, and ABSENT** | It commits what the box shows, so it belongs to the box, not to the bottom of a list of source controls. And its old disabled predicate *was* "there is no finished animal on screen" — which the box already says in words directly above it. A greyed button asks the user to work out why; no button does not (§1.7). Cost: it lives in the `artifact` slot, which renders in every state, so it gates on `showsControls` explicitly or it survives the collapse |
| 18 | Does the card heading name its step? | **Yes — `Step N — <title>`, in `<Step>`, for all three** | The faint numeral read as a list marker while the page header promised three named steps. Putting it in the shell rather than in step 1's call site keeps the engine from branching on which step it is rendering (§1.8) |
| 19 | Does the rail keep its heading and sub-line? | **No — both deleted** | `Where should it come from?` sits above three doors that answer it in their own labels. The sub-line was §3.2's guardrail and its deletion is a real cost, paid twice over: the page header already says *"start from what a typical animal looks like"*, and the typed door — the only one a design can be typed into — carries `Or type any animal` / `drawn from scratch` / `blue jay` on the control itself (§1.8). If typed designs appear, fix the typed row, not the rail |
| 20 | Do the step-advancing buttons look different from the loop buttons? | **Yes — `.btn-step`, filled, exactly three** | Three locks surrounded by press-as-often-as-you-like loop buttons all rendered as `.btn` made three decisions look like six options. Filled = "this moves you forward". **Never put it on a control that can be pressed twice**, or the signal is worth nothing (§1.8) |
| 21 | Does the box keep a permanent caption? | **No — it speaks only when it has news** | The name repeats the picture (and the collapsed step already shows it via `<Step summary>`); `drop a photo here` spent a permanent line on a rarely-used capability. `drawing…`, `not drawn yet — press draw` and `🔒 locked in` stay, because each explains something the picture cannot — the middle one is the other half of §1.7 (§1.9) |
| 22 | Is the drop hint a `title=` tooltip? | **No — a hover overlay inside the box** | `CLAUDE.md` forbids native `title` and mandates a shared tooltip component; none exists, and building one for a single call site is out of scope. The overlay also avoids the layout shift a hover-revealed caption line would cause, and is `pointer-events-none` so it cannot fire `dragleave` under a dragged file (§1.9) |
| 23 | How is the commit button aligned with the rail's last button? | **Caption removal (24 px) + `-mt-3` on the artifact (12 px), measured to 6 px** | Cancelling the split row's own `mt-3` sits the picture flush with the header baseline. Scoped to `step1Open` — collapsed, that margin is what keeps the box off the *🔒 Locked* button (§1.9) |
| 24 | Is an oversized photo rejected or downscaled? | **Downscaled, client-side, before it is sent** | The server's 413 fires on a budget nothing downstream cares about — `_encode_reference_image` thumbnails every accepted image to the same 1024 px four lines later. Doing it first turns a full upload plus a round-trip into ~200 ms of local work (§1.10) |
| 25 | Does the server's 12 MB cap change? | **No** | It is the security boundary; a direct API call never runs this code. The UI simply stops producing files that trip it. Relaxing a server limit because the client got polite is the wrong lesson (§1.10) |
| 26 | Is the downscaled file always the one sent? | **No — only when it is actually smaller** | Measured: a 548 KB 3000 px PNG re-encoded to **2.9 MB** at 1024 px, because resampling raises entropy. Fewer pixels ≠ fewer bytes. When the re-encode loses and the original fits, the original is sent (§1.10) |
| 28 | Where does the upload's **Draw it** live? | **Inside the upload door, beside its strength chips** | It was stranded at the foot of the column, below all three doors, describing a decision raised two cards higher. Every door now owns its own controls, and the two doors with a decision attached (§3.2) look alike (§1.11) |
| 29 | Does the upload door change shape when a photo is pending? | **Yes — plain button → card** | Not a special case: it is the door *acquiring* a decision, which is precisely when §3.2 says a door stops executing on selection and waits for one |
| 30 | ~~Does `UploadStrength` learn how to draw?~~ | **Moot — the component is deleted (#31)** | It took an `action` slot for one commit, then the control it wrapped was removed entirely (§1.12) |
| 31 | Does the upload door keep faithful/balanced/sprite? | **No — removed; the server's `UPLOAD_REDRAW_STRENGTH` governs** | Step 2's redraw is mandatory, runs at its own strength, and is forced to 0.9 whenever the design fights the source — so a "faithful" base was overwritten before it was animated. A control whose effect is erased downstream charges a decision and discards it. Step 2's own strength control is untouched and is the one that shapes the pet (§1.12) |
| 32 | Does the client send `strength` for uploads? | **No — nothing at all** | The client has no opinion now, and the server's `Form(UPLOAD_REDRAW_STRENGTH)` default already holds the value. A client copy would be a second owner of one number, free to drift (§1.12) |
| 27 | Where does the intake error live? | **Local `useState`, not the reducer** | It is not a property of the base animal — it is a note about a file we declined to send. A rejection leaves the current base, its picture and its commit button completely untouched (§1.10) |

### 9.15 The undrawn draft, and why the commit ignores it

Inlining the field buys §0's answer and costs one new state. In the modal there was no such
thing as an abandoned draft — Confirm drew it, Cancel destroyed it, and the field did not
exist in between. On the page it persists, so this is now reachable:

> Type `blue jay`. Do not press Draw. Press **Use this animal →**. You get the tabby.

`onTypedDraft` sets `typedDraft` and nothing else — it never touches `pending` — so the
commit button's disabled rule (`Designer.tsx:290-291`) does not see the draft, and must not.

**The commit stays enabled, and that is the correct answer, not a concession:**

- **The rule it appears to strain is in fact satisfied.** `Designer.tsx:285-289` requires
  that the button *"must never lock something other than what the user is looking at"* — and
  what the user is looking at **is** the tabby. The box shows it, the caption names it, the
  rail's current-edge (§1.5) sits on *Use an existing base animal*. Every artifact on screen
  agrees. Text in an input the user never actioned is an intention, not a choice, and step 1
  commits choices.
- **Blocking would be worse.** Disabling commit on non-empty text lets a stray keystroke
  hold the whole flow hostage with no visible cause — the button would grey out and the page
  would not say why. Auto-drawing on commit is worse still: it spends ~10 s of GPU the user
  never asked for and violates §3.2, where drawing is always an explicit act.
- **It is self-correcting and cheap.** The draft survives (decision #12), the row's own
  **Draw it** is right beside it, and unlocking returns to a rail with the text still there.
  The recovery is one click on a button already adjacent to the mistake.

What the design owes in exchange is that the two are never confusable, and §1.5 already pays
it: the current-marker sits on the source that filled the box, never on the typed row, until
a typed source is actually drawn. **The page always says which of the two is real.**

*If field evidence later shows users committing over a live draft, the fix is a hint on the
typed row — "press Draw to use this" once the draft is non-empty and unmatched — not a
disabled commit button. Record it here before building it.*

---

## 10. Rejected alternatives

**A. Caption-only fix.** Rewrite the box caption to name the doors —
`click to choose — existing · your photo · any animal`. Zero new controls, §3.1 untouched,
and it recovers some of the discoverability. **Rejected** because it fixes the symptom at
the weakest typographic level the page has (11 px faint mono) and leaves every path two
clicks long. It remains the correct fallback if §3's control budget is later judged
inviolable — it is cheap, and it is not incompatible with anything here.

**B. Fully inline — no dialog at all.** The rail selects a source and *every* answer
surface renders in the left column, gallery included. **Rejected in half.** This spec
adopts B's typed field and rejects B's gallery, per decisions #3 and #4 — the two doors
differ by an order of magnitude in the surface their answer needs (§1.2), and bundling
them was the error in Rev.1 of this document. The gallery does not fit a growing catalog
in 280 px; a text input does.

**C. Rail replaces the box's click entirely** (the picture becomes inert, drop-only).
**Rejected**: a 200 px picture with a pointer cursor that does nothing is a worse lie than
one that does something unexpected, and the gallery is the one door the picture genuinely
implies. §2.1 handles the resulting overlap instead.

**D. Radio-group rail** — clicking selects a source, a separate control opens it.
**Rejected**: it re-introduces the select-then-confirm ceremony §3.2 removed. Selecting
executes; the rail's slots *are* the doors.

**E. A two-view dialog behind an `initialView` prop** — Rev.1 of this document kept the
typed view in the dialog, replaced `dialogOpen` with `dialogView: View | null`, and had
`<BaseAnimalDialog>` do `useState<View>(initialView)`. **Rejected, and it was broken:**
`<BaseAnimalDialog>` is mounted unconditionally (`Designer.tsx:315`) and only
`<ModalOverlay>` returns `null` when closed (`ModalOverlay.tsx:69`), so the dialog's own
state survives every close — which is exactly why today's `close()` has to reset it
explicitly (`:47`). `useState(initialView)` reads its argument once, at first mount, and
ignores every later prop change: open the gallery, close it, click *Type the animal I
want*, and the gallery opens again. That is `SPEC_PET_DESIGNER_FLOW` §13's recorded miss
with the symptom inverted — *"the chooser's state was destroyed on every close and it
reopened claiming Cat/Tabby over a corgi"* — state the parent must control, living in the
child. Inlining the field deletes the second view, and with it the state that carried the
bug. **Do not reintroduce a `view` prop to make the dialog multi-purpose again**; if a
second view is ever genuinely needed, make the dialog fully controlled (`view` + `onView`
props, no internal `useState`) rather than seeding it from a prop.

---

## 11. Amendments owed to `SPEC_PET_DESIGNER_FLOW`

Delivering this without these edits leaves two specs disagreeing about the same screen —
the §11.3 failure the flow spec already carries once.

| Section | Change |
|---|---|
| **§3.1** | Retitle *"The box is the interface"* → the box is the **subject**; the question is on the page. Keep the Rev.1–4 second-door argument verbatim — it is still correct and §2 depends on it — and add the distinction it turns on: a second control performing an existing action is a second door; the first statement of a hidden question is not. Record §2.1's accepted overlap explicitly |
| **§3.2** | The three-door table stands unchanged in substance. Note that the doors are reached from the rail, that the typed door's Confirm is now the rail's own button (Enter still draws), and that the dialog holds only the gallery |
| **§3.6** | Note the controls now sit in the left column under the rail, not centred beneath the box; that the draw button for a typed source sits in the rail beside its field (`canRedraw` covers uploads only); and that **Use this animal →** moved under the picture and is rendered rather than disabled (§1.7) |
| **§3.5** | New subsection: what reaches the server. The MIME list and 12 MB cap are unchanged and remain the authority; all three intake paths now pass one client gate, and oversize is downscaled to the server's own 1024 px rather than rejected (§1.10) |
| **§3.7** | The toggle's two halves still live apart, but the reason shifted: the commit now sits in the always-rendered `artifact` slot, so it carries its own `showsControls` gate instead of relying on the body unmounting (§1.7) |
| **§3.8** | `<ModalOverlay>` unchanged; the dialog it wraps is now one view, not three, and is named `BaseGalleryDialog` |
| **§4.8** | Delete *"Step 1 stays centred: it has three controls, so there is no distance to close."* Both steps are split; step 1's premise changed |
| **§4.7 / §8** | Their locks (`Use this as my pet →`, `Bring it to life`) now wear `.btn-step` — the filled treatment reserved for the three controls that end a step (§1.8) |
| **§7.6 (Files)** | `globals.css` gains `.btn-step`. The component list gains `SourceRail.tsx` and renames `BaseAnimalDialog.tsx` → `BaseGalleryDialog.tsx`; the directory is `design/general/`, not `general2/`, and the root component is `Designer.tsx`, not `PetDesigner2.tsx` |
| **§1.1 / §12** | First paint 2 → **6**, with §3's reasoning. Do not quietly restate the metric — §12 exists because a control count was once claimed rather than measured |
| **§13** | New row: *"Nothing else is on screen" (§3.1)* → true for controls that duplicate an action, wrong for the question itself. The pre-filled box made the chooser undiscoverable, and the product's headline capability — type any animal — was invisible until clicked. Second new row: the `initialView` design (§10E) as a near-miss of §13's own recorded lesson |
| **New §3.10** | Fold in §1–§2 of this document as the as-built description of the rail |

Once folded in, this file is archived to `docs/archive/` per the repo's delivered-spec
convention.

---

## 12. What changed in Rev.2, and why

Rev.1 put all three doors on the page as three identical buttons, and kept the dialog at
two views behind an `initialView` prop. Two things were wrong with it:

| Rev.1 | Reality |
|---|---|
| Three equal buttons answer §0 | **Half an answer.** §0's complaint is that *one specific door* is invisible; equal weight gives the product's headline capability a third of a low-contrast column and still charges two interactions for it. The three doors are not symmetric — their answer surfaces differ by an order of magnitude (§1.2) — and the spec never asked whether they should be presented as if they were |
| Alternative B ("fully inline") rejects the inline typed field, citing `ReferenceBox.tsx:12-17` — *"a second 'which animal?' input on the page"* | **Misreads its own citation.** That comment records the deletion of **two competing text fields** (one labelled *"type any animal"*, one *"what animal is it?"*). Both are already gone; the page has zero. An inline field would be the first, not the second. The valid half of B's rejection — the gallery — is retained as decision #3 |
| `initialView` seeds the dialog's view state | **Broken.** See §10E. The dialog is mounted unconditionally and its state outlives every close, so the prop is read once and ignored thereafter. Rev.2 dissolves it by deleting the second view rather than patching the seed |

Rev.2 is also a **smaller** change than Rev.1 despite doing more: the `View` union, the
`view` state, the `close()` reset, the `typed` state, and two props all disappear, where
Rev.1 kept them and added a third state to coordinate them.
