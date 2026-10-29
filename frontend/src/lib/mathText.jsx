/**
 * Inline LaTeX → readable text.
 *
 * Papers are written in LaTeX, so the text the pipeline extracts carries its
 * notation: an encoder-decoder network `$f$`, parameters `$\alpha$` and
 * `$\beta$`, a VGG19 network `$\phi$`. The summariser reproduces those spans
 * faithfully, which is correct — they are the names the paper uses — but they
 * were reaching the page as literal source, so a reader saw `$\phi$` where the
 * paper shows φ.
 *
 * This resolves the subset that actually appears in prose: symbol commands,
 * sub/superscripts, fractions, roots, accents, and the font commands
 * (`\mathbb`, `\mathcal`, `\text`) that carry meaning in a name. It is not a
 * TeX engine — a full one (KaTeX, MathJax) is ~300KB to render what is almost
 * always a single Greek letter, and it fails loudly on the malformed fragments
 * an extractor produces. Anything unrecognised falls through as its own text,
 * so the worst case is what the reader already had.
 */

/* ── Symbol table ───────────────────────────────────────────────────────── */

const SYMBOLS = {
  // Greek, lower
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε',
  zeta: 'ζ', eta: 'η', theta: 'θ', vartheta: 'ϑ', iota: 'ι', kappa: 'κ',
  lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', varpi: 'ϖ', rho: 'ρ',
  varrho: 'ϱ', sigma: 'σ', varsigma: 'ς', tau: 'τ', upsilon: 'υ', phi: 'φ',
  varphi: 'ϕ', chi: 'χ', psi: 'ψ', omega: 'ω',
  // Greek, upper
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π',
  Sigma: 'Σ', Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  // Operators and relations
  times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓', ast: '∗', star: '⋆',
  leq: '≤', le: '≤', geq: '≥', ge: '≥', neq: '≠', ne: '≠', equiv: '≡',
  approx: '≈', sim: '∼', simeq: '≃', cong: '≅', propto: '∝', ll: '≪', gg: '≫',
  // Arrows
  rightarrow: '→', to: '→', leftarrow: '←', gets: '←', leftrightarrow: '↔',
  Rightarrow: '⇒', Leftarrow: '⇐', Leftrightarrow: '⇔', mapsto: '↦',
  uparrow: '↑', downarrow: '↓',
  // Sets and logic
  in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆', supset: '⊃',
  supseteq: '⊇', cup: '∪', cap: '∩', setminus: '∖', emptyset: '∅',
  varnothing: '∅', forall: '∀', exists: '∃', nexists: '∄', neg: '¬',
  land: '∧', wedge: '∧', lor: '∨', vee: '∨',
  // Big operators and calculus
  sum: '∑', prod: '∏', int: '∫', iint: '∬', oint: '∮', partial: '∂',
  nabla: '∇', infty: '∞', lim: 'lim',
  // Misc
  circ: '∘', bullet: '∙', dagger: '†', prime: '′', degree: '°', deg: '°',
  perp: '⊥', parallel: '∥', angle: '∠', triangle: '△', square: '□',
  ldots: '…', dots: '…', cdots: '⋯', vdots: '⋮', hbar: 'ℏ', ell: 'ℓ',
  Re: 'ℜ', Im: 'ℑ', aleph: 'ℵ', top: '⊤', bot: '⊥', surd: '√',
  langle: '⟨', rangle: '⟩', lVert: '‖', rVert: '‖', vert: '|', Vert: '‖',
  // Named functions kept as words, so \sin x reads as sin x
  sin: 'sin', cos: 'cos', tan: 'tan', log: 'log', ln: 'ln', exp: 'exp',
  max: 'max', min: 'min', arg: 'arg', argmax: 'argmax', argmin: 'argmin',
  sup: 'sup', inf: 'inf', det: 'det', dim: 'dim', mod: 'mod',
}

/** Blackboard bold — the one font command whose glyphs carry the meaning
 *  (ℝ is the reals; a plain R is a variable). */
const BLACKBOARD = {
  A: '𝔸', B: '𝔹', C: 'ℂ', D: '𝔻', E: '𝔼', F: '𝔽', G: '𝔾', H: 'ℍ', I: '𝕀',
  J: '𝕁', K: '𝕂', L: '𝕃', M: '𝕄', N: 'ℕ', O: '𝕆', P: 'ℙ', Q: 'ℚ', R: 'ℝ',
  S: '𝕊', T: '𝕋', U: '𝕌', V: '𝕍', W: '𝕎', X: '𝕏', Y: '𝕐', Z: 'ℤ',
}

/** Combining marks, appended after the character they sit over. */
const ACCENTS = {
  hat: '̂', bar: '̄', tilde: '̃', vec: '⃗',
  dot: '̇', ddot: '̈', acute: '́', grave: '̀',
  check: '̌', breve: '̆', overline: '̄',
}

/* ── Normalisation ──────────────────────────────────────────────────────── */

/** Read a `{...}` group starting at `i` (which must point at the `{`).
 *  Returns [contents, indexAfterClosingBrace], tracking nesting. */
function readGroup(src, i) {
  if (src[i] !== '{') {
    // A single-token argument: `\hat x`, `x^2`. One character, or one command.
    if (src[i] === '\\') {
      const m = /^\\[A-Za-z]+/.exec(src.slice(i))
      if (m) return [m[0], i + m[0].length]
    }
    return [src[i] ?? '', i + 1]
  }
  let depth = 0
  for (let j = i; j < src.length; j += 1) {
    if (src[j] === '{') depth += 1
    else if (src[j] === '}') {
      depth -= 1
      if (depth === 0) return [src.slice(i + 1, j), j + 1]
    }
  }
  // Unbalanced — extractors truncate mid-expression often enough to expect it.
  return [src.slice(i + 1), src.length]
}

