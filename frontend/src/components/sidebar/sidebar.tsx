"use client";

import { cn } from "@/lib/utils";
import {
  MessageSquare,
  BookOpen,
  Search,
  Eye,
  Settings,
  Plus,
  Zap,
  Sliders,
  Menu,
  X,
  Trash2,
} from "lucide-react";

type Tab = "chat" | "knowledge" | "search" | "agent" | "strategy" | "settings";

interface SidebarProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  onNewChat: () => void;
  conversations: { id: string; title: string }[];
  activeConversation: string | null;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  isOpen: boolean;
  onToggle: () => void;
}

const navItems: { id: Tab; label: string; icon: typeof MessageSquare }[] = [
  { id: "chat", label: "对话", icon: MessageSquare },
  { id: "knowledge", label: "知识库", icon: BookOpen },
  { id: "search", label: "搜索", icon: Search },
  { id: "agent", label: "Agent 观察", icon: Eye },
  { id: "strategy", label: "策略配置", icon: Sliders },
  { id: "settings", label: "设置", icon: Settings },
];

export function Sidebar({
  activeTab,
  onTabChange,
  onNewChat,
  conversations,
  activeConversation,
  onSelectConversation,
  onDeleteConversation,
  isOpen,
  onToggle,
}: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={onToggle}
        />
      )}

      {/* Mobile hamburger */}
      <button
        onClick={onToggle}
        className="fixed top-3 left-3 z-50 rounded-lg border border-border bg-surface p-2 md:hidden cursor-pointer"
      >
        {isOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
      </button>

      <aside
        className={cn(
          "flex h-full w-[260px] shrink-0 flex-col border-r border-border bg-[#0c1525] z-50",
          "fixed top-0 left-0 bottom-0 md:static",
          "transition-transform duration-200",
          isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border/50">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15">
            <Zap className="h-4 w-4 text-primary" />
          </div>
          <span className="text-base font-semibold tracking-tight">Orbit</span>
        </div>

        {/* Navigation */}
        <nav className="px-3 py-3 space-y-0.5">
          <button
            onClick={onNewChat}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm
                       text-muted hover:bg-surface hover:text-foreground
                       transition-colors duration-150 cursor-pointer"
          >
            <Plus className="h-4 w-4" />
            新对话
          </button>

          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => { onTabChange(item.id); onToggle(); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors duration-150 cursor-pointer",
                activeTab === item.id
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted hover:bg-surface hover:text-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </button>
          ))}
        </nav>

        {/* Conversation History */}
        {activeTab === "chat" && conversations.length > 0 && (
          <div className="flex-1 overflow-y-auto px-3 py-2">
            <p className="px-3 text-[11px] font-medium uppercase tracking-wider text-muted/60 mb-1.5">
              历史对话
            </p>
            <div className="space-y-0.5">
              {conversations.map((conv) => (
                <div
                  key={conv.id}
                  className={cn(
                    "group flex items-center rounded-lg px-3 py-1.5 transition-colors duration-150",
                    activeConversation === conv.id
                      ? "bg-surface text-foreground"
                      : "text-muted hover:bg-surface/50"
                  )}
                >
                  <button
                    onClick={() => { onSelectConversation(conv.id); onToggle(); }}
                    className="flex-1 truncate text-left text-xs cursor-pointer"
                  >
                    {conv.title}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDeleteConversation(conv.id); }}
                    className="rounded p-0.5 text-muted/20 opacity-0 group-hover:opacity-100
                               hover:text-error hover:bg-error/10 transition-all duration-150 cursor-pointer shrink-0"
                    title="删除对话"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="border-t border-border/50 px-4 py-3">
          <span className="text-xs text-muted">Orbit v1.0</span>
        </div>
      </aside>
    </>
  );
}
