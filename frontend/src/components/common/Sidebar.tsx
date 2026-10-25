"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

const NAVIGATION = [
  { name: "Dashboard", href: "/dashboard", icon: "📊" },
  { name: "Chat", href: "/chat", icon: "💬" },
  { name: "Connections", href: "/connections", icon: "🔗" },
];

export default function Sidebar() {
  const { persona, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  function handleSignOut() {
    logout();
    router.push("/login");
  }

  return (
    <aside className="w-64 bg-gray-900 text-white flex flex-col min-h-screen">
      {/* Logo */}
      <div className="p-6 border-b border-gray-700">
        <h1 className="text-xl font-bold tracking-wide">MAHALO3</h1>
        <p className="text-xs text-gray-400">AI-Powered SDLC Platform</p>
      </div>

      {/* User */}
      <div className="p-4 border-b border-gray-700">
        {persona ? (
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-sm font-semibold shrink-0">
                {persona.displayName.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{persona.displayName}</p>
                <p className="text-xs text-gray-400 truncate">{persona.personaLabel}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleSignOut}
              className="text-xs text-gray-300 hover:text-white hover:underline shrink-0"
            >
              Sign out
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-400">Not signed in</p>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {NAVIGATION.map((item) => {
          const isActive = pathname?.startsWith(item.href) ?? false;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <span className="text-base">{item.icon}</span>
              <span>{item.name}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
