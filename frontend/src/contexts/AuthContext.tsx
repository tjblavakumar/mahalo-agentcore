"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { authenticate, PERSONAS, type Persona, type PersonaId } from "@/lib/personas";

const STORAGE_KEY = "mahalo_persona";

interface AuthContextType {
  persona: Persona | null;
  isLoading: boolean;
  /** Pure client-side credential check. Returns an error string or null on success. */
  login: (userid: string, password: string) => string | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore any existing persona from sessionStorage (reload-survival only;
  // React state is the in-memory source of truth). Deferred to a microtask so
  // the setState calls do not run synchronously in the effect body.
  const restoreSession = useCallback(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY) as PersonaId | null;
    if (stored && PERSONAS[stored]) {
      setPersona(PERSONAS[stored]);
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      restoreSession();
    });
  }, [restoreSession]);

  const login = useCallback((userid: string, password: string): string | null => {
    const match = authenticate(userid, password);
    if (!match) {
      return "Invalid credentials";
    }
    sessionStorage.setItem(STORAGE_KEY, match.personaId);
    setPersona(match);
    return null;
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setPersona(null);
  }, []);

  return (
    <AuthContext.Provider value={{ persona, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
