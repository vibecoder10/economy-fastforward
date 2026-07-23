"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { AuthUser, getMe, googleLogin, registerUser, loginUser } from "@/lib/api";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  login: (credential: string) => Promise<void>;
  loginWithEmail: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    displayName?: string,
    betaCode?: string
  ) => Promise<{ betaApplied: boolean }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  isLoading: true,
  login: async () => {},
  loginWithEmail: async () => {},
  register: async () => ({ betaApplied: false }),
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, check for existing token
  useEffect(() => {
    let token = localStorage.getItem("token");
    // Local-only auth seed so `npm run dev` can reach authed pages for UI
    // verification before a deploy. Double-gated: dead in prod builds
    // (NODE_ENV) and inert unless NEXT_PUBLIC_DEV_TOKEN is set in .env.local
    // (gitignored). Refresh the token with `se.sh devtoken`.
    if (
      (!token || token === "dev-token") &&
      process.env.NODE_ENV === "development" &&
      process.env.NEXT_PUBLIC_DEV_TOKEN
    ) {
      token = process.env.NEXT_PUBLIC_DEV_TOKEN;
      localStorage.setItem("token", token);
    }
    if (!token || token === "dev-token") {
      setIsLoading(false);
      return;
    }
    getMe()
      .then((u) => setUser(u))
      .catch(() => {
        // Token expired or invalid — clear it
        localStorage.removeItem("token");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (credential: string) => {
    const res = await googleLogin(credential);
    localStorage.setItem("token", res.token);
    setUser(res.user);
  }, []);

  const loginWithEmail = useCallback(async (email: string, password: string) => {
    const res = await loginUser(email, password);
    localStorage.setItem("token", res.token);
    setUser(res.user);
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName?: string, betaCode?: string) => {
      const res = await registerUser(email, password, displayName || "", betaCode);
      localStorage.setItem("token", res.token);
      setUser(res.user);
      return { betaApplied: !!res.beta_applied };
    },
    []
  );

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, loginWithEmail, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
