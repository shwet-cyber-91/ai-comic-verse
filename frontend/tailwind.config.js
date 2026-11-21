/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0b0b10',
          900: '#12121a',
          850: '#181822',
          800: '#1e1e2a',
          700: '#2b2b3a',
          600: '#3d3d50',
        },
        accent: {
          DEFAULT: '#f2b23e',
          soft: '#ffd479',
          deep: '#c8871d',
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
