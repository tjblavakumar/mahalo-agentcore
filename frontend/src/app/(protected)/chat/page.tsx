"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { buildSuggestions } from "@/lib/chatSuggestions";
import { api, checkSkill, getModelConfig, listSkills, runSkill } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import type {
  Proposal,
  ChatResponse,
  ActionResult,
  Stage,
  ReviewSummary,
} from "@/types";
import {
  CODE_GEN_OPTION,
  DEFAULT_REVIEW_OPTION,
  modelLabel,
} from "@/lib/modelConfig";
import ChatInput from "@/components/chat/ChatInput";
import ChatMessage from "@/components/chat/ChatMessage";
import StageProgress from "@/components/chat/StageProgress";
import ProposalCard from "@/components/chat/ProposalCard";
import ContextPanel from "@/components/chat/ContextPanel";
import SkillCheckCard, { type SkillCardState } from "@/components/chat/SkillCheckCard";
import SkillRunStatus from "@/components/chat/SkillRunStatus";
import SkillLibraryPanel from "@/components/chat/SkillLibraryPanel";
import type { SkillFileBlock } from "@/lib/skills/chatBlock";
import { getSkill } from "@/services/api";
import type { SkillCheck, SkillRunInfo, SkillSummary } from "@/lib/skills/types";
import {
  describeCheckError,
  describeFailure,
  formatRunSummary,
  type SkillFailure,
} from "@/lib/skills/ui";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  systemsQueried?: string[];
  proposal?: Proposal | null;
  stages?: Stage[];
  review?: ReviewSummary;
  /** Chip text of a "/" skill command (user bubble). The skill body is never shown. */
  skillCommand?: string;
  /** A skill check card. */
  skillCard?: SkillCard;
  /** Transient "skill is running" status line. */
  skillRunning?: { command: string; project: string; systems: string[] };
  /** Summary line under a skill answer. */
  skillRunInfo?: SkillRunInfo;
}

interface SkillCard {
  command: string;
  project: string | null;
  check: SkillCheck | null;
  sha: string | null;
  state: SkillCardState;
  failure?: SkillFailure;
  content?: string | null;
}

interface CardResult {
  success: boolean;
  message: string;
}

