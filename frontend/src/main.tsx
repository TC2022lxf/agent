import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { createApiClient } from './api/client'
import { ApiProvider } from './state/api-context'
import { AuthProvider } from './state/auth'
import { NavProvider } from './state/nav'
import { ToastProvider } from './state/toast'
import './styles/proto.css'
import './styles/image-studio.css'
import './styles/canvas.css'
import './styles/app-overrides.css'
import './styles/auth.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 0, retry: false } } })
const client = createApiClient()

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ApiProvider client={client}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <NavProvider>
            <ToastProvider>
              <App />
            </ToastProvider>
          </NavProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ApiProvider>
  </React.StrictMode>,
)

