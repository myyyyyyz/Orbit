"use client";

import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "motion/react";
import { User, Sparkles, Copy, ThumbsUp, ThumbsDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { SourcePopover } from "./source-popover";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: { filename: string; chunk: string }[];
  timestamp: number;
}

interface MessageItemProps {
  message: Message;
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";
  const reduce = useReducedMotion();

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "flex gap-3 px-4 py-5 group",
        isUser ? "bg-transparent" : "bg-surface/50"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-accent/20 text-accent" : "bg-primary/20 text-primary"
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className={cn(
          "text-sm leading-relaxed",
          isUser ? "text-foreground" : "markdown text-foreground/90"
        )}>
          {isUser ? (
            message.content
          ) : (
            <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
              {message.content}
            </ReactMarkdown>
          )}
        </div>

        {/* Sources */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <p className="text-[11px] font-medium text-muted/70 uppercase tracking-wider">
              来源引用
            </p>
            {message.sources.map((src, i) => (
              <SourcePopover key={i} filename={src.filename} chunk={src.chunk}>
                <span className="inline-flex items-center rounded-md border border-border bg-surface px-2 py-0.5
                               text-[11px] text-primary/80 hover:text-primary hover:border-primary/30
                               transition-colors duration-150 cursor-pointer">
                  {src.filename}
                </span>
              </SourcePopover>
            ))}
          </div>
        )}

        {/* Actions (assistant only) */}
        {!isUser && (
          <div className="mt-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              className="rounded p-1 text-muted hover:text-foreground transition-colors cursor-pointer"
              title="复制"
              onClick={() => navigator.clipboard.writeText(message.content)}
            >
              <Copy className="h-3 w-3" />
            </button>
            <button
              className="rounded p-1 text-muted hover:text-success transition-colors cursor-pointer"
              title="有用"
              onClick={() => console.log("[Feedback] positive:", message.id)}
            >
              <ThumbsUp className="h-3 w-3" />
            </button>
            <button
              className="rounded p-1 text-muted hover:text-error transition-colors cursor-pointer"
              title="无用"
              onClick={() => console.log("[Feedback] negative:", message.id)}
            >
              <ThumbsDown className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
