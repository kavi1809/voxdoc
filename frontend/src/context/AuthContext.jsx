import { createContext, useContext, useEffect, useState } from 'react'
import * as apiClient from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // On first load, validate any stored token against the server. A token can be
  // present but expired, so trusting localStorage alone would show a logged-in
  // shell that then 401s on every request.
  useEffect(() => {
    if (!apiClient.getToken()) {
      setLoading(false)
      return
    }
    apiClient
      .fetchMe()
      .then(setUser)
      .catch(() => apiClient.clearToken())
      .finally(() => setLoading(false))
  }, [])

  const handleAuth = (data) => {
    apiClient.setToken(data.access_token)
    setUser({ id: data.user_id, username: data.username })
  }

  const value = {
    user,
    loading,
    login: async (u, p) => handleAuth(await apiClient.login(u, p)),
    register: async (u, p) => handleAuth(await apiClient.register(u, p)),
    logout: () => {
      apiClient.clearToken()
      setUser(null)
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
