import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from './components/ui/sonner.tsx'
import { DemoProvider } from './hooks/use-demo.tsx'
import { OfficeProvider } from './hooks/use-office.tsx'
import { ProjectSelectionProvider } from './hooks/use-project-selection.tsx'

import './index.css'
import './lib/setup-prism.ts'
import App from './app.tsx'

const isEmbed = new URLSearchParams(window.location.search).has('embed');

async function ensureOfficeJs() {
  if (isEmbed || typeof Office !== 'undefined') {
    return;
  }

  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://appsforoffice.microsoft.com/lib/1/hosted/Office.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Office.js'));
    document.head.appendChild(script);
  });
}

async function bootstrap() {
  try {
    await ensureOfficeJs();
  } catch (error) {
    console.error(error);
  }

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <DemoProvider>
        <OfficeProvider>
          <ProjectSelectionProvider>
            <MemoryRouter initialEntries={isEmbed ? ['/embed'] : ['/']}>
              <App />
              <Toaster />
            </MemoryRouter>
          </ProjectSelectionProvider>
        </OfficeProvider>
      </DemoProvider>
    </StrictMode>
  )
}

void bootstrap();
