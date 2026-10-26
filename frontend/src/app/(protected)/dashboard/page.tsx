"use client";

import { useAuth } from "@/contexts/AuthContext";
import CustomDashboard from "@/components/dashboard/CustomDashboard";

export default function DashboardPage() {
  const { persona } = useAuth();

  if (!persona) {
    return null;
  }

  return <CustomDashboard persona={persona} />;
}
