"use client";

import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { Send, Paperclip, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface InputBoxProps {
  onSend: (content: string) => void;
  isLoading: boolean;
  onStop?: () => void;
  disabled?: boolean;
}

export function InputBox({ onSend, isLoading, onStop, disabled }: InputBoxProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 160) + "px";
    }
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    onSend(trimmed);
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-border bg-[#0c1525] px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="relative flex items-end gap-2 rounded-xl border border-border bg-surface
                        focus-within:border-primary/40 transition-colors duration-200">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows={1}
            disabled={disabled}
            className="flex-1 resize-none bg-transparent px-3.5 py-3 text-sm
                       placeholder:text-muted/50 focus:outline-none
                       max-h-[160px]"
          />

          <div className="flex items-center gap-1 pr-2 pb-2">
            <button
              className="rounded-lg p-1.5 text-muted hover:text-foreground hover:bg-surface-elevated
                         transition-colors duration-150 cursor-pointer"
              title="上传文件"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            {isLoading ? (
              <button
                onClick={onStop}
                className="rounded-lg p-1.5 text-accent hover:bg-accent/10
                           transition-colors duration-150 cursor-pointer"
                title="停止生成"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() || disabled}
                className={cn(
                  "rounded-lg p-1.5 transition-all duration-150 cursor-pointer",
                  input.trim()
                    ? "bg-primary text-white hover:bg-primary-hover active:scale-[0.95]"
                    : "text-muted/40"
                )}
                title="发送"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted/50">
          Orbit 可能产生不准确信息，请核实重要内容
        </p>
      </div>
    </div>
  );
}
