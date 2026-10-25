"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { buildSuggestions } from "@/lib/chatSuggestions";
import { api } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import type { Proposal, ChatResponse } from "@/types";
import ChatInput from "@/components/chat/ChatInput";
import ChatMessage from "@/components/chat/ChatMessage";
import ProposalCard from "@/components/chat/ProposalCard";
import ContextPanel from "@/components/chat/ContextPanel";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  systemsQueried?: string[];
  proposal?: Proposal | null;
}

interface ActionResult {
  success: boolean;
  message: string;
}

export default function ChatPage() {
  const router = useRouter();
  const { persona, logout } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [actionResults, setActionResults] = useState<Record<string, ActionResult>>({});
  const [approvingId, setApprovingId] = useState<string | null>(null);
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

  async function handleApprove(msg: Message) {
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
        approved: true,
      },
      persona?.personaId
    );

    if (result.data) {
      setActionResults((prev) => ({ ...prev, [msg.id]: result.data! }));
    }
    setApprovingId(null);
  }

  async function handleReject(msg: Message) {
    if (!sessionId) return;
    const interruptId = msg.proposal?.interrupt_id;
    if (!interruptId) return;
    setApprovingId(msg.id);

    const result = await api.post<ActionResult>(
      "/chat/approve",
      {
        session_id: sessionId,
        interrupt_id: interruptId,
        approved: false,
      },
      persona?.personaId
    );

    if (result.data) {
      setActionResults((prev) => ({ ...prev, [msg.id]: result.data! }));
    }
    setApprovingId(null);
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
              <ChatMessage
                role={msg.role}
                content={msg.content}
                systemsQueried={msg.systemsQueried}
              />
              {msg.proposal && (
                <ProposalCard
                  proposal={msg.proposal}
                  onApprove={() => handleApprove(msg)}
                  onReject={() => handleReject(msg)}
                  isLoading={approvingId === msg.id}
                  result={actionResults[msg.id]}
                />
              )}
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start mb-4">
              <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                <div className="flex gap-1.5">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.1s]" />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-200 bg-white px-6 py-4">
          <ChatInput onSend={handleSend} disabled={isLoading} />
        </div>
      </div>

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
