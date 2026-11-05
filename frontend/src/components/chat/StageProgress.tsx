"use client";

import { useEffect, useState } from "react";
import type { Stage } from "@/types";
import {
  type OptimisticStep,
  optimisticSteps,
  reconcileSteps,
} from "@/lib/stageProgress";

/**
 * The in-flight stage indicator, replacing the static three-dot spinner. While
 * the request is pending (no `stages` yet) it advances optimistically through
 * "Generating with X" -> "Reviewing with Y" on a short timer. Once the response
 * arrives with authoritative `stages`, it reconciles (dropping the review step
 * if no review ran) and marks completed steps.
 *
 * Client component: it owns a timer + local state and renders nothing on the
 * server beyond its hydrated markup.
 */

interface StageProgressProps {
  genLabel: string;
  reviewLabel: string;
  /** Authoritative stages once the response has arrived; undefined while pending. */
  stages?: Stage[];
  /** Advance interval for the optimistic steps (ms); kept short for the demo. */
  advanceMs?: number;
}

export default function StageProgress({
  genLabel,
  reviewLabel,
  stages,
  advanceMs = 1200,
}: StageProgressProps) {
  const settled = Boolean(stages);
  // While pending, show the full optimistic sequence (generate + review); once
  // the response arrives, reconcile against the authoritative stages (which may
  // drop the review step if no review ran).
  const optimistic = optimisticSteps(genLabel, reviewLabel);
  const steps: OptimisticStep[] = settled
    ? reconcileSteps(optimistic, stages)
    : optimistic;

  // How far the optimistic indicator has advanced. Once settled, every step is
  // shown as complete.
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (settled) return;
    if (activeIndex >= steps.length - 1) return;
    const timer = setTimeout(() => {
      setActiveIndex((i) => Math.min(i + 1, steps.length - 1));
    }, advanceMs);
    return () => clearTimeout(timer);
  }, [settled, activeIndex, steps.length, advanceMs]);

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
        <ul className="space-y-1.5">
          {steps.map((step, index) => {
            const done = settled || index < activeIndex;
            const active = !settled && index === activeIndex;
            return (
              <li
                key={step.stage}
                className="flex items-center gap-2 text-sm text-gray-600"
              >
                <span aria-hidden="true">
                  {done ? (
                    "✅"
                  ) : active ? (
                    <span className="inline-flex gap-1">
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" />
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.1s]" />
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
                    </span>
                  ) : (
                    "○"
                  )}
                </span>
                <span>{step.label}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
