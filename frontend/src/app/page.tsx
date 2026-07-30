"use client";

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/sidebar/sidebar";
import { ChatInterface } from "@/components/chat/chat-interface";
import { KnowledgeBasePanel } from "@/components/knowledge-base/kb-panel";
import { AgentPanel } from "@/components/agent/agent-panel";
import { SettingsPanel } from "@/components/settings/settings-panel";
import { motion, AnimatePresence } from "motion/react";

type Tab = "chat" | "knowledge" | "agent" | "settings";

interface Conversation {
  id: string;
  title: string;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<string | null>(null);

  const handleNewChat = useCallback(() => {
    const id = `conv-${Date.now()}`;
    setConversations((prev) => [{ id, title: "新对话" }, ...prev]);
    setActiveConversation(id);
  }, []);

  const handleSelectConversation = useCallback((id: string) => {
    setActiveConversation(id);
    setActiveTab("chat");
  }, []);

  const renderPanel = () => {
    switch (activeTab) {
      case "chat":
        return <ChatInterface key="chat" />;
      case "knowledge":
        return <KnowledgeBasePanel key="knowledge" />;
      case "agent":
        return <AgentPanel key="agent" />;
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
      />

      <main className="flex-1 overflow-hidden">
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
