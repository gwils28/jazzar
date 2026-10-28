/** Logo Jazzar : une croche dont la tête est le disque d'accrétion d'un quasar, la hampe le jet et le crochet son panache.
 *  Couleurs via les tokens : tête `--logo-head` (orange en sombre, bordeaux en clair), reste en `--fg`. */
export function Logo({ size = 32 }: { size?: number }) {
  // En dessous de 20 px l'anneau externe n'est plus lisible : on le retire et on épaissit la hampe.
  const small = size < 20;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      {!small && (
        <ellipse cx="26" cy="42" rx="21" ry="13" transform="rotate(-25 26 42)" fill="none" stroke="var(--logo-head)" strokeWidth="1.5" opacity=".5" />
      )}
      <path d={small ? "M36 38 L40.6 38 L39.6 5 L37.1 5 Z" : "M36.4 38 L40.2 38 L39.3 5 L37.5 5 Z"} fill="var(--fg)" />
      <path
        d={small ? "M38 5 C 48 9, 53 17, 47 27 C 49.5 18, 45.5 13, 38 12.5 Z" : "M38.5 5 C 47 9, 51 16, 46.5 26 C 48.5 17.5, 45 12.5, 38.5 11.5 Z"}
        fill="var(--fg)"
      />
      <ellipse cx="26" cy="42" rx="14" ry="9.5" transform="rotate(-25 26 42)" fill="var(--logo-head)" />
      <circle cx="26" cy="42" r={small ? 4.5 : 4.2} fill="var(--logo-core)" />
    </svg>
  );
}
