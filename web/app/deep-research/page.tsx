// @filename: app/deepresearch/page.tsx
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useChatStore } from '@/stores/chat-store';
import { Loader } from 'lucide-react'; // Keep loader for button state

export default function DeepResearchInitiationPage() {
    const [topic, setTopic] = useState('');
    const [isNavigating, setIsNavigating] = useState(false); // Simple loading state for navigation
    const [error, setError] = useState<string | null>(null);
    const router = useRouter();
    const { addChat } = useChatStore();

    const handleInitiateResearch = () => {
        if (!topic.trim()) {
            setError("Please enter a topic.");
            return;
        }
        setIsNavigating(true); // Indicate process started
        setError(null);

        try {
            // 1. Create the chat entry in the store to get an ID
            //    Use agentId, agentName, and pass topic as the optional initialName
            const newChat = addChat('deep-research', 'Deep Research', topic);

            // 2. Store the actual topic temporarily for the next page
            //    Use a unique key based on the new chat ID
            sessionStorage.setItem(`topic_for_${newChat.id}`, topic);

            // 3. Navigate to the specific research page
            //    The actual 'run' will be triggered on that page load
            router.push(`/deep-research/${newChat.id}`);

            // Note: No backend API call here. No 'run' triggered here.

        } catch (err: any) {
            console.error("Failed to initiate research process:", err);
            setError(err.message || "Failed to start. Please try again.");
            setIsNavigating(false); // Stop loading on error
        }
        // If navigation starts, the component will unmount, no need to set isNavigating back to false
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4">
            <Card className="w-full max-w-2xl shadow-lg">
                <CardHeader>
                    <CardTitle>Start New Deep Research</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-muted-foreground mb-4">
                        Enter the topic you want the agent to research in depth.
                    </p>
                    <Textarea
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        placeholder="Example: Impact of AI on renewable energy"
                        className="min-h-[100px] mb-4 text-sm"
                        disabled={isNavigating}
                    />
                    {error && (
                         <p className="text-red-500 text-sm mb-4">{error}</p>
                    )}
                    <Button
                        onClick={handleInitiateResearch} // Use the correct handler name
                        disabled={isNavigating || !topic.trim()}
                        className="w-full"
                    >
                        {isNavigating ? (
                            <>
                                <Loader className="mr-2 h-4 w-4 animate-spin" />
                                Proceeding...
                            </>
                        ) : (
                            // Changed button text to be more accurate
                            <>Prepare Research</>
                        )}
                    </Button>
                </CardContent>
            </Card>
        </div>
    );
}