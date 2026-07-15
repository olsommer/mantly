import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from './components/ui/sonner.tsx'
import { I18nProvider } from './lib/i18n-provider'
import AdminApp from './App.tsx'
import './index.css'

createRoot(document.getElementById('admin-root')!).render(
  <StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <AdminApp />
        <Toaster />
      </I18nProvider>
    </BrowserRouter>
  </StrictMode>
)
