"use client";

import { useState, useRef, useEffect } from "react";
import { FileText } from "lucide-react";

interface SourcePopoverProps {
  filename: string;
  chunk: string;
  children: React.ReactNode;
}

export function SourcePopover({ filename, chunk, children }: SourcePopoverProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = () => {
    clearTimeout(timeoutRef.current);
    setVisible(true);
  };

  const hide = () => {
    timeoutRef.current = setTimeout(() => setVisible(false), 200);
  };

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  return (
    <span
      className="relative inline"
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      {children}

      {visible && (
        <div
          className="absolute bottom-full left-0 mb-2 z-50 w-72 rounded-lg border border-border
                     bg-surface-elevated shadow-lg p-3 pointer-events-none"
          onMouseEnter={show}
          onMouseLeave={hide}
        >
          <div className="flex items-center gap-2 mb-2">
            <FileText className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-medium text-foreground/90">{filename}</span>
          </div>
          <p className="text-[11px] text-muted leading-relaxed line-clamp-5">
            {chunk}
          </p>
          <div className="absolute left-3 top-full -mt-0.5 h-2 w-2 rotate-45 bg-surface-elevated border-r border-b border-border z-[51]" />
        </div>
      )}
    </span>
  );
}
