"use client";

import Image from "next/image";

/**
 * Logo mark — only the blue square symbol from the Sentinela AION lockup.
 * Use in tight spaces (sidebar 28px, favicon, browser tab).
 *
 * For the full horizontal lockup with the "sentinela aion" wordmark, use <LogoFull />.
 */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <Image
      src="/logo-mark.svg"
      alt="Sentinela AION"
      width={size}
      height={size}
      priority
    />
  );
}

/**
 * Full Sentinela AION lockup — wordmark + symbol. Horizontal.
 * Use in headers / login screens where there is room for the full brand.
 *
 * The aspect ratio of the source SVG is roughly 16:9 (1672 × 941).
 */
export function LogoFull({ width = 200 }: { width?: number }) {
  // Maintain source aspect ratio: 1672/941 ≈ 1.78
  const height = Math.round(width * (941 / 1672));
  return (
    <Image
      src="/logo-full.svg"
      alt="Sentinela AION"
      width={width}
      height={height}
      priority
    />
  );
}
