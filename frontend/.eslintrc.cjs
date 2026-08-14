/**
 * ESLint config.
 *
 * `npm run lint` was in package.json but no config file existed, so the script
 * failed outright and nothing was ever linted.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules', '.eslintrc.cjs'],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: 'detect' } },
  plugins: ['react-refresh'],
  overrides: [
    {
      // A context module has to export both its provider and the hook that
      // reads it, and `primitives.jsx` exports the `cx` helper its own
      // components are built on. The rule is a dev-only hot-reload nicety and
      // there is no way to satisfy it here without splitting every context into
      // two files — but `npm run lint` runs with `--max-warnings 0`, so leaving
      // it as a warning meant lint could never pass.
      files: [
        'src/contexts/*.jsx',
        'src/components/ui/primitives.jsx',
      ],
      rules: { 'react-refresh/only-export-components': 'off' },
    },
  ],
  rules: {
    // Vite's fast refresh only works when a module exports components alone.
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

    // Prop types are not used in this codebase; the rule would fire everywhere.
    'react/prop-types': 'off',

    // Underscore-prefixed args are intentional placeholders.
    'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],

    // Leftover debugging must not reach a build; warnings and errors are fine.
    'no-console': ['warn', { allow: ['warn', 'error'] }],

    eqeqeq: ['error', 'always', { null: 'ignore' }],
    'no-var': 'error',
    'prefer-const': 'error',

    /**
     * Catches a hook dependency array that names a `const` declared further
     * down the component.
     *
     * A dependency array is evaluated during render, at the point the
     * `useEffect` call appears — so `useEffect(..., [loadSummary])` written
     * above `const loadSummary = useCallback(...)` throws on its temporal dead
     * zone the moment the component mounts. Neither `--max-warnings 0` lint nor
     * a production build catches it, because it is legal syntax; the page just
     * dies at runtime with "Cannot access 'loadSummary' before initialization".
     *
     * Functions are exempt because hoisted `function` declarations are genuinely
     * safe to reference earlier, and classes/type refs are not a pattern here.
     */
    'no-use-before-define': [
      'error',
      { functions: false, classes: false, variables: true, allowNamedExports: false },
    ],
  },
}
