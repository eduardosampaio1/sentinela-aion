"use client";

export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      fill="none"
      width={size}
      height={size}
    >
      <defs>
        <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#14B8A6" />
          <stop offset="100%" stopColor="#0F766E" />
        </linearGradient>
      </defs>
      <circle cx="256" cy="256" r="220" stroke="url(#ringGrad)" strokeWidth="28" fill="none"
        strokeDasharray="1320 62" strokeDashoffset="-31" strokeLinecap="round" />
      <path d="M160 132 A148 148 0 0 1 352 132"
        stroke="#2DD4BF" strokeWidth="4" fill="none" strokeLinecap="round" opacity="0.5" />
      <path d="M352 380 A148 148 0 0 1 160 380"
        stroke="#2DD4BF" strokeWidth="4" fill="none" strokeLinecap="round" opacity="0.35" />
      <circle cx="256" cy="256" r="36" fill="#0F766E" />
      <circle cx="256" cy="256" r="36" stroke="#14B8A6" strokeWidth="3" fill="none" />
      <circle cx="256" cy="256" r="14" fill="#14B8A6" />
      <circle cx="256" cy="36" r="10" fill="#14B8A6" />
      <circle cx="66" cy="366" r="10" fill="#14B8A6" opacity="0.7" />
      <circle cx="446" cy="366" r="10" fill="#14B8A6" opacity="0.7" />
      <line x1="256" y1="56" x2="256" y2="220" stroke="#2DD4BF" strokeWidth="2" opacity="0.3" />
      <line x1="82" y1="356" x2="228" y2="274" stroke="#2DD4BF" strokeWidth="2" opacity="0.2" />
      <line x1="430" y1="356" x2="284" y2="274" stroke="#2DD4BF" strokeWidth="2" opacity="0.2" />
    </svg>
  );
}
