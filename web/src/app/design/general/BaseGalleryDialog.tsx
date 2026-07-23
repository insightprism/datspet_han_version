"use client";

/**
 * <BaseGalleryDialog> — the curated bases, and nothing else
 * (SPEC_STEP1_SOURCE_RAIL §1.3).
 *
 * This file used to hold three views and ask step 1's question. It no longer asks
 * anything: <SourceRail> asks "where should it come from?" on the page, the typed field
 * lives there too, and what is left here is ONE answer surface — "which breed?".
 *
 * That is why it has no `view` state, no `View` union and no reset-on-close. A one-view
 * dialog needs no view plumbing, and the `initialView` prop an earlier draft proposed was
 * not merely unnecessary but broken: this component is mounted unconditionally by
 * <Designer> and only <ModalOverlay> returns null when closed, so its state outlives every
 * close — `useState(initialView)` would read once at first mount and ignore every later
 * change (§10E). Do NOT reintroduce a `view` prop to make this multi-purpose again; if a
 * second view is ever genuinely needed, make it fully controlled (`view` + `onView`), never
 * seeded from a prop.
 *
 * Picking a base EXECUTES it (§3.2) — it is a file, ~6 ms, and the result IS the thing you
 * clicked, so there is nothing to approve first. The dialog does not commit: the base is
 * set by the one button outside.
 *
 * The overlay shell is <ModalOverlay> — the shared primitive that owns scroll-lock,
 * safe-area insets, the height cap, the inner scroller, Escape and focus-return. This file
 * owns none of that and must never hand-roll it.
 */
import ModalOverlay from "@/components/ModalOverlay";
import { catalogBaseImageUrl, type CatalogBaseOption } from "@/lib/api";

interface Props {
  open: boolean;
  options: CatalogBaseOption[];
  onClose: () => void;
  onPickCurated: (o: CatalogBaseOption) => void;
}

export default function BaseGalleryDialog({ open, options, onClose, onPickCurated }: Props) {
  // Group by animal, preserving catalog order (the order a human authored them in).
  const groups = options.reduce<{ key: string; label: string; breeds: CatalogBaseOption[] }[]>(
    (acc, o) => {
      let g = acc.find((x) => x.key === o.animal);
      if (!g) { g = { key: o.animal, label: o.animalLabel ?? o.animal, breeds: [] }; acc.push(g); }
      g.breeds.push(o);
      return acc;
    }, []);

  return (
    <ModalOverlay open={open} onClose={onClose} labelledBy="base-dialog-title">
      <h2 id="base-dialog-title" className="mb-1 text-lg font-semibold"
          style={{ color: "var(--heading)" }}>
        Pick an existing base animal
      </h2>
      <p className="mb-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        These are hand-picked, and free to use.
      </p>

      <div className="flex flex-col gap-4">
        {/* The curated bases are SHOWN, not described. They are already images on
            disk, and making someone read "Cat → Tabby" out of a dropdown to learn
            what a tabby looks like inverts the point of curating them (platform
            §4.3: "the user starts from a picture, not a blank screen"). */}
        {groups.map((g) => (
          <div key={g.key} className="flex flex-col gap-2">
            <div className="mono text-xs" style={{ color: "var(--faint)" }}>{g.label}</div>
            <div className="flex flex-wrap gap-2">
              {g.breeds.map((b) => (
                <button
                  key={`${b.animal}/${b.key}`}
                  type="button"
                  title={b.label}
                  onClick={() => { onPickCurated(b); onClose(); }}
                  className="flex flex-col items-center gap-1 rounded-lg border p-2 transition hover:opacity-80"
                  style={{ background: "#151515", borderColor: "var(--line)" }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={catalogBaseImageUrl(b.animal, b.key)} alt={b.label}
                       style={{ width: 72, height: 72, objectFit: "contain" }} />
                  <span className="mono text-xs" style={{ color: "var(--muted)" }}>{b.label}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {/* Closing is what reveals the other options now — they are on the page behind
            this overlay. Kept because Escape and backdrop-click are both undiscoverable
            (§1.3). */}
        <button type="button" className="btn-ghost self-start text-xs" onClick={onClose}>
          ← other options
        </button>
      </div>
    </ModalOverlay>
  );
}
