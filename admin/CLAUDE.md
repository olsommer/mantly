# CLAUDE.md — mantly admin

## Project overview

Standalone React SPA for managing the Mantly backend: intents,
identity tools, and organisation settings. Runs separately from the Outlook
add-in frontend. No Office.js dependency.

## Tech stack

- **Framework:** React 19, TypeScript 5.9 (strict)
- **Build:** Vite 7 (rolldown-vite), Babel React Compiler
- **Styling:** Tailwind CSS 4, shadcn/ui (Radix UI primitives), Lucide icons, CVA
- **HTTP:** Axios
- **Routing:** React Router 7 with BrowserRouter

## Commands

```bash
npm run dev      # Vite dev server on :5174
npm run build    # tsc -b && vite build → dist/
npm run lint     # ESLint
npm run preview  # Preview production build
```

## Verification (run after every change)

Run `npm run lint` after any admin change. See root CLAUDE.md for the full cross-project checklist.

## Project structure

```
src/
├── main.tsx           # Entry: StrictMode > BrowserRouter > AdminApp + Toaster
├── App.tsx            # Tab-based shell (Intents / Tools / Config)
├── index.css          # Tailwind v4 + CSS custom properties (oklch)
├── settings.tsx       # API URL config — reads VITE_API_URL, defaults to localhost:8080
├── api/
│   ├── client.ts      # Axios-based ApiClient singleton
│   └── endpoints.ts   # Admin-only endpoints (/api/admin/*)
├── routes/
│   ├── Intents.tsx    # CRUD for intent definitions (YAML frontmatter + markdown)
│   ├── Tools.tsx      # CRUD for identity tool definitions (JSON)
│   └── Config.tsx     # Org name, description, LLM model
├── lib/
│   └── utils.ts       # cn() helper (clsx + tailwind-merge)
└── components/
    └── ui/            # shadcn/ui primitives (button, input, textarea, label, badge, separator, sonner)
```

## Environment

```env
VITE_API_URL=http://localhost:8080
```

In development the API URL defaults to `http://localhost:8080` automatically.
Set `VITE_API_URL` for production deployments.

## Conventions

- All imports use `@/` alias (maps to `src/`)
- Components: named exports
- No Office.js, no mock mode, no demo data
