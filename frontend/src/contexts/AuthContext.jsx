import React, { createContext, useState, useContext, useEffect } from 'react'
import api from '../lib/api'

const AuthContext = createContext(null)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

/** Return true if a JWT token string is expired (checks exp claim). */
function isTokenExpired(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return Date.now() >= payload.exp * 1000
  } catch {
    return true
  }
}

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const savedToken = localStorage.getItem('token')
    if (savedToken) {
      if (isTokenExpired(savedToken)) {
        _clearAuth()
        setLoading(false)
      } else {
        fetchCurrentUser(savedToken)
      }
    } else {
      setLoading(false)
    }
  }, [])

  function _clearAuth() {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
  }

  const fetchCurrentUser = async (authToken) => {
    try {
      const { data } = await api.get('/api/auth/me', {
        headers: { Authorization: `Bearer ${authToken || token}` },
      })
      setUser(data.user)
    } catch {
      _clearAuth()
    } finally {
      setLoading(false)
    }
  }

  const login = async (email, password) => {
    try {
      const { data } = await api.post('/api/auth/login', { email, password })
      localStorage.setItem('token', data.token)
      setToken(data.token)
      setUser(data.user)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.response?.data?.error || error.message }
    }
  }

  const signup = async (email, password, fullName) => {
    try {
      const { data } = await api.post('/api/auth/signup', {
        email,
        password,
        full_name: fullName,
      })
      localStorage.setItem('token', data.token)
      setToken(data.token)
      setUser(data.user)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.response?.data?.error || error.message }
    }
  }

  const logout = async () => {
    try {
      await api.post('/api/auth/logout')
    } catch {
      // ignore — clear local state regardless
    }
    _clearAuth()
  }

  const updateProfile = async (updates) => {
    try {
      const { data } = await api.put('/api/auth/me', updates)
      setUser(data.user)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.response?.data?.error || error.message }
    }
  }

  const value = {
    user,
    token,
    loading,
    login,
    signup,
    logout,
    updateProfile,
    isAuthenticated: !!user,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
