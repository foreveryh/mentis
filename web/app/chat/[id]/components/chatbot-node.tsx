import { AgentState } from '../agent-types';
import { Bot, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Badge } from '@/components/ui/badge';
import { Message } from '@/hooks/useLangGraphAgent/types';
import { useEffect, useRef } from 'react';

interface ChatbotNodeProps {
  nodeState: Partial<AgentState>;
  fallbackMessages?: Message[]; // Add fallback messages from hook
}

export function ChatbotNode({ nodeState, fallbackMessages }: ChatbotNodeProps) {
  // 使用ref保存最后一次有效的消息列表，防止消息丢失
  const lastValidMessagesRef = useRef<Message[]>([]);
  
  // 如果nodeState.messages存在且不为空，使用它；否则使用fallbackMessages；如果都没有，使用上次有效的消息
  const currentMessages = nodeState?.messages?.length ? nodeState.messages : 
                         (fallbackMessages?.length ? fallbackMessages : lastValidMessagesRef.current);
  
  // 更新最后一次有效的消息引用
  useEffect(() => {
    if (currentMessages?.length > 0) {
      lastValidMessagesRef.current = [...currentMessages];
      console.log("[ChatbotNode] 更新最后有效消息缓存:", currentMessages.length);
    }
  }, [currentMessages]);

  // Debug log for message rendering
  console.log("[ChatbotNode] Rendering with:", { 
    nodeStateMessages: nodeState?.messages?.length || 0, 
    fallbackMessages: fallbackMessages?.length || 0,
    lastValidMessages: lastValidMessagesRef.current.length,
    displaying: currentMessages.length
  });

  // 添加更详细的消息内容调试
  if (currentMessages.length > 0) {
    console.log("[ChatbotNode] Messages content:", 
      currentMessages.map(msg => ({
        id: msg.id,
        type: msg.type,
        contentLength: msg.content?.length || 0,
        contentPreview: msg.content?.substring(0, 50) + (msg.content?.length > 50 ? '...' : ''),
        hasToolCalls: msg.tool_calls?.length > 0
      }))
    );
  }

  const getMessageIcon = (type: string) => {
    const baseClasses = "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700";

    switch (type) {
      case 'ai':
        return {
          icon: <Bot className="h-5 w-5" />,
          className: baseClasses
        };
      case 'user':
      case 'human':
        return {
          icon: <User className="h-5 w-5" />,
          className: baseClasses
        };
      default:
        return {
          icon: <Bot className="h-5 w-5" />,
          className: baseClasses
        };
    }
  };

  if (!currentMessages?.length) {
    console.log("[ChatbotNode] No messages to display, returning null");
    return null; // Don't render anything if no messages
  }

  return (
    <div className="space-y-4 font-mono">
      {currentMessages.map((msg, index) => (
        // When restoring data from checkpoint history, user input messages do not have an id.
        // Use index as key to avoid React warnings.
        <div key={msg.id ?? index} className="flex items-start gap-3" style={{border: '1px solid #f0f0f0', padding: '8px', margin: '8px 0'}}>
          <div className={cn(
            "flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full border",
            getMessageIcon(msg.type).className
          )}>
            {getMessageIcon(msg.type).icon}
          </div>
          <div className="flex-1 p-2 min-w-0">
            <div className="text-foreground text-sm break-words">
              {msg.content ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  className="prose prose-sm max-w-none overflow-hidden"
                  components={{
                    p: ({ children }) => <p className="mb-2 break-words">{children}</p>,
                    code: ({ children, className }) => {
                      const isInline = !className?.includes('language-');
                      return (
                        <code className={cn(
                          "bg-gray-100 px-1 py-0.5 rounded break-all",
                          !isInline && "block p-2 my-2 overflow-x-auto"
                        )}>
                          {children}
                        </code>
                      );
                    },
                    pre: ({ children }) => <pre className="bg-gray-100 p-2 rounded my-2 overflow-x-auto max-w-full">{children}</pre>,
                    ul: ({ children }) => <ul className="list-disc pl-6 mb-2">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal pl-6 mb-2">{children}</ol>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              ) : (
                <span className="text-gray-400 italic">(空消息)</span>
              )}
            </div>
            {msg.tool_calls && msg.tool_calls.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm font-mono">Tool calls:</span>
                {msg.tool_calls?.map((toolCall) => (
                  <div key={toolCall.id}>
                    <Badge variant="outline">{toolCall.name}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}