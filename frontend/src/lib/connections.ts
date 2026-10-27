/**
 * Static "all connected" services for the presentational Connections screen.
 *
 * Demo posture: the four services the agent synthesizes across are shown as
 * connected. No backend/CRUD — the Connections page maps over this constant.
 */

export interface ServiceInfo {
  key: "jira" | "confluence" | "github" | "servicenow";
  label: string;
  icon: string; // emoji, ported from the mahalo-dock integration table
  description: string; // short line under the service name
  url?: string; // optional click-through to the live system (opens in a new tab)
}

export const SERVICES: ServiceInfo[] = [
  { key: "jira", label: "Jira", icon: "📋", description: "Issues, sprints & boards" },
  { key: "confluence", label: "Confluence", icon: "📄", description: "Docs & knowledge base" },
  {
    key: "github",
    label: "GitHub",
    icon: "🐙",
    description: "Repos, PRs & commits",
    url: "https://d3ec76atxiij9a.cloudfront.net/",
  },
  { key: "servicenow", label: "ServiceNow", icon: "🛠️", description: "Incidents & change mgmt" },
];
