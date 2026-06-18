/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0f0f0f',
        card: '#1a1a1a',
        'card-border': '#2a2a2a',
        accent: '#00d4aa',
        positive: '#00d4aa',
        negative: '#ff4444',
        'text-main': '#e5e5e5',
        'text-muted': '#888888',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
