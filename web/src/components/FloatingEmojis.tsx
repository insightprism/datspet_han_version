"use client";

import { useMemo, useState, useEffect } from "react";

/**
 * Determine if a hex color is "dark" (luminance < 0.5).
 * Returns true for dark backgrounds, false for light.
 */
function isDarkColor(hex: string): boolean {
  const c = hex.replace("#", "");
  if (c.length < 6) return true;
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  // Relative luminance (ITU-R BT.709)
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance < 0.5;
}

/**
 * Renders subtle floating emoji particles in the background.
 * Each emoji drifts slowly with a unique position, size, and animation delay.
 * Emoji brightness auto-adjusts to contrast against the page background.
 */
export default function FloatingEmojis({ emojis }: { emojis: string }) {
  const emojiList = emojis ? emojis.split(",").filter(Boolean) : [];

  // Detect if background is dark or light and adjust emoji rendering
  const [darkBg, setDarkBg] = useState(true);
  useEffect(() => {
    if (typeof document === "undefined") return;
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    if (bg) setDarkBg(isDarkColor(bg));

    // Re-check when CSS variable changes (theme switch)
    const observer = new MutationObserver(() => {
      const updated = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
      if (updated) setDarkBg(isDarkColor(updated));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });
    return () => observer.disconnect();
  }, []);

  // Generate fixed particle positions (deterministic from emoji content)
  const particles = useMemo(() => {
    if (emojiList.length === 0) return [];

    const items: { emoji: string; left: number; top: number; size: number; delay: number; duration: number }[] = [];
    // Scatter 12-15 particles across the page
    const count = Math.min(15, emojiList.length * 4);

    for (let i = 0; i < count; i++) {
      items.push({
        emoji: emojiList[i % emojiList.length],
        left: ((i * 37 + 13) % 90) + 5,  // pseudo-random spread 5-95%
        top: ((i * 53 + 7) % 85) + 5,     // pseudo-random spread 5-90%
        size: 16 + (i % 3) * 6,            // 16px, 22px, or 28px
        delay: (i * 1.3) % 8,              // stagger animation starts
        duration: 12 + (i % 5) * 4,        // 12-28s per cycle
      });
    }
    return items;
  }, [emojiList.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  if (particles.length === 0) return null;

  return (
    <>
      <style>{`
        @keyframes emoji-float {
          0%, 100% { transform: translateY(0px) rotate(0deg); }
          25% { transform: translateY(-12px) rotate(5deg); }
          50% { transform: translateY(-6px) rotate(-3deg); }
          75% { transform: translateY(-18px) rotate(2deg); }
        }
      `}</style>
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        {particles.map((p, i) => (
          <span
            key={i}
            className="absolute select-none"
            style={{
              left: `${p.left}%`,
              top: `${p.top}%`,
              fontSize: `${p.size}px`,
              opacity: darkBg ? 0.12 : 0.08,
              filter: darkBg
                ? "grayscale(0.3) brightness(1.8)"   // lighten emojis on dark backgrounds
                : "grayscale(0.3) brightness(0.4)",   // darken emojis on light backgrounds
              animation: `emoji-float ${p.duration}s ease-in-out ${p.delay}s infinite`,
            }}
          >
            {p.emoji}
          </span>
        ))}
      </div>
    </>
  );
}
