"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePetJob } from "@/hooks/usePetJob";
import PetJobResult from "@/components/PetJobResult";

export default function DescribePage() {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const [dragover, setDragover] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { job, error, setError, submit, reset, busy, done } = usePetJob();

  const acceptFile = useCallback((f: File) => {
    if (!f.type.startsWith("image/")) return;
    setFile(f);
    setFilePreview((old) => {
      if (old) URL.revokeObjectURL(old);
      return URL.createObjectURL(f);
    });
  }, []);

  // Paste an image anywhere on the page.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items ?? []).find((x) =>
        x.type.startsWith("image/"),
      );
      const f = item?.getAsFile();
      if (f) acceptFile(f);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [acceptFile]);

  function onSubmit() {
    if (!file && !text.trim() && !name.trim()) {
      setError("Give the pet a name/description or drop in an image.");
      return;
    }
    const fd = new FormData();
    if (name.trim()) fd.append("name", name.trim());
    if (text.trim()) fd.append("text", text.trim());
    if (file) fd.append("image", file);
    submit(fd);
  }

  function onReset() {
    reset();
    setName("");
    setText("");
    setFile(null);
    setFilePreview((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
  }

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Make your own pet
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Describe a pet — or drop in a picture of one — and get back a living DatsMe pet:
        a walking loop and an idle loop, packed as a ready-to-upload breed bundle (.zip).
        Generated locally on this machine&apos;s GPU. Takes about 3 minutes.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/design"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
        >
          🎨 Design your own →
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      {!done && (
        <div className="card mb-6 p-6">
          <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
            Pet name (optional — also steers the animation)
          </label>
          <input
            type="text"
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. red panda, chubby penguin"
            disabled={busy}
            className="mb-4 w-full rounded-lg px-3 py-2.5 text-[15px] outline-none"
            style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
          />

          <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
            Reference image (optional — your pet, side profile facing right)
          </label>
          <div
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
            onDragLeave={() => setDragover(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragover(false);
              if (e.dataTransfer.files[0]) acceptFile(e.dataTransfer.files[0]);
            }}
            className="flex min-h-[130px] w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl p-4 text-center text-sm transition-colors"
            style={{
              background: dragover ? "rgba(99,102,241,0.08)" : "#151515",
              border: `2px dashed ${dragover ? "var(--accent)" : "var(--line)"}`,
              color: file ? "var(--foreground)" : "var(--faint)",
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && acceptFile(e.target.files[0])}
            />
            <span>{file ? file.name : "drop, paste, or click to choose an image"}</span>
            <span className="text-xs" style={{ color: "var(--faint)" }}>
              with an image, the animation is built from YOUR picture; without one, the pet is drawn from the description
            </span>
            {filePreview && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={filePreview} alt="reference preview" className="mt-1 max-h-28 max-w-28 rounded-md shadow" />
            )}
          </div>

          <div className="mono my-3 text-center text-xs tracking-[0.2em]" style={{ color: "var(--faint)" }}>
            — OR —
          </div>

          <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
            Text description
          </label>
          <textarea
            value={text}
            maxLength={200}
            onChange={(e) => setText(e.target.value)}
            placeholder='e.g. "purple baby dragon with golden eyes and tiny wings"'
            disabled={busy}
            className="min-h-[64px] w-full resize-y rounded-lg px-3 py-2.5 text-[15px] outline-none"
            style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
          />

          <button
            onClick={onSubmit}
            disabled={busy}
            className="mono mt-4 w-full rounded-xl py-3.5 text-[15px] font-bold tracking-wide transition active:scale-[0.98] disabled:opacity-45"
            style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}
          >
            {busy ? "Generating…" : "Generate my pet"}
          </button>
          <div className="mono mt-3 min-h-5 text-sm" style={{ color: "var(--accent)" }}>{error}</div>
        </div>
      )}

      {job && <PetJobResult job={job} onReset={onReset} />}
    </main>
  );
}
