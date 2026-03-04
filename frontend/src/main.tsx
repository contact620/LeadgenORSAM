import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    <Toaster
      theme="dark"
      position="bottom-right"
      toastOptions={{
        style: {
          background: 'rgba(15, 20, 35, 0.95)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: '#e2e8f8',
        },
      }}
    />
  </StrictMode>,
)
