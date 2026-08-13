import { createContext, useContext } from 'react'
import toast, { Toaster } from 'react-hot-toast'

const ToastContext = createContext()

export const useToast = () => {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used within ToastProvider')
  return context
}

const TOAST_OPTS = {
  position: 'top-right',
  style: { fontSize: '14px' },
}

export function ToastProvider({ children }) {
  const showToast = {
    success: (message) => toast.success(message, { ...TOAST_OPTS, duration: 3000 }),
    error:   (message) => toast.error(message,   { ...TOAST_OPTS, duration: 4000 }),
    info:    (message) => toast(message,          { ...TOAST_OPTS, duration: 3000, icon: 'ℹ️' }),
    warning: (message) => toast(message,          { ...TOAST_OPTS, duration: 3000, icon: '⚠️' }),
    promise: (promise, messages) =>
      toast.promise(promise, {
        loading: messages.pending || 'Processing...',
        success: messages.success || 'Success!',
        error:   messages.error   || 'Something went wrong',
      }, TOAST_OPTS),
  }

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      {/* Toasts follow the theme: react-hot-toast takes concrete CSS values, so
          these read the same custom properties every component does. */}
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            fontSize: '14px',
            background: 'rgb(var(--surface))',
            color: 'rgb(var(--ink))',
            border: '1px solid rgb(var(--border))',
            borderRadius: 'var(--radius)',
            boxShadow: 'var(--shadow-md)',
          },
          success: { iconTheme: { primary: 'rgb(var(--success))', secondary: 'rgb(var(--surface))' } },
          error: { iconTheme: { primary: 'rgb(var(--danger))', secondary: 'rgb(var(--surface))' } },
        }}
      />
    </ToastContext.Provider>
  )
}
