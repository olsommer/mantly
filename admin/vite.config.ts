import path from "path"
import { readFileSync } from "fs"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const brand: unknown = JSON.parse(readFileSync(path.resolve(__dirname, "../brand.json"), "utf-8"))

// https://vite.dev/config/
export default defineConfig({
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
  build: {
    // Use "_app" instead of the default "assets" to avoid colliding with
    // the /assets/ mount used for Outlook-manifest icon files when the
    // backend serves the admin SPA at /.
    assetsDir: '_app',
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          const normalized = id.replace(/\\/g, '/')
          const marker = '/node_modules/'
          if (!normalized.includes(marker)) return undefined

          const modulePath = normalized.split(marker)[1] ?? ''
          const [scopeOrName, subName] = modulePath.split('/')
          const pkg = scopeOrName.startsWith('@') ? `${scopeOrName}/${subName}` : scopeOrName

          if (pkg === 'react' || pkg === 'react-dom' || pkg === 'scheduler') return 'vendor-react'
          if (pkg === 'react-router' || pkg === 'react-router-dom') return 'vendor-router'
          if (pkg === 'axios') return 'vendor-http'
          if (pkg === 'yaml') return 'vendor-yaml'
          if (pkg.startsWith('@dnd-kit/')) return 'vendor-dnd'
          if (pkg.startsWith('@tanstack/')) return 'vendor-table'
          if (
            pkg === 'recharts' ||
            pkg === 'victory-vendor' ||
            pkg.startsWith('d3-') ||
            pkg === 'decimal.js-light'
          ) {
            return 'vendor-charts'
          }
          if (
            pkg.startsWith('@radix-ui/') ||
            pkg === 'radix-ui' ||
            pkg === 'lucide-react' ||
            pkg === 'class-variance-authority' ||
            pkg === 'tailwind-merge' ||
            pkg === 'clsx' ||
            pkg === 'sonner'
          ) {
            return 'vendor-ui'
          }
          return 'vendor'
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@demo": path.resolve(__dirname, "../demo"),
    },
  },
})
