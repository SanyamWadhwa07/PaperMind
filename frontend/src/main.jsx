import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App.jsx'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { ToastProvider } from './contexts/ToastContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
          {/* Toasts inherit the theme through CSS variables rather than being
              re-styled per theme. */}
          <Toaster
            position="top-right"
            toastOptions={{
              duration: 4000,
              style: {
                background: 'rgb(var(--surface))',
                color: 'rgb(var(--ink))',
                border: '1px solid rgb(var(--border))',
                fontSize: '0.875rem',
                boxShadow: 'var(--shadow-lg)',
              },
              success: { iconTheme: { primary: 'rgb(var(--accent))', secondary: 'rgb(var(--surface))' } },
              error: { iconTheme: { primary: 'rgb(var(--danger))', secondary: 'rgb(var(--surface))' } },
            }}
          />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
