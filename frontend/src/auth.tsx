import * as React from "react";

import { api, ApiError, type User } from "@/api/client";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState | null>(null);

// Most globalny - pozwala zareagować na wygaśnięcie sesji spoza drzewa React
// (QueryCache.onError w main.tsx). Bez tego 401 z dowolnego zapytania był po cichu
// połykany: panel zostawał na ekranie z pustymi wykresami i zerami, a właściciel
// widział „wyzerowany biznes" zamiast prośby o ponowne zalogowanie.
let _wymusWylogowanie: (() => void) | null = null;
let _juzWygaslo = false;

/** Zgłasza wygaśnięcie sesji. Zwraca `true` tylko przy PIERWSZYM zgłoszeniu.
 *
 * Jedno wygaśnięcie daje tyle błędów 401, ile zapytań akurat leciało (Pulpit: 8),
 * a wołający nie ma jak ich odróżnić. Flagę zdejmuje udane logowanie.
 */
export function wygaslaSesja(): boolean {
  if (_juzWygaslo) return false;
  _juzWygaslo = true;
  _wymusWylogowanie?.();
  return true;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    _wymusWylogowanie = () => setUser(null);
    return () => {
      _wymusWylogowanie = null;
    };
  }, []);

  React.useEffect(() => {
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError)) console.error(e);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const u = await api.post<User>("/auth/login", { username, password });
    _juzWygaslo = false; // nowa sesja - kolejne wygaśnięcie ma znów dać komunikat
    setUser(u);
  };

  const logout = async () => {
    const r = await api.post<{ ok: boolean; redirect?: string }>("/auth/logout");
    setUser(null);
    // Przy logowaniu przez Cloudflare Access samo skasowanie naszej sesji nie wylogowuje -
    // brzeg nadal ma ważną sesję Google i przy następnym żądaniu wpuści z powrotem.
    // Backend oddaje wtedy adres wylogowania Cloudflare, na który trzeba przejść.
    if (r?.redirect) window.location.href = r.redirect;
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth poza AuthProvider");
  return ctx;
}
