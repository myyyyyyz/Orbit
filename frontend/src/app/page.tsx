"use client";

import { useState, useCallback } from "react";
import { useLocalFlag, setLocalValue } from "@/lib/local-storage";
import { Sidebar } from "@/components/sidebar/sidebar";
import { ChatInterface } from "@/components/chat/chat-interface";
import { KnowledgeBasePanel } from "@/components/knowledge-base/kb-panel";
import { SearchPanel } from "@/components/search/search-panel";
import { SettingsPanel } from "@/components/settings/settings-panel";
import { StrategyPanel } from "@/components/strategy/strategy-panel";
import { OnboardingWizard } from "@/components/onboarding/wizard";
import { AuthForm } from "@/components/auth/auth-form";
import { useAuth } from "@/lib/auth-context";
import { motion, AnimatePresence } from "motion/react";

type Tab = "chat" | "knowledge" | "search" | "strategy" | "settings";

interface Conversation {
  id: string;
  title: string;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<string | null>(null);
  const { isAuthenticated } = useAuth();

  // localStorage 是外部数据源：用订阅读取（SSR 首帧为 false，挂载后自动切真值）。
  // 之前是「effect 里读 + setState」，会触发级联渲染并违反 React Compiler 规则。
  const skipLogin = useLocalFlag("orbit_skip_login");
  const onboarded = useLocalFlag("orbit_onboarded");

  // 两个门都是派生状态，不需要各自的 state
  const showAuth = !isAuthenticated && !skipLogin;
  const showOnboarding = !showAuth && !onboarded;

  const handleSkipAuth = useCallback(() => {
    setLocalValue("orbit_skip_login", "true");
  }, []);

  const handleOnboardingComplete = useCallback((role: string) => {
    setLocalValue("orbit_onboarded", "true");
    setLocalValue("orbit_role", role);
  }, []);

  const handleNewChat = useCallback(() => {
    const id = `conv-${Date.now()}`;
    setConversations((prev) => [{ id, title: "新对话" }, ...prev]);
    setActiveConversation(id);
  }, []);

  const handleSelectConversation = useCallback((id: string) => {
    setActiveConversation(id);
    setActiveTab("chat");
  }, []);

  const handleDeleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConversation === id) setActiveConversation(null);
  }, [activeConversation]);

  // 未登录且未跳过 → 登录/注册页（可跳过匿名使用）
  if (showAuth) {
    return <AuthForm onSkip={handleSkipAuth} />;
  }

  // 首次使用（含跳过后匿名进入）→ 引导向导
  if (showOnboarding) {
    return <OnboardingWizard onComplete={handleOnboardingComplete} />;
  }

  const renderPanel = () => {
    switch (activeTab) {
      case "chat":
        return <ChatInterface key="chat" />;
      case "knowledge":
        return <KnowledgeBasePanel key="knowledge" />;
      case "search":
        return <SearchPanel key="search" />;
      case "strategy":
        return <StrategyPanel key="strategy" />;
      case "settings":
        return <SettingsPanel key="settings" />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onNewChat={handleNewChat}
        conversations={conversations}
        activeConversation={activeConversation}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen((o) => !o)}
      />

      <main className="flex-1 overflow-hidden md:ml-0">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -4 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="h-full"
          >
            {renderPanel()}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
