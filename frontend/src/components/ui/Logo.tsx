/** The SIQE crystal: cyan lattice, gold core, gold spark. */
export function Logo({ className = "size-7" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <g fill="none" stroke="var(--cyan)" strokeWidth="1.5" strokeLinejoin="round">
        <path d="M16 3l11 6.4v13.2L16 29 5 22.6V9.4z" />
        <path d="M16 3v26M5 9.4l22 13.2M27 9.4L5 22.6" opacity=".45" />
      </g>
      <path d="M16 11l4.5 2.6v5.2L16 21.4l-4.5-2.6v-5.2z" fill="var(--gold)" />
      <circle cx="25.5" cy="6.5" r="2" fill="var(--gold)" />
    </svg>
  );
}

/** Forge icon: a faceted cube, matching the blueprint mockups. */
export function ForgeIcon({ className = "size-[19px]" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      <path d="M12 2.8l8 4.6v9.2l-8 4.6-8-4.6V7.4z" strokeLinejoin="round" />
      <path d="M12 12l8-4.6M12 12v9.2M12 12L4 7.4" strokeLinejoin="round" />
    </svg>
  );
}
