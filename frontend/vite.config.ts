import { defineConfig } from 'vite'
import path from 'path'

export default defineConfig({
  build: {
    outDir: path.resolve(__dirname, '../backend/static/react'),
    emptyOutDir: true,
    sourcemap: false,
    lib: {
      entry: path.resolve(__dirname, 'src/main.tsx'),
      name: 'WalletWidget',
      fileName: () => 'wallet-widget.js',
      formats: ['iife']
    },
    rollupOptions: {
      external: [],
      output: {
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  },
  define: {
    // Many libs read this for feature flags; provide a literal string.
    'process.env.NODE_ENV': JSON.stringify('production'),
    // Some packages reference `global`; map to window in browser
    global: 'window'
  }
})