// @filename: components/layout/app-sidebar.tsx (或者您的实际路径)
'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React from "react"; // 导入 React
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarFooter,
  SidebarGroup,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarGroupLabel,
  // SidebarGroupAction // 不再需要，我们用普通按钮替代
} from "@/components/ui/sidebar"; // 确认这是您自定义的 Sidebar 结构组件
import { Bot, Plus, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button"; // 导入 Button
import { useChatStore } from "@/stores/chat-store"; // 确认路径
import ThemeSwitcher from "./theme-switcher"; // 确认路径

// --- Agent 配置 (硬编码，未来可改为 API 获取) ---
// 'id' 应与后端 load_agent 期望的名称匹配
const availableAgents = [
  { id: 'chat', name: 'General Chatbot', description: '通用助理', icon: MessageSquare }, // 添加图标
  { id: 'deep_research', name: 'Deep Research', description: '深度研究助理', icon: Bot }, // 添加图标
  // 在这里添加更多 Agent
];
// --- Agent 配置结束 ---

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  // 假设 useChatStore 包含更新后的 addChat 和带 agentName 的 ChatItem
  const { chats, addChat } = useChatStore();

  // 处理创建新聊天的函数 (保持不变)
  const handleAddNewChat = (agentId: string, agentName: string) => {
    if (agentId === 'deep_research') {
      // For Deep Research, navigate to the dedicated initiation page
      const targetPath = '/deep-research/';
      console.log(`Navigating from Sidebar to Deep Research initiation: ${targetPath}`);
      router.push(targetPath);
      // NOTE: We DO NOT call addChat here for deep_research
    } else {
      // For all other agents, create chat item and navigate to its specific ID page
      console.log(`Creating new chat entry for agent: ${agentName}`);
      const newChat = addChat(agentId, agentName); // Create entry in store
      const targetPath = `/${agentId}/${newChat.id}`; // e.g., /default/abc987
      console.log(`Navigating from Sidebar to: ${targetPath}`);
      router.push(targetPath);
    }
  };

  return (
    <Sidebar>
      <SidebarHeader>
        {/* 保持您的 Header */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/" className="flex items-center gap-2">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <Bot className="size-4" />
                </div>
                <span className="font-semibold">Mentis Web UI</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="flex flex-col"> {/* 允许内容增长 */}
        {/* --- MODIFIED: 添加 Agent 创建按钮区域 --- */}
        <SidebarGroup className="flex-shrink-0"> {/* 防止此区域过度增长 */}
          <SidebarGroupLabel>New Chat</SidebarGroupLabel>
          <SidebarMenu className="mt-1 space-y-1"> {/* 为按钮添加间距 */}
            {availableAgents.map((agent) => {
              const Icon = agent.icon || Plus; // 使用配置的图标或默认 Plus
              return (
                <SidebarMenuItem key={agent.id}>
                  <Button
                    variant="ghost" // 使用 ghost 样式使其看起来像菜单项
                    size="sm"
                    className="w-full justify-start px-2" // 调整 padding 和对齐
                    onClick={() => handleAddNewChat(agent.id, agent.name)}
                    title={agent.description} // 添加工具提示
                  >
                    <Icon className="mr-2 size-4" /> {/* 显示图标 */}
                    {agent.name}
                  </Button>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
        {/* --- End Agent 创建按钮区域 --- */}

        <div className="my-4 border-t dark:border-gray-700 flex-shrink-0"></div> {/* 分隔线 */}

        {/* --- 聊天历史记录区域 --- */}
        <SidebarGroup className="flex-grow overflow-y-auto"> {/* 让历史记录区域可滚动 */}
          <SidebarGroupLabel>Recent Chats</SidebarGroupLabel>
           {/* 确保这里的 map 不会出错 */}
          <SidebarMenu className="mt-2">
            {/* 如果 chats 为空，可以显示提示 */}
            {chats && chats.length === 0 && (
              <p className="px-2 text-xs text-muted-foreground">No recent chats.</p>
            )}
            {/* --- MODIFIED: Link href in chat history --- */}
            {Array.isArray(chats) && chats.map((chat) => {
              // >>> Important Assumption: Your 'chat' object in the store needs to know its agentId <<<
              // >>> If not, you cannot correctly link back here. Let's assume chat has `agentId` <<<
              // >>> If `chat.agentId` doesn't exist, you'll need to update your store logic <<<
              const chatAgentId = chat.agentId || 'chat'; // Fallback to 'chat' if missing, adjust as needed

              // Construct the correct link based on the chat's agent type
              const chatHref = `/${chatAgentId}/${chat.id}`;
              const isActive = pathname === chatHref;

              // Find the agent icon (optional, improves UI)
               const agentConfig = availableAgents.find(a => a.id === chatAgentId);
               const Icon = agentConfig?.icon || MessageSquare; // Use agent icon or default

              return (
                <SidebarMenuItem key={chat.id}>
                  <SidebarMenuButton
                      asChild
                      isActive={isActive} // Check against the full dynamic path
                      className="truncate"
                      title={chat.name} // Use chat name for title
                  >
                    <Link href={chatHref}>
                      <Icon className="size-4 flex-shrink-0 mr-2" /> {/* Use dynamic icon */}
                      <span className="truncate">{chat.name}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        {/* 保持您的 Footer */}
        <div className="flex flex-col items-center text-sm gap-4">
          <ThemeSwitcher />
          <span>Made by{" "}
            <a
              href="https://github.com/foreveryh/mentis"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:text-primary/80 transition-colors inline-flex items-center gap-1 font-semibold underline underline-offset-4"
            >
              Mentis
            </a>
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}