/**
 * Resolve every command in a math fragment to plain characters.
 *
 * Sub- and superscripts are deliberately *not* handled here: they become real
 * `<sub>`/`<sup>` elements in `renderMath`, which typesets any character
 * correctly rather than only the handful Unicode has raised forms for.
 */
function normaliseCommands(src) {
  let out = ''
  let i = 0

  while (i < src.length) {
    const ch = src[i]

    if (ch !== '\\') {
      out += ch
      i += 1
      continue
    }

    const m = /^\\([A-Za-z]+)/.exec(src.slice(i))
    if (!m) {
      // An escaped literal: \{ \} \_ \% \& \$
      out += src[i + 1] ?? ''
      i += 2
      continue
    }

    const name = m[1]
    i += m[0].length

    // Spacing and sizing commands carry no text.
    if (['left', 'right', 'big', 'Big', 'bigg', 'Bigg', 'displaystyle',
         'limits', 'nolimits', 'quad', 'qquad'].includes(name)) {
      continue
    }

    if (name === 'frac' || name === 'dfrac' || name === 'tfrac') {
      const [num, afterNum] = readGroup(src, i)
      const [den, afterDen] = readGroup(src, afterNum)
      const n = normaliseCommands(num)
      const d = normaliseCommands(den)
      // Parenthesise only compound parts, so `\frac{1}{2}` stays `1/2`.
      const wrap = (s) => (/^[\w.]+$/.test(s) ? s : `(${s})`)
      out += `${wrap(n)}/${wrap(d)}`
      i = afterDen
      continue
    }

    if (name === 'sqrt') {
      const [arg, after] = readGroup(src, i)
      out += `√(${normaliseCommands(arg)})`
      i = after
      continue
    }

    if (name === 'mathbb') {
      const [arg, after] = readGroup(src, i)
      out += [...arg].map((c) => BLACKBOARD[c] || c).join('')
      i = after
      continue
    }

    // Font and text wrappers: the glyphs are what matter, not the face.
    if (['mathcal', 'mathbf', 'mathrm', 'mathit', 'mathsf', 'mathtt',
         'boldsymbol', 'text', 'textit', 'textbf', 'textrm', 'operatorname',
         'mbox'].includes(name)) {
      const [arg, after] = readGroup(src, i)
      out += normaliseCommands(arg)
      i = after
      continue
    }

    if (ACCENTS[name]) {
      const [arg, after] = readGroup(src, i)
      out += normaliseCommands(arg) + ACCENTS[name]
      i = after
      continue
    }

    if (SYMBOLS[name] !== undefined) {
      out += SYMBOLS[name]
      // `\sin x` needs its space back; `\alpha x` does not gain one.
      if (SYMBOLS[name].length > 1 && src[i] === ' ') out += ' '
      continue
    }

    // Unknown command — show the name rather than dropping it, so an
    // unmapped symbol degrades to something the reader can still identify.
    out += name
  }

  return out
}

/* ── Rendering ──────────────────────────────────────────────────────────── */

/** Split normalised text into React nodes, raising `^`/`_` groups. */
function renderScripts(src, keyPrefix) {
  const nodes = []
  let buffer = ''
  let i = 0
  let n = 0

  const flush = () => {
    if (buffer) {
      nodes.push(buffer)
      buffer = ''
    }
  }

  while (i < src.length) {
    const ch = src[i]
    if (ch === '^' || ch === '_') {
      const [arg, after] = readGroup(src, i + 1)
      if (arg) {
        flush()
        const Tag = ch === '^' ? 'sup' : 'sub'
        nodes.push(
          <Tag key={`${keyPrefix}-s${n}`} className="text-[0.75em]">
            {arg}
          </Tag>,
        )
        n += 1
        i = after
        continue
      }
    }
    buffer += ch
    i += 1
  }

  flush()
  return nodes
}

/**
 * Render one `$...$` body.
 *
 * Set in the serif italic that mathematical variables are conventionally set
 * in — which is also what distinguishes `$f$`, the network, from the letter f
 * in the surrounding sentence.
 */
export function renderMath(body, keyPrefix) {
  return (
    <span key={keyPrefix} className="font-serif italic tracking-[0.01em]">
      {renderScripts(normaliseCommands(body), keyPrefix)}
    </span>
  )
}

/**
 * Does this `$...$` span hold notation, or a dollar amount?
 *
 * "costs $5 to $10 million" contains a `$…$` pair that is not math. Requiring
 * either a command, a script, or a short bare identifier accepts `$f$`,
 * `$\alpha$`, `$x_i$`, and `$L^2$` while leaving currency alone.
 */
export function looksLikeMath(body) {
  const inner = body.trim()
  if (!inner) return false
  if (/[\\^_]/.test(inner)) return true
  return /^[A-Za-z][A-Za-z0-9]{0,2}$/.test(inner)
}

/** `$…$` and `\(…\)`, both constrained to a single line — an unmatched `$`
 *  should not swallow the rest of a paragraph. */
export const MATH_TOKEN = /(\$\$[^$\n]+\$\$|\$[^$\n]+\$|\\\([^\n]*?\\\))/

/** Strip the delimiters from a token matched by MATH_TOKEN. */
export function mathBody(token) {
  if (token.startsWith('$$')) return token.slice(2, -2)
  if (token.startsWith('\\(')) return token.slice(2, -2)
  return token.slice(1, -1)
}
