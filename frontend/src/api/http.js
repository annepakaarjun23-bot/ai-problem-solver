// Thin fetch wrapper: bearer token in memory, transparent refresh via the HttpOnly cookie.

const BASE = '/api/v1';

let accessToken = null;
let refreshPromise = null;
let authLostHandler = null;
let refreshTimer = null;
let accessTokenExpiresAt = null;
let lastUserActivityAt = Date.now();
let activityTrackingStarted = false;

function noteUserActivity() {
  lastUserActivityAt = Date.now();
  if (accessToken && accessTokenExpiresAt && accessTokenExpiresAt - Date.now() <= 60_000) {
    refreshSession();
  }
}

function startActivityTracking() {
  if (activityTrackingStarted || typeof document === 'undefined') return;
  activityTrackingStarted = true;
  for (const eventName of ['pointerdown', 'keydown', 'touchstart', 'wheel']) {
    document.addEventListener(eventName, noteUserActivity, { passive: true });
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') noteUserActivity();
  });
}

export function setAccessToken(token, expiresInSeconds = 0) {
  accessToken = token;
  accessTokenExpiresAt = token && expiresInSeconds > 0 ? Date.now() + expiresInSeconds * 1000 : null;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  if (token && Number.isFinite(expiresInSeconds) && expiresInSeconds > 0) {
    startActivityTracking();
    // Refresh one minute before expiry so an expired token does not delay a user action.
    const delay = Math.max(1000, (expiresInSeconds - 60) * 1000);
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      if (Date.now() - lastUserActivityAt > 5 * 60 * 1000) return;
      // A background refresh must not log the user out on a transient network failure.
      // The normal 401 retry path will recover or clear the session when needed.
      refreshSession();
    }, delay);
  }
}

export function setAuthLostHandler(handler) {
  authLostHandler = handler;
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function detailFrom(body, status) {
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : '';
    const msg = String(first.msg || 'Invalid input').replace(/^Value error, /, '');
    return field && field !== 'body' ? `${field}: ${msg}` : msg;
  }
  return `Request failed (${status})`;
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession() {
  if (!refreshPromise) {
    const doRefresh = () => fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' });
    const refreshRequest =
      typeof navigator !== 'undefined' && navigator.locks?.request
        ? navigator.locks.request('ai-problem-solver-auth-refresh', doRefresh)
        : doRefresh();
    refreshPromise = refreshRequest
      .then(async (res) => {
        if (!res.ok) return null;
        const data = await res.json();
        setAccessToken(data.access_token, data.expires_in);
        return data;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/** Low-level fetch that returns the Response. Retries once after a token refresh on 401. */
export async function rawFetch(path, { method = 'GET', body, headers = {}, signal, retry = true } = {}) {
  const finalHeaders = { ...headers };
  if (accessToken) finalHeaders.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json';

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
    signal,
  });

  if (res.status === 401 && retry && !path.startsWith('/auth/')) {
    const refreshed = await refreshSession();
    if (refreshed) return rawFetch(path, { method, headers, body, signal, retry: false });
    if (authLostHandler) authLostHandler();
  }
  return res;
}

async function request(path, options) {
  const res = await rawFetch(path, options);
  if (res.status === 204) return null;
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new ApiError(res.status, detailFrom(body, res.status));
  return body;
}

export const api = {
  get: (path, options) => request(path, { ...options }),
  post: (path, body, options) => request(path, { method: 'POST', body, ...options }),
  patch: (path, body, options) => request(path, { method: 'PATCH', body, ...options }),
  del: (path, options) => request(path, { method: 'DELETE', ...options }),
};
