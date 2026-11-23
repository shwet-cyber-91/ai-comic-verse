/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#080a12',
          900: '#10131f',
          850: '#171b2b',
          800: '#20253a',
          700: '#30364f',
          600: '#454b67',
        },
        accent: {
          DEFAULT: '#8b7cf6',
          soft: '#b6adff',
          deep: '#6857db',
        },
        panel: '#f6f3ec',
      },
      fontFamily: {
        display: ['"Bangers"', '"Trebuchet MS"', 'system-ui', 'sans-serif'],
        body: ['ui-sans-serif', 'system-ui', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        comic: '0 18px 44px rgba(0,0,0,.55)',
        inset: 'inset 0 0 0 1px rgba(255,255,255,.06)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-500px 0' },
          '100%': { backgroundPosition: '500px 0' },
        },
      },
      animation: {
        'fade-up': 'fade-up .35s ease-out both',
        shimmer: 'shimmer 1.4s linear infinite',
      },
    },
  },
  plugins: [],
}
