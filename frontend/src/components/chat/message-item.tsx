"use client";

import { cn } from "@/lib/utils";
import { motion } from "motion/react";
import { User, Sparkles, Copy, ThumbsUp, ThumbsDown } from "lucide-react";

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

function thinkMarkdownToHtml(text: string): string {
  // Simple markdown-like rendering
  let html = text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`;
    })
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\n/g, "<br/>");
  return html;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "flex gap-3 px-4 py-5",
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
        <div
          className={cn(
            "text-sm leading-relaxed",
            isUser ? "text-foreground" : "markdown text-foreground/90"
          )}
          dangerouslySetInnerHTML={
            isUser
              ? undefined
              : { __html: thinkMarkdownToHtml(message.content) }
          }
        >
          {isUser ? message.content : undefined}
        </div>

        {/* Sources */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <p className="text-[11px] font-medium text-muted/70 uppercase tracking-wider">
              来源引用
            </p>
            {message.sources.map((src, i) => (
              <div
                key={i}
                className="rounded-md border border-border bg-surface px-3 py-2 text-xs text-muted
                           hover:border-primary/30 transition-colors duration-150 cursor-pointer"
              >
                <span className="font-medium text-foreground/80">{src.filename}</span>
                <p className="mt-0.5 line-clamp-2">{src.chunk}</p>
              </div>
            ))}
          </div>
        )}

        {/* Actions (assistant only) */}
        {!isUser && (
          <div className="mt-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button className="rounded p-1 text-muted hover:text-foreground transition-colors cursor-pointer" title="复制">
              <Copy className="h-3 w-3" />
            </button>
            <button className="rounded p-1 text-muted hover:text-success transition-colors cursor-pointer" title="有用">
              <ThumbsUp className="h-3 w-3" />
            </button>
            <button className="rounded p-1 text-muted hover:text-error transition-colors cursor-pointer" title="无用">
              <ThumbsDown className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
