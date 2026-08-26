"use client";

import { useState, useCallback, useEffect } from "react";
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
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showAuth, setShowAuth] = useState(false);          // Bug #17: 接入登录/注册 UI
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<string | null>(null);
  const { isAuthenticated } = useAuth();

  // localStorage 只能在浏览器访问（SSR/hydration 安全），故必须放在 effect 里
  useEffect(() => {
    // Bug #17: 未登录且未跳过时显示登录/注册页
    if (!isAuthenticated && !localStorage.getItem("orbit_skip_login")) {
      setShowAuth(true);
      return;
    }
    const onboarded = localStorage.getItem("orbit_onboarded");
    if (!onboarded) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 客户端渲染模式下的正确位置
      setShowOnboarding(true);
    }
  }, [isAuthenticated]);

  // 登录成功后关闭登录页，新用户走 onboarding
  useEffect(() => {
    if (isAuthenticated && showAuth) {
      setShowAuth(false);
      if (!localStorage.getItem("orbit_onboarded")) {
        setShowOnboarding(true);
      }
    }
  }, [isAuthenticated, showAuth]);

  const handleSkipAuth = useCallback(() => {
    localStorage.setItem("orbit_skip_login", "true");
    setShowAuth(false);
  }, []);

  const handleOnboardingComplete = useCallback((role: string) => {
    localStorage.setItem("orbit_onboarded", "true");
    localStorage.setItem("orbit_role", role);
    setShowOnboarding(false);
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
  if (showAuth && !isAuthenticated) {
    return <AuthForm onSkip={handleSkipAuth} />;
  }

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
