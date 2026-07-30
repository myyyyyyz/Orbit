"use client";

import { useState } from "react";
import { Brain, ChevronDown, ChevronUp } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export interface ThinkingBlockProps {
  content: string;
  status?: "thinking" | "done";
}

export function ThinkingBlock({ content, status = "done" }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="my-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 rounded-lg border border-border/50 bg-surface/30 px-3 py-2
                   text-left cursor-pointer hover:border-primary/20 transition-colors duration-150"
      >
        <Brain className="h-3.5 w-3.5 text-primary/70" />
        <span className="text-xs text-muted flex-1">
          {status === "thinking" ? "正在思考..." : "推理过程"}
        </span>
        {expanded
          ? <ChevronUp className="h-3 w-3 text-muted/40" />
          : <ChevronDown className="h-3 w-3 text-muted/40" />
        }
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="ml-7 mt-1.5 rounded-md border-l-2 border-primary/30 bg-[#0a0f1a]/50 px-3 py-2">
              <pre className="text-[11px] text-muted/70 font-mono leading-relaxed whitespace-pre-wrap">
                {content}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
