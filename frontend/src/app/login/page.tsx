"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { PERSONAS, type PersonaId } from "@/lib/personas";

export default function LoginPage() {
  const [userid, setUserid] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  function submit(uid: string, pwd: string) {
    setError(null);
    setIsSubmitting(true);
    const err = login(uid, pwd);
    if (err) {
      setError(err);
      setIsSubmitting(false);
    } else {
      router.push("/chat");
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(userid, password);
  }

  // Demo affordance: prefill + submit one of the three hardcoded personas.
  function quickLogin(personaId: PersonaId) {
    const p = PERSONAS[personaId];
    setUserid(p.userid);
    setPassword(p.password);
    submit(p.userid, p.password);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 w-full">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-lg shadow-lg p-8">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-gray-900">MAHALO3</h1>
            <p className="text-gray-500 mt-2">Sign in as a persona</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <div>
              <label htmlFor="userid" className="block text-sm font-medium text-gray-700 mb-1">
                User ID
              </label>
              <input
                id="userid"
                type="text"
                value={userid}
                onChange={(e) => setUserid(e.target.value)}
                required
                autoComplete="username"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors text-gray-900"
                placeholder="pm / dev / exec"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors text-gray-900"
                placeholder="Enter your password"
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div className="mt-6">
            <p className="text-center text-xs text-gray-400 mb-3">Quick login (demo)</p>
            <div className="grid grid-cols-3 gap-2">
              {(Object.values(PERSONAS)).map((p) => (
                <button
                  key={p.personaId}
                  type="button"
                  onClick={() => quickLogin(p.personaId)}
                  disabled={isSubmitting}
                  className="px-2 py-2 border border-gray-200 rounded-lg text-xs text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors disabled:opacity-50"
                >
                  {p.personaLabel}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
