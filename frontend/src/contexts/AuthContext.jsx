import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { auth as authApi, tokenStore } from '../lib/api'

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
        if (!cancelled) setUser(data.user)
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
    tokenStore.set(data.token)
    setToken(data.token)
    setUser(data.user)
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
