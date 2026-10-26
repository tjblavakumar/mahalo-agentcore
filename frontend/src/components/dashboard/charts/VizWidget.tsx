"use client";

import { Component, type ReactNode } from "react";
import type { VizSpec } from "@/types/viz";
import ChartRenderer from "./ChartRenderer";
import TableRenderer from "./TableRenderer";

/**
 * Lightweight per-widget error boundary so one malformed spec can't blank the
 * whole dashboard (design §8). Specs come from an LLM and a possibly-stale
 * stored item, so a render throw is contained to this card.
 */
class WidgetErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Widget render error:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full items-center justify-center p-4 text-center text-sm text-gray-400">
          Couldn&apos;t render this chart.
        </div>
      );
    }
    return this.props.children;
  }
}

interface VizWidgetProps {
  spec: VizSpec;
}

/** Given a validated VizSpec, pick the renderer. Shared by preview + card. */
export default function VizWidget({ spec }: VizWidgetProps) {
  return (
    <WidgetErrorBoundary>
      {spec.type === "table" ? <TableRenderer spec={spec} /> : <ChartRenderer spec={spec} />}
    </WidgetErrorBoundary>
  );
}
