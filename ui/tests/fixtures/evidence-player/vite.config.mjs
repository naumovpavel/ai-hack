import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
export default defineConfig({
  root: import.meta.dirname,
  define: {
    'process.env.NEXT_PUBLIC_API_BASE_URL': JSON.stringify(
      'http://127.0.0.1:4319',
    ),
  },
  plugins: [react()],
  resolve: { alias: { '@': new URL('../../../', import.meta.url).pathname } },
  css: { postcss: { plugins: [tailwindcss()] } },
  server: {
    host: '127.0.0.1',
    port: 4319,
    strictPort: true,
    fs: { allow: [new URL('../../../', import.meta.url).pathname] },
  },
});
