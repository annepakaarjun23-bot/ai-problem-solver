/** @type {import('tailwindcss').Config} */
// One design system for the landing page and the chat application:
// ink/paper neutrals plus a single accent colour.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Helvetica Neue"', 'Helvetica', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        ink: '#0b0b0c',
        paper: '#ffffff',
        accent: {
          50: '#fff3ed',
          100: '#ffe1d3',
          500: '#f2541b',
          600: '#d9430f',
          700: '#b6360a',
        },
      },
      letterSpacing: { display: '-0.045em' },
      transitionTimingFunction: { out: 'cubic-bezier(0.22, 1, 0.36, 1)' },
    },
  },
  plugins: [],
};
