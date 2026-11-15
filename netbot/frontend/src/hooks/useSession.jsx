import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createApi } from "../../modules/api.mjs";

const defaultFetch = (...args) => fetch(...args);
export function useSession({
  fetcher = defaultFetch,
  storage = localStorage,
} = {}) {
  const state = useRef({ user: null, session: 0 }).current;
  const [user, setUser] = useState(null),
    [screen, setScreen] = useState("guest");
  const [message, setMessage] = useState("");
  const attempt = useRef(0),
    expireRef = useRef(() => {}),
    mounted = useRef(true);
  const api = useMemo(
    () =>
      createApi({
        fetch: fetcher,
        localStorage: storage,
        state,
        baseUrl: "",
        onSessionExpired: () => expireRef.current(),
      }),
    [state, fetcher, storage],
  );
  const signOut = useCallback(
    (notice = "", expired = false) => {
      const tokens = api.getStoredTokens();
      attempt.current++;
      state.session++;
      state.user = null;
      api.clearTokens();
      setUser(null);
      setMessage(notice);
      setScreen(expired ? "login" : "guest");
      if (tokens?.refresh_token)
        api
          .apiRequest("/auth/logout", {
            method: "POST",
            body: JSON.stringify({ refresh_token: tokens.refresh_token }),
          })
          .catch(() => {});
    },
    [api, state],
  );
  expireRef.current = () =>
    signOut("Tu sesión expiró. Inicia sesión nuevamente.", true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      attempt.current++;
      state.session++;
      state.user = null;
      api.clearTokens();
    };
  }, [api, state]);
  useEffect(() => {
    if (!user) return;
    let timer;
    const check = () => {
      clearTimeout(timer);
      const encoded = api.getStoredTokens()?.access_token?.split(".")[1];
      try {
        const exp = JSON.parse(
          atob(encoded.replace(/-/g, "+").replace(/_/g, "/")),
        ).exp;
        if (!Number.isFinite(exp)) return;
        const remaining = exp * 1000 - Date.now();
        if (remaining <= 0) {
          expireRef.current();
          return;
        }
        timer = setTimeout(check, Math.min(remaining, 2147483647));
      } catch {
        /* El servidor sigue validando firma y sesión. */
      }
    };
    check();
    document.addEventListener("visibilitychange", check);
    window.addEventListener("pageshow", check);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("pageshow", check);
    };
  }, [user, api]);
  const login = useCallback(
    async (email, password) => {
      const currentAttempt = ++attempt.current,
        epoch = state.session;
      const current = () =>
        mounted.current &&
        currentAttempt === attempt.current &&
        epoch === state.session;
      const tokens = await api.apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      if (!current()) return;
      const person = await api.apiRequest("/auth/me", {}, tokens.access_token);
      if (!current()) return;
      api.setTokens(tokens);
      state.session++;
      state.user = person;
      setMessage("");
      setUser(person);
    },
    [api, state],
  );
  const openScreen = useCallback((next) => {
    attempt.current++;
    setMessage("");
    setScreen(next);
  }, []);
  return { api, state, user, screen, message, login, signOut, openScreen };
}
