# Lessons Learned — anchor prompts drift to whatever the prompt leaves unstated

**Date:** 2026-07-26 · **Area:** `pet_factory/motion_profiles`, `webui` upload door · **Severity:**
medium-high (wrong species shipped in finished bundles; one nude render) · **Fix commits:**
`908e855`, `dd530e9`, `b8a8d56` + uncommitted humanoid clause work · **Time cost:** a session,
with four wrong diagnoses worth more than the fixes.

**One-line summary:** Adding a `humanoid` body type surfaced four separate renders of the wrong
thing — a dog, a cartoon cat, a nude figure and an animal mascot — all from one root cause:
**a generation prompt fills anything it is not told from the strongest prior available**, and the
animal profiles never revealed this because an animal noun silently supplies species, activity and
covering all at once.

---

## 1. Symptoms

Four failures, over one session, each initially looking like a different bug.

| # | Input | Output | First (wrong) impression |
|---|---|---|---|
| 1 | photo of a person, upload door | a cartoon **dog** | "the image model can't do people" |
| 2 | `tom cruise` + humanoid profile | **Tom the cat** in `run` and `sleep` | "the celebrity prior is too strong" |
| 3 | same build, `idle` pose | a **nude** figure | "amusing edge case" |
| 4 | same build, `play` pose | a person in an **animal mascot suit** | "still anchored to an animal" |

Failures 2–4 came from the *same profile in the same build*, with the other poses rendering
correctly — which is what made them diagnosable: the working poses were the control group.

---

## 2. The investigation — including four wrong turns

### Wrong turn #1 — "the dog came from the wrong `base_pose`"

The obvious theory: a person resolves to `quadruped`, whose `base_pose` is *"standing on all
fours, alert"*, so the prompt asked for a four-legged animal. Plausible, tidy, wrong.

Pulling the **actual prompt** out of ComfyUI's `/history` killed it:

```
a cute cartoon pet, exactly pet, side profile view, facing right, standing, …
```

The pose word was `standing` — the plain default, no profile involved. The damage was the noun:
the literal string **`"pet"`**, from `subject = animal or suggested or "pet"` in `app.py`.

**Lesson: read the artifact, not the code path you expect it to have taken.** Two minutes of
`/history` beat twenty minutes of reasoning about `base_pose`.

### Wrong turn #2 — comparing the wrong bytes

Testing whether the negative prompt did anything: same seed, same positive, three very different
negatives. Three different **file hashes** → "the negative is applied, don't remove it."

Wrong. ComfyUI stamps the workflow JSON into PNG metadata, so the *files* differed by exactly the
length of each negative string while the **pixels** were byte-identical. Comparing
`Image.open(p).tobytes()` instead reversed the conclusion completely.

**Lesson: hash the thing you are actually asking about.** A file hash answers "are these files the
same", not "do these images look the same".

### Wrong turn #3 — asserting how the UI worked

I told the user the Motion Lab's profile dropdown was manual, and reasoned about a bug on that
basis. Their screenshot said `↳ auto-matched from "Komodo dragon"`. It auto-matches — by the
*keyword* path, while a real build resolves by the *AI* path, which is a second bug I had just
talked past.

**Lesson: when the user's screenshot and my model of the UI disagree, the screenshot is right.**

### Wrong turn #4 — testing without reloading

Twice, a fix was declared not-working when it had never run: the backend caches motion profiles in
memory and has no `--reload`, so a JSON edit is invisible until restart. The second time, the user
had already drawn the conclusion *"the word Tom is too strong, accept it as a limitation"* — from a
run that used the pre-fix clauses.

**Lesson: before interpreting a negative result, prove the new code was loaded.** Comparing the
process start time against the file mtime takes one command and prevents a wrong conclusion from
being adopted as a design decision.

---

## 3. Root cause

One sentence: **the prompt is a specification with defaults, and every gap is filled by the
strongest prior in it.**

| what was left unstated | what filled it |
|---|---|
| the subject noun (captioner bailed) | `"pet"` → the most generic pet → a dog |
| the body plan (`run`, `sleep` clauses) | `a cute cartoon **tom**` → Tom & Jerry's cat |
| the activity (`idle` clause) | *"standing, weight on one leg, arms loose"* = contrapposto → a life-drawing nude |
| a human-typical gesture (`play`) | `a cute cartoon` + bouncing, arms out → a mascot |

