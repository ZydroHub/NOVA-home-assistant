import React, { useCallback, useEffect, useRef } from 'react';
import { X, Minimize2, Trash2 } from 'lucide-react';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import MessageList from './MessageList';
import ChatInput from './ChatInput';

export default function MiniChat({ onClose, className }) {
    const {
        connStatus,
        messages,
        setMessages,
        streamText,
        streaming,
        sendMessage
    } = useWebSocket();

    const messagesEndRef = useRef(null);

    // Auto-scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, streamText]);

    const send = useCallback(
        (text, images = []) => {
            setMessages((prev) => [...prev, { role: 'user', text }]);
            sendMessage('send', { message: text, images });
        },
        [sendMessage, setMessages]
    );

    const abort = useCallback(() => {
        sendMessage('abort');
    }, [sendMessage]);

    const reset = useCallback(() => {
        sendMessage('reset');
        // Optional: Clear local messages if reset clears backend history
        // But usually backend sends 'session_reset' event which we might listen to?
        // For now, let's manually clear to be responsive
        setMessages([]);
    }, [sendMessage, setMessages]);

    return (
        <div className={`flex flex-col h-full bg-[var(--pixel-bg)] text-[var(--pixel-text)] font-['VT323'] ${className}`}>
            {/* Minimal Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b-4 border-[var(--pixel-border)] bg-[var(--pixel-surface)]">
                <span className="text-sm font-['Press_Start_2P'] text-[var(--pixel-primary)] uppercase">Assistant</span>
                <div className="flex items-center gap-4">
                    <button
                        onClick={reset}
                        className="p-2 hover:text-red-500 transition-colors"
                        title="RESET MEMORY"
                    >
                        <Trash2 size={20} />
                    </button>
                    {onClose && (
                        <button
                            onClick={onClose}
                            className="p-2 hover:text-[var(--pixel-accent)] transition-colors"
                        >
                            <Minimize2 size={20} />
                        </button>
                    )}
                </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto min-h-0 bg-[var(--pixel-bg)] p-2 scroller-pixel touch-scroll-y">
                <MessageList
                    messages={messages}
                    streaming={streaming}
                    streamText={streamText}
                />
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-2 border-t-4 border-[var(--pixel-border)] bg-[var(--pixel-surface)]">
                <ChatInput
                    onSend={send}
                    onAbort={abort}
                    streaming={streaming}
                    disabled={connStatus !== 'connected'}
                />
            </div>
        </div>
    );
}
