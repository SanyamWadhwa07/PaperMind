import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { auth as authApi, tokenStore } from '../lib/api'
import { invalidate } from '../lib/query'
import { startProcessingPoller, stopProcessingPoller } from '../lib/processingStore'

const AuthContext = createContext(null)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

/** True when a JWT is absent, malformed, or past its `exp` claim. */
function isTokenExpired(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return Date.now() >= payload.exp * 1000
  } catch {
    return true
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => tokenStore.get())
  const [loading, setLoading] = useState(true)

  const clearAuth = useCallback(() => {
    tokenStore.clear()
    setToken(null)
    setUser(null)
    // Every cached response was fetched as the outgoing user. The query cache
    // outlives the components that filled it, so without this the next person
    // to sign in on this browser would be served the previous one's library
    // from memory before any request went out.
    invalidate()
    stopProcessingPoller()
  }, [])

  useEffect(() => {
    const saved = tokenStore.get()

    // Check expiry locally first: a known-dead token should not cost a request.
    if (!saved || isTokenExpired(saved)) {
      clearAuth()
      setLoading(false)
      return
    }

    let cancelled = false
    authApi
      .me()
      .then((data) => {
        if (!cancelled) {
          setUser(data.user)
          startProcessingPoller()
        }
      })
      .catch(() => {
        if (!cancelled) clearAuth()
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [clearAuth])

  const applySession = useCallback((data) => {
    // Same reasoning as `clearAuth`, for the case where a session is replaced
    // without a logout in between.
    invalidate()
    tokenStore.set(data.token)
    setToken(data.token)
    setUser(data.user)
    startProcessingPoller()
  }, [])

  const login = useCallback(
    async (email, password) => {
      try {
        applySession(await authApi.login(email, password))
        return { success: true }
      } catch (error) {
        return { success: false, error: error.message }
      }
    },
    [applySession],
  )

  const signup = useCallback(
    async (email, password, fullName) => {
      try {
        applySession(await authApi.signup(email, password, fullName))
        return { success: true }
      } catch (error) {
        return { success: false, error: error.message }
      }
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // The server-side cookie may already be gone; local state clears regardless.
    }
    clearAuth()
  }, [clearAuth])

  const updateProfile = useCallback(async (updates) => {
    try {
      const data = await authApi.updateProfile(updates)
      setUser(data.user)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.message }
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      login,
      signup,
      logout,
      updateProfile,
      isAuthenticated: Boolean(user),
    }),
    [user, token, loading, login, signup, logout, updateProfile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
