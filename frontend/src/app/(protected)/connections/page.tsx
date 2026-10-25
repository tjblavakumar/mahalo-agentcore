"use client";

import { useAuth } from "@/contexts/AuthContext";
import { SERVICES } from "@/lib/connections";

export default function ConnectionsPage() {
  const { persona } = useAuth();

  return (
    <div className="p-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Connections</h1>
        <p className="mt-1 text-gray-600">
          The services the agent synthesizes across
          {persona ? ` for ${persona.personaLabel}` : ""}.
        </p>
      </div>

      <div className="mt-6 space-y-3 max-w-2xl">
        {SERVICES.map((service) => (
          <div
            key={service.key}
            className="bg-white rounded-lg shadow p-5 flex items-center justify-between"
          >
            <div className="flex items-center gap-4">
              <span className="text-3xl">{service.icon}</span>
              <div>
                <p className="font-medium text-gray-900">{service.label}</p>
                <p className="text-sm text-gray-500">{service.description}</p>
              </div>
            </div>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-green-50 text-green-700 border border-green-200 rounded-full text-xs font-medium">
              <span className="w-2 h-2 bg-green-500 rounded-full" />
              Connected
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
