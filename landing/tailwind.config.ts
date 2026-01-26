import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          900: '#0c1222'
        },
        brand: {
          500: '#6d5efc',
          600: '#5a4cf4'
        },
        accent: {
          500: '#ff8f1f'
        }
      },
      boxShadow: {
        soft: '0 20px 60px rgba(15, 23, 42, 0.18)'
      }
    }
  },
  plugins: []
};

export default config;
