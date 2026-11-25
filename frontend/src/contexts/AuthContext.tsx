"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { authenticate, PERSONAS, type Persona, type PersonaId } from "@/lib/personas";
import { BRIEFING_STATE_KEY, LOGIN_ID_KEY, newLoginId } from "@/lib/briefing";

const STORAGE_KEY = "mahalo_persona";

interface AuthContextType {
  persona: Persona | null;
  /** Random id written by each explicit login(); null for a session restored from before it existed. */
  loginId: string | null;
  isLoading: boolean;
  /** Pure client-side credential check. Returns an error string or null on success. */
  login: (userid: string, password: string) => string | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loginId, setLoginId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore any existing persona from localStorage (shared across tabs and
  // reload-survival; React state is the in-memory source of truth). Deferred to
  // a microtask so the setState calls do not run synchronously in the effect body.
  const restoreSession = useCallback(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as PersonaId | null;
    if (stored && PERSONAS[stored]) {
      setPersona(PERSONAS[stored]);
      setLoginId(localStorage.getItem(LOGIN_ID_KEY));
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
    const id = newLoginId();
    localStorage.setItem(STORAGE_KEY, match.personaId);
    localStorage.setItem(LOGIN_ID_KEY, id);
    setPersona(match);
    setLoginId(id);
    return null;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(LOGIN_ID_KEY);
    localStorage.removeItem(BRIEFING_STATE_KEY);
    setPersona(null);
    setLoginId(null);
  }, []);

  return (
    <AuthContext.Provider value={{ persona, loginId, isLoading, login, logout }}>
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
