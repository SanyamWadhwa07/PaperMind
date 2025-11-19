/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          light: '#00988F',
          dark: '#00A7A0',
          hover: '#008F89',
        },
        accent: {
          light: '#C4935F',
          dark: '#D9A86C',
        },
        background: {
          light: '#F9FBFA',
          dark: '#111312',
        },
        card: {
          light: '#EEF4F3',
          dark: '#1E2020',
        },
        text: {
          primary: '#F5F5F5',
          dim: '#8F8F8F',
          light: '#1B1B1B',
        },
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
}
