/**
 * The mark: a page with its section spine — the same rail that structures the
 * app, reduced to a glyph. Monoline, drawn in `currentColor`, so it inherits
 * the accent in the header and the ink anywhere else.
 *
 * No gradients and no looping animation: this system builds depth from
 * hairlines alone, and a mark that never stops moving is not a quiet one.
 */
export default function Logo({ className = 'w-8 h-8', type = 'icon' }) {
  const glyph = (
    <g
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* The sheet, with a turned corner. */}
      <path d="M9 3.5h13.5L30 11v21.5a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-27a2 2 0 0 1 2-2Z" />
      <path d="M22 3.5V11h7.5" />
      {/* The spine rail and its nodes — §-numbered sections, abstracted. */}
      <path d="M13 16.5v12" strokeOpacity="0.45" />
      <path d="M17 16.5h8M17 22h8M17 27.5h5" />
    </g>
  )

  const nodes = (
    <g fill="currentColor">
      <circle cx="13" cy="16.5" r="1.6" />
      <circle cx="13" cy="22" r="1.6" fillOpacity="0.5" />
      <circle cx="13" cy="27.5" r="1.6" fillOpacity="0.5" />
    </g>
  )

  if (type === 'full') {
    return (
      <svg
        className={className}
        viewBox="0 0 190 40"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="PaperMind"
      >
        <g transform="translate(0, 2)">
          {glyph}
          {nodes}
        </g>
        <text
          x="44"
          y="26"
          fontFamily="Inter Variable, Inter, system-ui, sans-serif"
          fontSize="20"
          fontWeight="500"
          letterSpacing="-0.5"
          fill="currentColor"
        >
          PaperMind
        </text>
      </svg>
    )
  }

  return (
    <svg
      className={className}
      viewBox="0 0 37 38"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="PaperMind"
    >
      {glyph}
      {nodes}
    </svg>
  )
}