**Why the animal profiles never hit this.** An animal noun carries everything at once: `corgi`
states the species, implies four-legged locomotion, and brings its own fur. `humanoid` states
none of it — the noun can be `tom cruise`, `alien`, or `robot`, and the covering is clothing,
which does not come free. Every assumption the animal profiles were quietly making had to be
written out.

**Why `pose_anchor` made it visible.** Anchors are drawn **txt2img** from a fresh prompt, not
img2img from the locked still. So the reference image cannot rescue a weak clause: whatever the
words fail to say, the model invents. And once the anchor is a cat, Wan animates that cat
perfectly faithfully — the motion engine was never at fault in any of the four cases.

---

## 4. The fixes

**Upload door (`webui/app.py`, `ai_purposes/image_triage.json`)**
1. Triage's `usable` question no longer requires a *side-profile* shot — a front-facing headshot
   was failing the gate, which is why the captioner bailed and the noun fell back to `"pet"`.
2. The `"pet"` fallback is gone. Nothing named it → **HTTP 422 and ask**. `"pet"` was not a
   neutral default but a species assertion.
3. A motion profile is now always resolved and pinned on an upload. Previously the profile was
   resolved from a deliberately-blanked noun, so uploads stored `motion_profile: null` and the
   build keyword-resolved from `"pet"` — meaning the new `humanoid` profile was unreachable from
   the upload door entirely.

**Humanoid clauses (`motion_profiles/humanoid.json`)**
4. Every clause opens with the **body plan** — `upright on two legs` — not the species. `"a person"`
   was rejected deliberately: the profile also serves aliens, robots, elves and zombies.
5. All `its` removed (`arms loose at the sides`, not `at its sides`) — inherited from the animal
   profiles it was modelled on, and quietly voting *creature*.
6. `idle` and `play` rewritten from **stances into activities**: *idling and looking bored, arms
   folded*; *waving hello with one raised hand*.

**Rejected fix worth recording:** adding `fully clothed` to every clause. It worked, and it was
the wrong layer — clothing is a *design* choice (someone may want a naked figure, or a bikini),
and the motion profile owns how a body moves, not how it looks. Reverted, and the nude was fixed
by changing the *gesture* instead.

---

## 5. Lessons learned

### Three authoring rules, each paid for with a GPU run

1. **Name the limb that moves** *(known before today; §4 of the animation reference)*. The motion
   prompt must say which body part cycles. Silence about a limb is silence in the pixels.
2. **Re-assert the body plan in every anchor clause.** A pose describes a posture; it must also
   describe the body holding it, or an ambiguous noun supplies one.
3. **Match the gesture to the body type.** *Gesture is species evidence.* The model reads what a
   body is *doing* as a clue to what kind of body it *is*. Give a humanoid a mascot's bounce and
   you get a mascot; give it a life-drawing stance and you get a life-drawing subject. This is why
   the animal profiles are safe — only a dog play-bows.

### Process lessons

- **Never let a fallback assert a fact.** `"pet"` looked like a harmless default and was actually
  a confident wrong answer about species, invisible in the code and in the UI.
- **A silent degradation is worse than an error.** Both the triage rejection and the AI
  classifier's invalid answer fell back quietly by design. Correct behaviour, but with no
  visibility the system happily produced wrong output for weeks.
- **Prefer measuring to reasoning when the GPU is right there.** Every real conclusion this
  session came from `/history`, a pixel hash, or a reference record — never from reading code.
- **Working cases are the control group.** Four poses rendered correctly and three did not, in
  the same build. Diffing the clauses found the cause in minutes; without them it would have
  looked like model flakiness.

### A pattern to watch for elsewhere

Any time a config format is generalised to a new kind of subject, check what the *old* subjects
were supplying implicitly. Here, three separate assumptions rode along inside the word "corgi".
The same trap exists in the AI classifier prompt: profile labels were captions until they became
prose, at which point the `key — label (movement_class)` line format became ambiguous and the
model started answering with the wrong field — silently degrading to keyword resolution
(fixed in `dd530e9`).
