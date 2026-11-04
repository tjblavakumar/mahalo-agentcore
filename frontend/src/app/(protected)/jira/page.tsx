import { Suspense } from "react";
import JiraShell from "@/components/jira/JiraShell";

// useSearchParams (deep links like /jira?project=CART&story=CART-205) requires a
// Suspense boundary so the rest of the page can still be prerendered.
export default function JiraPage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-500">Loading MahaloJira…</div>}>
      <JiraShell />
    </Suspense>
  );
}
