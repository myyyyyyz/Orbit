"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Message, MessageItem } from "./message-item";
import { InputBox } from "./input-box";
import { knowledge } from "@/lib/api";

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const messageIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSend = useCallback(async (content: string) => {
    const userMsg: Message = {
      id: `msg-${++messageIdRef.current}`,
      role: "user",
      content,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);

    setIsLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantContent = "";

    const assistantMsg: Message = {
      id: `msg-${++messageIdRef.current}`,
      role: "assistant",
      content: "",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    knowledge.streamAsk(
      content,
      5,
      (token: string) => {
        assistantContent += token;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: assistantContent }
              : m
          )
        );
      },
      (model: string) => {
        console.log("[Orbit] Done with model:", model);
        setIsLoading(false);
      },
      (error: string) => {
        console.error("[Orbit] Stream error:", error);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: assistantContent || `错误: ${error}` }
              : m
          )
        );
        setIsLoading(false);
      },
      controller.signal
    );
  }, []);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setIsLoading(false);
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4">
            <div className="text-center max-w-md">
              <h1 className="text-2xl font-semibold tracking-tight mb-2">
                有什么我可以帮助你的？
              </h1>
              <p className="text-sm text-muted leading-relaxed mb-4">
                我可以帮你查询知识库、分析文档、委派 Agent 执行任务。
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {["总结我上传的文档", "这个项目有哪些模块", "帮我规划一个新功能"].map((q) => (
                  <button
                    key={q}
                    onClick={() => handleSend(q)}
                    className="rounded-full border border-border/60 px-3 py-1.5 text-xs text-muted
                               hover:border-primary/30 hover:text-foreground transition-colors duration-150 cursor-pointer"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="group">
            {messages.map((msg) => (
              <MessageItem key={msg.id} message={msg} />
            ))}
            {isLoading && messages[messages.length - 1]?.content === "" && (
              <div className="flex gap-3 px-4 py-5 bg-surface/50">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
                  <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                </div>
                <div className="flex items-center gap-1.5 py-1">
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <InputBox
        onSend={handleSend}
        isLoading={isLoading}
        onStop={handleStop}
      />
    </div>
  );
}
