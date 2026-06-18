import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import {
  api,
  setAccessToken,
  setUnauthorizedHandler,
  refreshAccessToken,
} from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // access token kept in memory only (never localStorage)
  const [token, setToken] = useState(null)
  const [role, setRole] = useState(null)
  // 'loading' until the initial refresh attempt resolves
  const [status, setStatus] = useState('loading')

  const applySession = useCallback((data) => {
    setAccessToken(data.access_token)
    setToken(data.access_token)
    setRole(data.role || null)
    setStatus('authenticated')
  }, [])

  const clearSession = useCallback(() => {
    setAccessToken(null)
    setToken(null)
    setRole(null)
    setStatus('unauthenticated')
  }, [])

  // On mount: try to restore the session via the httpOnly refresh cookie.
  useEffect(() => {
    let active = true
    ;(async () => {
      const data = await refreshAccessToken()
      if (!active) return
      if (data && data.access_token) {
        applySession(data)
      } else {
        clearSession()
      }
    })()
    return () => {
      active = false
    }
  }, [applySession, clearSession])

  // When the client gives up (2nd 401), drop the session.
  useEffect(() => {
    setUnauthorizedHandler(() => clearSession())
    return () => setUnauthorizedHandler(null)
  }, [clearSession])

  const login = useCallback(
    async (username, password) => {
      const data = await api.login(username, password)
      applySession(data)
      return data
    },
    [applySession]
  )

  const logout = useCallback(async () => {
    await api.logout()
    clearSession()
  }, [clearSession])

  const value = {
    token,
    role,
    status,
    isAuthenticated: status === 'authenticated',
    isLoading: status === 'loading',
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