export default function ChatPage() {
  const router = useRouter();
  const { persona, logout } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [reviewLabel, setReviewLabel] = useState(DEFAULT_REVIEW_OPTION.label);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [actionResults, setActionResults] = useState<Record<string, CardResult>>({});
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [skillsFailed, setSkillsFailed] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // A skill drafted in chat; the key remounts the panel so a new draft replaces the old one.
  const [skillDraft, setSkillDraft] = useState<{ block: SkillFileBlock; key: number } | null>(null);
  const [contextPanel, setContextPanel] = useState<{
    isOpen: boolean;
    title: string;
    content: string;
    type: "story" | "document" | "pr";
  }>({ isOpen: false, title: "", content: "", type: "story" });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageIdRef = useRef(0);

  // Generates a stable, unique message id without calling impure functions
  // (like Date.now()) during render. The counter lives in a ref and is only
  // advanced from event handlers.
  const nextMessageId = useCallback((suffix?: string) => {
    messageIdRef.current += 1;
    return suffix ? `msg-${messageIdRef.current}-${suffix}` : `msg-${messageIdRef.current}`;
  }, []);

  // Starter prompts for the logged-in persona (GitHub + Jira connected, no
  // scoped project). The thin API has no suggestions/connections backend, so the
  // context is static rather than live; only the role tracks the persona.
  const templateSuggestions = useMemo(
    () =>
      buildSuggestions({
        role: persona?.role ?? "developer",
        project: null,
        connectedTypes: ["github", "jira"],
      }),
    [persona?.role]
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load the persona's configured review model so the optimistic "Reviewing
  // with X" label matches what the server will actually use. On any error we
  // keep the default label (the server also falls back to the default model).
  useEffect(() => {
    let active = true;
    getModelConfig(persona?.personaId).then((res) => {
      if (!active) return;
      if (res.data?.codeReview) {
        setReviewLabel(modelLabel(res.data.codeReview));
      }
    });
    return () => {
      active = false;
    };
  }, [persona?.personaId]);

  const refreshSkills = useCallback(async () => {
    const res = await listSkills(persona?.personaId);
    if (res.data) {
      setSkills(res.data.skills);
      setSkillsFailed(false);
    } else {
      setSkillsFailed(true);
    }
  }, [persona?.personaId]);

  // Load the skill library once per persona.
  useEffect(() => {
    let active = true;
    listSkills(persona?.personaId).then((res) => {
      if (!active) return;
      if (res.data) {
        setSkills(res.data.skills);
        setSkillsFailed(false);
      } else {
        setSkillsFailed(true);
      }
    });
    return () => {
      active = false;
    };
  }, [persona?.personaId]);

  function updateCard(id: string, patch: Partial<SkillCard>) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id && m.skillCard ? { ...m, skillCard: { ...m.skillCard, ...patch } } : m))
    );
  }

  function dropSkill(name: string) {
    setSkills((prev) => prev.filter((s) => s.name !== name));
  }

  async function runCheck(name: string, project: string | null) {
    setIsLoading(true);
    const cardId = nextMessageId("check");
    const res = await checkSkill({ name, project, session_id: sessionId }, persona?.personaId);
    let card: SkillCard;
    if (res.data?.skill_check) {
      card = {
        command: name,
        project: res.data.project ?? project,
        check: res.data.skill_check,
        sha: res.data.skill?.content_sha256 ?? null,
        state: "ready",
      };
    } else {
      const failure = res.data?.error
        ? describeCheckError(res.data.error)
        : describeFailure("check", res, false);
      if (failure.removeSkill) dropSkill(name);
      card = { command: name, project, check: null, sha: null, state: "error", failure };
    }
    setMessages((prev) => [
      ...prev,
      { id: cardId, role: "assistant", content: "", skillCard: card },
    ]);
    setIsLoading(false);
  }

  async function handleSkillCommand(name: string, project: string | null) {
    const chip = project ? `/${name} ${project}` : `/${name}`;
    setMessages((prev) => [
      ...prev,
      { id: nextMessageId(), role: "user", content: "", skillCommand: chip },
    ]);
    await runCheck(name, project);
  }

  function handleCheckAgain(msg: Message, project: string | null) {
    const card = msg.skillCard;
    if (!card) return;
    // The old card stays as history; its retry control is used up.
    updateCard(msg.id, {
      failure: card.failure ? { ...card.failure, control: null } : card.failure,
    });
    return runCheck(card.command, project);
  }

  function handleCancelSkill(msg: Message) {
    updateCard(msg.id, { state: "cancelled" });
  }

  async function handleViewSkill(msg: Message) {
    const card = msg.skillCard;
    if (!card || card.content) return;
    const res = await getSkill(card.command, persona?.personaId);
    updateCard(msg.id, { content: res.data ? res.data.content : "The skill could not be loaded." });
  }

  async function handleRunSkill(msg: Message, project: string) {
    const card = msg.skillCard;
    if (!card || !card.sha) return;
    updateCard(msg.id, { state: "accepted", project, failure: undefined });
    const runId = nextMessageId("running");
    setMessages((prev) => [
      ...prev,
      {
        id: runId,
        role: "assistant",
        content: "",
        skillRunning: {
          command: card.command,
          project,
          systems: card.check?.systems_needed ?? [],
        },
      },
    ]);
    setIsLoading(true);
    const res = await runSkill(
      {
        name: card.command,
        project,
        content_sha256: card.sha,
        consented: true,
        session_id: sessionId,
      },
      persona?.personaId
    );
    setMessages((prev) => prev.filter((m) => m.id !== runId));
    if (res.data) {
      if (!sessionId || res.data.session_id !== sessionId) setSessionId(res.data.session_id);
      const isPending = res.data.status === "pending_approval";
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId("resp"),
          role: "assistant",
          content: res.data!.response,
          systemsQueried: res.data!.systems_queried,
          proposal: isPending ? res.data!.proposal : null,
          stages: res.data!.stages,
          review: res.data!.review,
          skillRunInfo: res.data!.skill_run ?? undefined,
        },
      ]);
    } else {
      const failure = describeFailure("run", res, card.check?.writes_involved ?? false);
      if (failure.removeSkill) dropSkill(card.command);
      updateCard(msg.id, { state: "error", failure });
    }
    setIsLoading(false);
  }

  async function handleSend(message: string) {
    const userMsg: Message = {
      id: nextMessageId(),
      role: "user",
      content: message,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    const result = await api.post<ChatResponse>(
      "/chat",
      {
        message,
        session_id: sessionId,
        project_id: null,
      },
      persona?.personaId
    );

    if (result.data) {
      if (!sessionId || result.data.session_id !== sessionId) {
        setSessionId(result.data.session_id);
      }

      const isPending = result.data.status === "pending_approval";
      const assistantMsg: Message = {
        id: nextMessageId("resp"),
        role: "assistant",
        content: result.data.response,
        systemsQueried: result.data.systems_queried,
        proposal: isPending ? result.data.proposal : null,
        stages: result.data.stages,
        review: result.data.review,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } else {
      const errorMsg: Message = {
        id: nextMessageId("err"),
        role: "assistant",
        content: `Sorry, I encountered an error: ${result.error}`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    }
    setIsLoading(false);
  }

  async function decide(msg: Message, approved: boolean) {
    if (!sessionId) return;
    const interruptId = msg.proposal?.interrupt_id;
    // Fail safe: a missing interrupt id would produce a 422 at the thin API, so
    // leave the card disabled rather than call the API.
    if (!interruptId) return;
    setApprovingId(msg.id);

    const result = await api.post<ActionResult>(
      "/chat/approve",
      {
        session_id: sessionId,
        interrupt_id: interruptId,
        approved,
      },
      persona?.personaId
    );

    const data = result.data;
    const description = msg.proposal?.description ?? "";
    if (data && data.success !== false) {
      const verb = approved ? "Approved" : "Rejected";
      setActionResults((prev) => ({
        ...prev,
        [msg.id]: {
          success: true,
          message: description ? `${verb}: ${description}` : verb,
        },
      }));
      const followUps: Message[] = [];
      if (data.message) {
        followUps.push({
          id: nextMessageId("done"),
          role: "assistant",
          content: data.message,
        });
      }
      if (data.proposal) {
        followUps.push({
          id: nextMessageId("next"),
          role: "assistant",
          content: "",
          proposal: data.proposal,
        });
      }
      if (followUps.length > 0) {
        setMessages((prev) => [...prev, ...followUps]);
      }
    } else {
      const text =
        data?.message || result.error || "The action failed. Please try again.";
      setActionResults((prev) => ({
        ...prev,
        [msg.id]: { success: false, message: text },
      }));
    }
    setApprovingId(null);
  }

  function handleApprove(msg: Message) {
    return decide(msg, true);
  }

  function handleReject(msg: Message) {
    return decide(msg, false);
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="border-b border-gray-200 bg-white px-6 py-4 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">AI Assistant</h1>
            <p className="text-sm text-gray-500">
              Ask about your projects, sprints, documentation, and code
            </p>
          </div>
          {persona && (
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-600">
                {persona.personaLabel} · {persona.displayName}
              </span>
              <button
                type="button"
                onClick={() => {
                  logout();
                  router.push("/login");
                }}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 hover:border-gray-400 transition-colors"
              >
                Logout
              </button>
            </div>
          )}
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {messages.length === 0 && (
            <div className="text-center py-16">
              <p className="text-4xl mb-4">💬</p>
              <h2 className="text-lg font-medium text-gray-700 mb-2">
                How can I help you today?
              </h2>
              {templateSuggestions.length > 0 && (
                <div className="max-w-lg mx-auto mt-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {templateSuggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => handleSend(suggestion)}
                        className="text-left px-4 py-3 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id}>
              {msg.skillCommand && (
                <div className="mb-4 flex justify-end">
                  <span className="rounded-lg bg-blue-600 px-4 py-3 font-mono text-sm text-white">
                    {msg.skillCommand}
                  </span>
                </div>
              )}
              {msg.skillCard && (
                <SkillCheckCard
                  command={msg.skillCard.command}
                  project={msg.skillCard.project}
                  check={msg.skillCard.check}
                  state={msg.skillCard.state}
                  failure={msg.skillCard.failure}
                  skillContent={msg.skillCard.content}
                  onViewSkill={() => handleViewSkill(msg)}
                  onRun={(p) => handleRunSkill(msg, p)}
                  onCancel={() => handleCancelSkill(msg)}
                  onCheckAgain={(p) => handleCheckAgain(msg, p)}
                  onRunAgain={(p) => handleRunSkill(msg, p)}
                />
              )}
              {msg.skillRunning && (
                <SkillRunStatus
                  command={msg.skillRunning.command}
                  project={msg.skillRunning.project}
                  systems={msg.skillRunning.systems}
                />
              )}
              {msg.content && (
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  systemsQueried={msg.systemsQueried}
                  stages={msg.stages}
                  review={msg.review}
                  onOpenSkillUpload={(block) => {
                    setSkillDraft((prev) => ({ block, key: (prev?.key ?? 0) + 1 }));
                    setLibraryOpen(true);
                  }}
                />
              )}
              {msg.skillRunInfo && (
                <p className="mb-3 text-xs text-gray-500">
                  {formatRunSummary(msg.skillRunInfo, Boolean(msg.proposal))}
                </p>
              )}
              {msg.proposal && (
                <ProposalCard
                  proposal={msg.proposal}
                  onApprove={() => handleApprove(msg)}
                  onReject={() => handleReject(msg)}
                  isLoading={approvingId === msg.id}
                  result={actionResults[msg.id]}
                  fileSummaries={msg.review?.file_summaries}
                />
              )}
            </div>
          ))}

          {isLoading && (
            <StageProgress
              genLabel={CODE_GEN_OPTION.label}
              reviewLabel={reviewLabel}
            />
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-200 bg-white px-6 py-4">
          <ChatInput
            onSend={handleSend}
            disabled={isLoading}
            skills={skills}
            skillsFailed={skillsFailed}
            onSkillCommand={handleSkillCommand}
            onOpenSkills={() => {
              setSkillDraft(null);
              setLibraryOpen(true);
            }}
          />
        </div>
      </div>

      {libraryOpen && (
        <SkillLibraryPanel
          key={skillDraft?.key ?? 0}
          initialDraft={skillDraft?.block}
          skills={skills}
          personaId={persona?.personaId}
          onClose={() => setLibraryOpen(false)}
          onChanged={refreshSkills}
          onCheckSkill={(name) => {
            setLibraryOpen(false);
            void handleSkillCommand(name, null);
          }}
        />
      )}

      {/* Context Panel */}
      <ContextPanel
        isOpen={contextPanel.isOpen}
        onClose={() => setContextPanel((prev) => ({ ...prev, isOpen: false }))}
        title={contextPanel.title}
        content={contextPanel.content}
        type={contextPanel.type}
      />
    </div>
  );
}
