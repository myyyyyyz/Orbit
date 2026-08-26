"use client";

import { cn } from "@/lib/utils";
import {
  MessageSquare,
  BookOpen,
  Search,
  Settings,
  Plus,
  Sliders,
  Menu,
  X,
  Trash2,
  LogOut,
  LogIn,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

type Tab = "chat" | "knowledge" | "search" | "strategy" | "settings";

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
  const { isAuthenticated, username, logout } = useAuth();

  /** 访客模式下引导登录：清除跳过标记并回到登录页 */
  const handleSignIn = () => {
    localStorage.removeItem("orbit_skip_login");
    window.location.reload();
  };

  return (
    <>
      {/* 移动端遮罩 */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm md:hidden"
          onClick={onToggle}
          aria-hidden
        />
      )}

      {/* 移动端汉堡按钮 */}
      <button
        onClick={onToggle}
        aria-label={isOpen ? "关闭菜单" : "打开菜单"}
        className="fixed left-3 top-3 z-50 rounded-lg border border-border bg-surface/90 p-2
                   backdrop-blur transition-colors hover:bg-surface-elevated md:hidden cursor-pointer"
      >
        {isOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
      </button>

      <aside
        className={cn(
          "z-50 flex h-full w-[248px] shrink-0 flex-col border-r border-border bg-surface-sunken",
          "fixed bottom-0 left-0 top-0 md:static",
          "transition-transform duration-250 ease-out",
          isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        {/* 品牌区 */}
        <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-border px-4">
          <div
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-border-strong
                       bg-surface-elevated ring-highlight"
          >
            <OrbitMark />
          </div>
          <div className="min-w-0">
            <div className="text-[0.9375rem] font-semibold leading-tight tracking-tight">Orbit</div>
            <div className="text-[0.625rem] leading-tight text-muted-subtle">AI Agent 工作台</div>
          </div>
        </div>

        {/* 新对话 */}
        <div className="px-3 pb-1 pt-3">
          <button
            onClick={onNewChat}
            className="group flex w-full items-center gap-2 rounded-lg border border-border bg-surface
                       px-3 py-2 text-[0.8125rem] font-medium text-foreground-muted
                       transition-all duration-150
                       hover:border-primary/40 hover:bg-primary-soft hover:text-primary
                       cursor-pointer"
          >
            <Plus className="h-4 w-4 transition-transform duration-200 group-hover:rotate-90" />
            新对话
          </button>
        </div>

        {/* 导航 */}
        <nav className="space-y-0.5 px-3 py-2" aria-label="主导航">
          {navItems.map((item) => {
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  onTabChange(item.id);
                  onToggle();
                }}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[0.8125rem]",
                  "transition-colors duration-150 cursor-pointer",
                  active
                    ? "bg-primary-soft font-medium text-primary"
                    : "text-muted hover:bg-surface hover:text-foreground"
                )}
              >
                {/* 激活指示条 */}
                {active && (
                  <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-primary" />
                )}
                <item.icon className="h-4 w-4 shrink-0" />
                {item.label}
              </button>
            );
          })}
        </nav>

        {/* 历史对话 */}
        {activeTab === "chat" && conversations.length > 0 && (
          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
            <p className="mb-1.5 px-3 pt-1 text-[0.625rem] font-medium uppercase tracking-wider text-muted-subtle">
              历史对话
            </p>
            <div className="space-y-0.5">
              {conversations.map((conv) => (
                <div
                  key={conv.id}
                  className={cn(
                    "group flex items-center rounded-lg pl-3 pr-1 transition-colors duration-150",
                    activeConversation === conv.id
                      ? "bg-surface text-foreground"
                      : "text-muted hover:bg-surface/60"
                  )}
                >
                  <button
                    onClick={() => {
                      onSelectConversation(conv.id);
                      onToggle();
                    }}
                    className="flex-1 truncate py-1.5 text-left text-xs cursor-pointer"
                  >
                    {conv.title}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteConversation(conv.id);
                    }}
                    aria-label={`删除对话 ${conv.title}`}
                    className="shrink-0 rounded p-1 text-muted-subtle opacity-0 transition-all duration-150
                               hover:bg-error-soft hover:text-error group-hover:opacity-100
                               focus-visible:opacity-100 cursor-pointer"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 撑开剩余空间，保证 footer 贴底 */}
        <div className="flex-1" />

        {/* 底部：账号区 */}
        <div className="shrink-0 border-t border-border p-3">
          {isAuthenticated ? (
            <div className="flex items-center gap-2 rounded-lg bg-surface px-2.5 py-2">
              <div
                className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/20
                           text-[0.625rem] font-semibold text-primary"
              >
                {(username || "U").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-foreground">{username || "已登录"}</div>
              </div>
              <button
                onClick={logout}
                aria-label="退出登录"
                title="退出登录"
                className="shrink-0 rounded p-1 text-muted-subtle transition-colors duration-150
                           hover:bg-error-soft hover:text-error cursor-pointer"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={handleSignIn}
              className="flex w-full items-center gap-2 rounded-lg bg-surface px-2.5 py-2
                         text-left transition-colors duration-150 hover:bg-surface-elevated cursor-pointer"
            >
              <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-warning-soft">
                <span className="h-1.5 w-1.5 rounded-full bg-warning" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-foreground-muted">访客模式</div>
                <div className="text-[0.625rem] text-muted-subtle">点击登录解锁全部能力</div>
              </div>
              <LogIn className="h-3.5 w-3.5 shrink-0 text-muted-subtle" />
            </button>
          )}

          <div className="mt-2 px-1 text-[0.625rem] text-muted-subtle">Orbit v1.0</div>
        </div>
      </aside>
    </>
  );
}

/** 品牌标识：轨道环绕 */
function OrbitMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 26 26" fill="none" aria-hidden>
      <ellipse
        cx="13"
        cy="13"
        rx="11"
        ry="5.5"
        stroke="var(--primary)"
        strokeWidth="1.6"
        opacity="0.75"
        transform="rotate(-28 13 13)"
      />
      <circle cx="13" cy="13" r="3.8" fill="var(--primary)" />
      <circle cx="22.2" cy="8.4" r="2.1" fill="var(--accent)" />
    </svg>
  );
}
