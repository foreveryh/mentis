import { create } from 'zustand'

export interface ChatItem {
  id: string; // Corresponds to thread_id
  name: string;
  agentId: string; // e.g., 'chat', 'deep-research'
  agentName: string; // e.g., 'default', 'deep_research', 'customer_service'
  // Optional: Add creation timestamp, last updated timestamp, etc.
  createdAt: number;
}

interface ChatStore {
  chats: ChatItem[]
  addChat: (agentId:string, agentName:string, initialName?: string) => ChatItem
}

export const useChatStore = create<ChatStore>((set, get) => ({
  chats: [],
  addChat: (agentId: string, agentName: string, initialName?: string) => {
    const newChat: ChatItem = {
      id: crypto.randomUUID(),
      // Use provided initial name or generate default based on agent and count
      name: initialName || `${agentName} Chat ${get().chats.filter(c => c.agentName === agentName).length + 1}`,
      agentId: agentId, // Store the agent ID
      agentName: agentName, // Store the agent name
      createdAt: Date.now(),
    };
    set((state) => ({
      chats: [newChat, ...state.chats] // Add to beginning for recency
    }));
    return newChat;
  }
}))