import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, refreshSession, setAccessToken, setAuthLostHandler } from '../api/http';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authenticated | anonymous

  const applySession = useCallback((data) => {
    setAccessToken(data.access_token, data.expires_in);
    setUser(data.user);
    setStatus('authenticated');
  }, []);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus('anonymous');
  }, []);

  // On first load, try to restore the session from the refresh cookie.
  useEffect(() => {
    let active = true;
    refreshSession().then((data) => {
      if (!active) return;
      if (data) applySession(data);
      else clearSession();
    });
    return () => {
      active = false;
    };
  }, [applySession, clearSession]);

  // If a refresh fails mid-session, drop back to the login screen.
  useEffect(() => {
    setAuthLostHandler(clearSession);
    return () => setAuthLostHandler(null);
  }, [clearSession]);

  const login = useCallback(
    async (email, password) => applySession(await api.post('/auth/login', { email, password })),
    [applySession],
  );

  const signup = useCallback(
    async (email, password) => applySession(await api.post('/auth/signup', { email, password })),
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* the local session is cleared either way */
    }
    clearSession();
  }, [clearSession]);

  const value = useMemo(
    () => ({ user, status, login, signup, logout }),
    [user, status, login, signup, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
