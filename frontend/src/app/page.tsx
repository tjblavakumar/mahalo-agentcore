"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

export default function Home() {
  const router = useRouter();
  const { persona, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading) return;
    router.push(persona ? "/chat" : "/login");
  }, [persona, isLoading, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 w-full">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin mx-auto" />
        <p className="mt-3 text-gray-500 text-sm">Loading MAHALO3...</p>
      </div>
    </div>
  );
}
