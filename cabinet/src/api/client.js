// API client for the Family Fund backend.
//
// Design:
//  - access_token lives in memory only (set via setAccessToken from AuthContext).
//  - refresh_token is an httpOnly cookie managed by the server; we always send
//    credentials so /auth/refresh works.
//  - On a 401 we transparently POST /auth/refresh ONCE, then replay the request.
//    A second 401 means the session is dead → onUnauthorized() (redirect to login).

const BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

let accessToken = null
let onUnauthorized = () => {}

// Single-flight refresh: concurrent 401s share one refresh promise.
let refreshPromise = null

export function setAccessToken(token) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function setUnauthorizedHandler(fn) {
  onUnauthorized = typeof fn === 'function' ? fn : () => {}
}

function url(path) {
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

async function parseBody(res) {
  const ct = res.headers.get('content-type') || ''
  if (res.status === 204) return null
  if (ct.includes('application/json')) {
    try {
      return await res.json()
    } catch {
      return null
    }
  }
  return await res.text()
}

class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function buildHeaders(extra = {}, hasBody = false) {
  const headers = { ...extra }
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`
  if (hasBody && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  return headers
}

// Refresh the access token via the httpOnly refresh cookie.
// Returns the new token, or null on failure. Single-flight.
export async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch(url('/auth/refresh'), {
          method: 'POST',
          credentials: 'include',
        })
        if (!res.ok) return null
        const data = await res.json()
        accessToken = data.access_token
        return data
      } catch {
        return null
      } finally {
        // Cleared after the awaiters below read it.
        setTimeout(() => {
          refreshPromise = null
        }, 0)
      }
    })()
  }
  return refreshPromise
}

// Core request with one transparent refresh-and-retry on 401.
async function request(path, { method = 'GET', body, headers, raw, _retried } = {}) {
  const isForm = body instanceof URLSearchParams || typeof body === 'string'
  const init = {
    method,
    credentials: 'include',
    headers: buildHeaders(headers, body != null && !isForm),
  }
  if (body != null) {
    init.body = isForm ? body : JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(url(path), init)
  } catch (err) {
    throw new ApiError(`Network error: ${err.message}`, 0, null)
  }

  if (res.status === 401 && !_retried && path !== '/auth/refresh' && path !== '/auth/login') {
    const refreshed = await refreshAccessToken()
    if (refreshed && refreshed.access_token) {
      return request(path, { method, body, headers, raw, _retried: true })
    }
    onUnauthorized()
    throw new ApiError('Unauthorized', 401, null)
  }

  const data = await parseBody(res)
  if (!res.ok) {
    const message =
      (data && data.error && data.error.message) ||
      (typeof data === 'string' && data) ||
      `Request failed (${res.status})`
    throw new ApiError(message, res.status, data)
  }
  return raw ? res : data
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),

  // OAuth2 password flow — backend expects x-www-form-urlencoded.
  async login(username, password) {
    const form = new URLSearchParams()
    form.set('username', username)
    form.set('password', password)
    const res = await fetch(url('/auth/login'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    })
    const data = await parseBody(res)
    if (!res.ok) {
      const message =
        (data && data.error && data.error.message) || 'Invalid credentials'
      throw new ApiError(message, res.status, data)
    }
    accessToken = data.access_token
    return data
  },

  async logout() {
    try {
      await request('/auth/logout', { method: 'POST' })
    } catch {
      // best-effort
    } finally {
      accessToken = null
    }
  },
}

export { ApiError }
