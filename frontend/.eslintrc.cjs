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
  },
}
