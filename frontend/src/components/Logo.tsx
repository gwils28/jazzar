/** Logo Jazzar : un quasar stylisé (disque + jets) dans la palette. */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
      <defs>
        <radialGradient id="jzg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#F4F1DE" />
          <stop offset="45%" stopColor="#F4A261" />
          <stop offset="100%" stopColor="#7A1C1C" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="32" cy="32" rx="26" ry="9" stroke="#4A4E69" strokeWidth="2" transform="rotate(-25 32 32)" opacity=".9" />
      <ellipse cx="32" cy="32" rx="18" ry="6" stroke="#F4A261" strokeWidth="1.5" transform="rotate(-25 32 32)" opacity=".7" />
      <path d="M32 6 L34.5 26 L29.5 26 Z" fill="#F4A261" opacity=".9" />
      <path d="M32 58 L29.5 38 L34.5 38 Z" fill="#F4A261" opacity=".9" />
      <circle cx="32" cy="32" r="10" fill="url(#jzg)" />
      <circle cx="32" cy="32" r="4" fill="#F4F1DE" />
    </svg>
  );
}
