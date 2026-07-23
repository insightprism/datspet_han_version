/**
 * prepareUpload — the one gate every uploaded photo passes through
 * (SPEC_STEP1_SOURCE_RAIL §1.10).
 *
 * Step 1 has three ways to hand over a photo — the OS picker, drag-and-drop, and paste —
 * and before this file only the OS picker checked anything. Drop accepted literally any
 * file (a .txt went through), and paste accepted any `image/*`, including formats the
 * server rejects. Both failures then surfaced at the worst possible moment: after the user
 * pressed Draw, as a 400 from the backend, next to a blank preview.
 *
 * Size failed the same way and worse. The server's 12 MB cap is a hard 413 with no
 * downscale — while `_encode_reference_image` (webui/app.py:302) thumbnails EVERY accepted
 * image to ≤1024 px on its longest side four lines later. So a 12.1 MB photo was rejected
 * for exceeding a budget that nothing downstream cared about, having already been uploaded
 * in full over the wire.
 *
 * This does on the client what the server was going to do anyway, before the bytes move:
 * validate the type, downscale to MAX_PX, re-encode. The server's cap stays exactly where
 * it is — it is the security boundary, and a direct API call never touches this file — but
 * the UI can no longer produce something that trips it.
 *
 * NOT a general image utility. It encodes step 1's specific contract (the server's MIME
 * list, the server's 1024 px), so it lives with step 1. If a second uploader ever appears,
 * that is the moment to lift it — not before.
 */

/** Mirrors `ALLOWED_IMAGE_MIMES` (webui/app.py:147). The server remains the authority. */
export const ACCEPTED_IMAGE_MIMES = [
  "image/png", "image/jpeg", "image/webp", "image/gif",
] as const;

/** For the file input's `accept` — so the picker and this gate cannot drift apart. */
export const ACCEPT_ATTR = ACCEPTED_IMAGE_MIMES.join(",");

/**
 * The longest side we send. Not a number invented here: it is `_encode_reference_image`'s
 * own `max_px` (webui/app.py:302), which the pool path applies to every reference image
 * before shipping it to a worker. Downscaling here is doing that work earlier, so it costs
 * nothing in output quality — the worker re-pads to a square canvas regardless.
 */
export const MAX_PX = 1024;

/**
 * Mirrors `MAX_UPLOAD_BYTES` (webui/app.py:146). Used only to decide whether an original
 * is small enough to keep in preference to our re-encode — the server's copy is the one
 * that actually rejects, and it stays exactly where it is.
 */
export const MAX_BYTES = 12 * 1024 * 1024;

/** Thrown for a file we will not send. The message is shown to the user verbatim. */
export class UploadRejected extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UploadRejected";
  }
}

const SUPPORTED = "Use a PNG, JPEG, WebP or GIF.";

function rejectionFor(file: File): string | null {
  const type = (file.type || "").toLowerCase();
  const ext = file.name.toLowerCase().split(".").pop() ?? "";

  if ((ACCEPTED_IMAGE_MIMES as readonly string[]).includes(type)) return null;

  // The one worth its own sentence: HEIC is the iPhone default, so this is the format
  // people will actually hit. It cannot be converted here — no browser outside Safari
  // decodes it, and shipping a wasm decoder for one door is not a trade worth making.
  if (type === "image/heic" || type === "image/heif" || ext === "heic" || ext === "heif") {
    return "iPhone HEIC photos aren't supported yet — save it as JPEG or PNG first "
         + "(Settings → Camera → Formats → Most Compatible).";
  }
  if (type.startsWith("image/")) {
    return `${type.slice(6).toUpperCase()} images aren't supported. ${SUPPORTED}`;
  }
  // An empty type is not a rejection: some drag sources supply none. Let the decoder
  // decide — it is the only honest test of whether bytes are an image.
  if (type === "") return null;
  return `That doesn't look like an image. ${SUPPORTED}`;
}

/**
 * Validate, downscale and re-encode a user-supplied photo.
 *
 * Returns the ORIGINAL file untouched when it is already within bounds — re-encoding a
 * small JPEG would throw away quality to accomplish nothing.
 *
 * @throws {UploadRejected} with a message written for the user.
 */
export async function prepareUpload(file: File): Promise<File> {
  const rejection = rejectionFor(file);
  if (rejection) throw new UploadRejected(rejection);

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new UploadRejected(`That file couldn't be read as an image. ${SUPPORTED}`);
  }

  try {
    const longest = Math.max(bitmap.width, bitmap.height);
    if (longest <= MAX_PX) return file;

    const scale = MAX_PX / longest;
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new UploadRejected("Your browser couldn't resize that image.");
    // Downscaling by a large factor without this is visibly aliased — and the sprite
    // redraw amplifies whatever it is handed.
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, width, height);

    // JPEG stays JPEG: a photo re-encoded as PNG is ~10x the bytes for no visible gain,
    // which works against the point of being here. Everything else becomes PNG, which
    // keeps the alpha a PNG/GIF/WebP may carry — flattening to JPEG would land
    // transparent pixels on black.
    const outType = file.type === "image/jpeg" ? "image/jpeg" : "image/png";
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, outType, 0.92));
    if (!blob) throw new UploadRejected("Your browser couldn't resize that image.");

    // Re-encoding can LOSE. A well-compressed 3000 px PNG can beat our 1024 px PNG of the
    // same picture, because resampling raises entropy — measured at 548 KB in, 2.9 MB out.
    // Fewer pixels is not automatically fewer bytes, and bytes are the thing being fixed
    // here. When the original already fits, it wins; the server downscales to this same
    // 1024 px anyway, so nothing downstream notices.
    if (blob.size >= file.size && file.size <= MAX_BYTES) return file;

    return new File([blob], renameFor(file.name, outType), { type: outType });
  } finally {
    bitmap.close();
  }
}

/** Keep the user's filename, correct the extension when the encoding changed. */
function renameFor(name: string, outType: string): string {
  const ext = outType === "image/jpeg" ? "jpg" : "png";
  const base = name.replace(/\.[^.]+$/, "") || "photo";
  return `${base}.${ext}`;
}
