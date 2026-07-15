import path from "path"
import { readFileSync } from "fs"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const brand: unknown = JSON.parse(readFileSync(path.resolve(__dirname, "../brand.json"), "utf-8"))

// https://vite.dev/config/
export default defineConfig({
  base: process.env.VITE_ADDIN_BASE_PATH || '/addin/',
  define: {
    __APP_BRAND__: JSON.stringify(brand),
  },
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@demo": path.resolve(__dirname, "../demo"),
    },
  },
})
