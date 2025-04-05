// @filename: pages/index.tsx (或者您的主页文件路径)
'use client';

import React, { useState } from 'react'; // 导入 React 和 useState
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
// --- MODIFIED: Import Dialog components ---
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter, // Optional: if you need a footer
  DialogClose,  // Optional: for explicit close buttons
} from "@/components/ui/dialog";
// --- MODIFIED: Import useChatStore again ---
import { useChatStore } from "@/stores/chat-store";
// --- Example Icons ---
import { BrainCircuit, Users, Wrench, BotMessageSquare, GitBranch, MessageSquare } from "lucide-react";

// --- Agent Configuration (Hardcoded for now) ---
// 'id' should match the agent name expected by your backend API loader.
const availableAgents = [
  { id: 'default', name: 'ReAct Agent', description: 'A general purpose assistant for various tasks.', icon: MessageSquare },
  { id: 'deep_research', name: 'Deep Research', description: 'Performs in-depth research on a topic.', icon: BrainCircuit },
  // Add other agents here
  // { id: 'another_agent', name: 'Another Agent', description: 'Description here', icon: Users },
];
// --- End Agent Configuration ---


// --- Feature Block Component (Unchanged from previous version) ---
function FeatureBlock({ title, description, icon: Icon }: { title: string; description: string; icon?: React.ElementType; }) {
  return (
    <div className="group p-4 md:p-6 rounded-lg bg-card dark:bg-gray-800/50 border border-border dark:border-gray-700/50 hover:shadow-md transition-shadow duration-300">
      <div className="flex items-center gap-3 mb-3">
         {Icon && <Icon className="w-6 h-6 text-primary flex-shrink-0" />}
         <h3 className="text-lg md:text-xl font-semibold text-foreground">{title}</h3>
      </div>
      <p className="text-sm md:text-base text-muted-foreground">{description}</p>
    </div>
  );
}

// --- Main Welcome Page Component ---
export default function WelcomePage() {
  const router = useRouter();
  // --- MODIFIED: Get addChat from the store ---
  const { addChat } = useChatStore();
  // State to control Dialog open/closed status, useful for closing programmatically
  const [isAgentSelectorOpen, setIsAgentSelectorOpen] = useState(false);

  // --- MODIFIED: Handler to create chat AND navigate ---
  const handleCreateChat = (agentId: string, agentName: string) => {
    console.log(`Creating new chat for agent: ${agentName} (ID: ${agentId})`);
    // Assume addChat takes agentId and returns the new chat object
    const newChat = addChat(`${agentId}`,`${agentName}`); // Create a slightly more descriptive name
    // Close the dialog
    setIsAgentSelectorOpen(false);
    // Navigate to the chat page
    router.push(`/chat/${newChat.id}`);
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background via-background/80 to-blue-50 dark:to-blue-900/20 flex items-center justify-center">
      <div className="container px-4 py-12 md:py-16 mx-auto space-y-12 md:space-y-16">

        {/* Hero Section (Unchanged) */}
        <div className="text-center space-y-4 max-w-4xl mx-auto">
          <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
            Welcome to Mentis
          </h1>
          <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto">
            An interactive learning framework for exploring Superagents and Multi-Agent Systems built with LangGraph.
          </p>
        </div>

        {/* About/Purpose Section (Unchanged) */}
        <div className="max-w-3xl mx-auto text-center space-y-4">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight">Learn by Doing</h2>
          <p className="text-base md:text-lg text-muted-foreground leading-relaxed">
            Mentis provides hands-on examples and tools to help you understand the core concepts, architectures, and capabilities of modern AI agents. Dive into pre-built agents or explore the underlying graph structures.
          </p>
        </div>

        {/* Capabilities / Concepts Section (Unchanged) */}
        <div className="space-y-8">
          <h3 className="text-2xl md:text-3xl font-semibold text-center">Explore Key Agent Concepts</h3>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6 max-w-5xl mx-auto">
            <FeatureBlock title="Autonomous Agents (Superagents)" description="Interact with agents for complex, multi-step tasks like research, utilizing planning and tool use." icon={BrainCircuit} />
            <FeatureBlock title="Multi-Agent Collaboration" description="Observe how multiple specialized agents can work together, delegate tasks, and achieve a common goal." icon={Users}/>
            <FeatureBlock title="Tool Usage & Function Calling" description="See how agents leverage external tools (web search, APIs) to enhance their abilities." icon={Wrench}/>
            <FeatureBlock title="Streaming & Real-time Feedback" description="Experience how intermediate steps and results are streamed back for transparency." icon={BotMessageSquare}/>
            <FeatureBlock title="State Management & Persistence" description="Understand how LangGraph manages conversation state for resuming and tracing execution."/>
            <FeatureBlock title="Human-in-the-Loop" description="Explore scenarios where agents pause to ask for human input or approval."/>
          </div>
        </div>

        {/* CTA Section --- MODIFIED --- */}
        <div className="text-center pt-4">
          {/* Use Dialog component */}
          <Dialog open={isAgentSelectorOpen} onOpenChange={setIsAgentSelectorOpen}>
            {/* Button triggers the Dialog */}
            <DialogTrigger asChild>
              <Button size="lg" className="px-8 py-3 text-lg">
                Explore Agents
              </Button>
            </DialogTrigger>
            {/* Dialog Content */}
            <DialogContent className="sm:max-w-[425px] md:max-w-lg"> {/* Adjust max width */}
              <DialogHeader>
                <DialogTitle>Select an Agent</DialogTitle>
                <DialogDescription>
                  Choose an agent type to start interacting with.
                </DialogDescription>
              </DialogHeader>
              {/* List of available agents */}
              <div className="grid gap-4 py-4">
                {availableAgents.map((agent) => {
                   const Icon = agent.icon || Bot; // Default icon
                   return (
                     <button
                       key={agent.id}
                       onClick={() => handleCreateChat(agent.id, agent.name)}
                       className="flex items-center p-4 rounded-lg border bg-card hover:bg-muted/50 dark:border-gray-700 dark:hover:bg-gray-800/60 transition-colors text-left w-full"
                     >
                       <Icon className="w-6 h-6 mr-4 text-primary flex-shrink-0" />
                       <div>
                         <p className="font-semibold text-foreground">{agent.name}</p>
                         <p className="text-sm text-muted-foreground">{agent.description}</p>
                       </div>
                     </button>
                   )
                 })}
              </div>
              {/* Optional Footer with Close button
              <DialogFooter>
                 <DialogClose asChild>
                     <Button type="button" variant="secondary">Close</Button>
                 </DialogClose>
              </DialogFooter>
               */}
            </DialogContent>
          </Dialog>
        </div>
        {/* --- End CTA Section --- */}

      </div>
    </div>
  );
}