/** @type {import('tailwindcss').Config} */

// Colours resolve through CSS custom properties (see src/index.css), so a theme
// switch reassigns variables instead of requiring `dark:` on every element.
// The `<alpha-value>` placeholder keeps Tailwind's opacity modifiers working,
// e.g. `bg-accent/10`.
//
// The scale below is the DesignMD `cursor` system: 4px spacing base, compact
// 8px control radius, hairline-only depth, and a display scale that sits at
// weight 400 with negative tracking.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: token('canvas'),
        surface: {
          DEFAULT: token('surface'),
          sunk: token('surface-sunk'),
          hover: token('surface-hover'),
        },
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          faint: token('ink-faint'),
        },
        line: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          soft: token('accent-soft'),
          ink: token('accent-ink'),
        },
        annotate: {
          DEFAULT: token('annotate'),
          soft: token('annotate-soft'),
        },
        success: { DEFAULT: token('success'), soft: token('success-soft') },
        warning: { DEFAULT: token('warning'), soft: token('warning-soft') },
        danger: { DEFAULT: token('danger'), soft: token('danger-soft') },

        // The AI-timeline pastels. Stage markers only — never action colours.
        stage: {
          1: token('stage-1'),
          2: token('stage-2'),
          3: token('stage-3'),
          4: token('stage-4'),
          5: token('stage-5'),
        },
      },

      fontFamily: {
        // Paper titles are set in the typeface papers themselves use. The
        // document speaks in serif; the tool around it speaks in sans.
        // Cursor names an editorial serif as its alternate display voice,
        // which is exactly the role a paper title plays here.
        serif: [
          'Iowan Old Style', 'Palatino Linotype', 'Palatino', 'Charter',
          'Georgia', 'ui-serif', 'serif',
        ],
        // Inter is the open-source substitute the Cursor system names.
        sans: [
          'Inter Variable', 'Inter', 'system-ui', '-apple-system',
          'Helvetica Neue', 'Helvetica', 'Arial', 'sans-serif',
        ],
        // Mandated on every technical surface: identifiers, metrics, code.
        mono: [
          'JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace',
          'SFMono-Regular', 'Menlo', 'Consolas', 'monospace',
        ],
      },

      fontSize: {
        // Tracked-out uppercase label — `caption-uppercase`, 11px/600/0.88px.
        eyebrow: ['0.6875rem', { lineHeight: '1.4', letterSpacing: '0.08em' }],
        caption: ['0.8125rem', { lineHeight: '1.4' }],
        code: ['0.8125rem', { lineHeight: '1.5' }],
        // Display sizes. Weight stays 400 — see the `.display` base rule.
        'display-xs': ['1.375rem', { lineHeight: '1.3', letterSpacing: '-0.005em' }],
        'display-sm': ['1.625rem', { lineHeight: '1.25', letterSpacing: '-0.0125em' }],
        display: ['2.25rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        'display-lg': ['4.5rem', { lineHeight: '1.1', letterSpacing: '-0.03em' }],
      },

      borderRadius: {
        DEFAULT: 'var(--radius)',
        sm: 'var(--radius-sm)',
        lg: 'var(--radius-lg)',
      },

      boxShadow: {
        sm: 'var(--shadow-sm)',
        DEFAULT: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
      },

      transitionTimingFunction: {
        out: 'var(--ease-out)',
        in: 'var(--ease-in)',
        'in-out': 'var(--ease-in-out)',
      },

      transitionDuration: {
        micro: 'var(--duration-micro)',
        fast: 'var(--duration-fast)',
        DEFAULT: 'var(--duration-default)',
        medium: 'var(--duration-medium)',
        slow: 'var(--duration-slow)',
      },

      // 80px section rhythm, 1200px editorial container.
      spacing: {
        section: '5rem',
      },

      maxWidth: {
        prose: '68ch',
        container: '75rem',
      },
    },
  },
  plugins: [],
}
