import React, { useState, useCallback, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import ChatHeader from './ChatHeader';
import ConnectionBar from './ConnectionBar';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import ChatSidebar from './ChatSidebar';
import VirtualKeyboard from './VirtualKeyboard';
import { motion } from 'framer-motion';
import { pageEntrance } from '../motionPresets.js';

import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import { useKeyboardSettings } from '../contexts/KeyboardContext.jsx';

export default function ChatInterface() {
    const location = useLocation();
    const {
        connStatus,
        connect,
        chatConnStatus,
        messages,
        setMessages,
        streamText,
        streaming,
        sendMessage,
        conversations,
        currentConvId,
        setCurrentConvId,
        createConversation,
        deleteConversation,
        fetchConversations,
        thinking,
        toggleVoice,
        isRecording,
        addEventListener,
    } = useWebSocket();

    const [sidebarOpen, setSidebarOpen] = useState(false);
    const { keyboardEnabled, focusState, setFocusState, focusedElementRef, syncInputValueRef } = useKeyboardSettings();
    const showInlineKeyboard = keyboardEnabled && focusState?.isChatInput === true;

    const closeKeyboard = useCallback(() => {
        setFocusState(null);
        focusedElementRef.current = null;
    }, [setFocusState, focusedElementRef]);

    const handleChatAreaPointerDown = useCallback(
        (e) => {
            if (!focusState?.isChatInput) return;
            const target = e.target;
            if (target?.closest?.('[data-virtual-keyboard]')) return;
            if (target?.closest?.('[data-chat-input-bar]')) return;
            if (target?.closest?.('[data-chat-messages]')) return;
            closeKeyboard();
        },
        [focusState?.isChatInput, closeKeyboard]
    );

    // ─── Actions ───────────────────────────────────────────────────────
    const send = useCallback(
        async (text, images = []) => {
            let activeConvId = currentConvId;
            if (!activeConvId) {
                const conv = await createConversation();
                if (conv) {
                    activeConvId = conv.id;
                    setCurrentConvId(conv.id);
                } else {
                    console.error("Failed to create conversation");
                    return;
                }
            }
            // Add user message immediately
            setMessages((prev) => [...prev, { role: 'user', text }]);
            sendMessage('send', { message: text, images, conv_id: activeConvId, thinking });
        },
        [sendMessage, setMessages, currentConvId, createConversation, setCurrentConvId, thinking]
    );

    // ─── Auto-select/create conversation ──────────────────────────────
    useEffect(() => {
        if (!currentConvId && conversations.length > 0) {
            setCurrentConvId(conversations[0].id);
        }
    }, [currentConvId, conversations, setCurrentConvId]);

    // Refetch conversations when Chat is shown and on an interval so task-created conversations appear without restart
    useEffect(() => {
        fetchConversations();
        const interval = setInterval(fetchConversations, 15000);
        return () => clearInterval(interval);
    }, [fetchConversations]);

    // ─── Auto-send from navigation ─────────────────────────────
    useEffect(() => {
        if (chatConnStatus === 'connected' && location.state?.prompt && location.state?.image && currentConvId) {
            const { prompt, image } = location.state;
            window.history.replaceState({}, document.title);
            send(prompt, [image]);
        }
    }, [chatConnStatus, location.state, send, currentConvId]);

    // When Whisper transcription is received in chat, send it to the backend so the AI responds
    useEffect(() => {
        const remove = addEventListener('voice_transcription', async (data) => {
            const text = (data.text || '').trim();
            if (!text) return;
            let convId = currentConvId;
            if (!convId && conversations.length > 0) convId = conversations[0].id;
            if (!convId) {
                const conv = await createConversation();
                if (conv) {
                    setCurrentConvId(conv.id);
                    convId = conv.id;
                }
            }
            if (convId) sendMessage('send', { message: text, conv_id: convId, thinking });
        });
        return remove;
    }, [addEventListener, currentConvId, conversations, createConversation, setCurrentConvId, sendMessage, thinking]);

    const abort = useCallback(() => {
        sendMessage('abort');
    }, [sendMessage]);

    const reset = useCallback(() => {
        sendMessage('reset');
    }, [sendMessage]);

    // ─── Render ────────────────────────────────────────────────────────
    return (
        <motion.div
            variants={pageEntrance}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="relative h-full w-full overflow-hidden bg-[#050816] text-[var(--nova-text)]"
        >
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(39,169,255,0.14),transparent_32%,rgba(95,244,178,0.08)_68%,transparent)]" />
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(124,224,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(124,224,255,0.035)_1px,transparent_1px)] bg-[size:42px_42px]" />
            <ChatSidebar
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
                conversations={conversations}
                currentConvId={currentConvId}
                setCurrentConvId={setCurrentConvId}
                createConversation={createConversation}
                deleteConversation={deleteConversation}
            />

            {/* Main Chat Area: keyboard in flow so it pushes content up (phone-style); tap outside input/keyboard closes keyboard */}
            <div
                className="relative z-10 flex h-full min-h-0 min-w-0 flex-1 flex-col p-3 touch-pan-y"
                onPointerDown={handleChatAreaPointerDown}
            >
                <motion.div variants={pageEntrance} className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/[0.08] bg-slate-900/[0.4] shadow-[0_24px_80px_rgba(0,0,0,0.42),inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-md">
                    <ChatHeader
                        connected={connStatus === 'connected'}
                        onReset={reset}
                        sidebarOpen={sidebarOpen}
                        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
                        onCloseKeyboard={closeKeyboard}
                    />
                    {connStatus !== 'connected' && <ConnectionBar status={connStatus} onRetry={connect} />}
                    <MessageList
                        messages={messages}
                        streaming={streaming}
                        streamText={streamText}
                    />
                    <ChatInput
                        onSend={send}
                        onAbort={abort}
                        onMicPress={() => toggleVoice({ transcriptionOnly: true })}
                        isRecording={isRecording}
                        streaming={streaming}
                        disabled={connStatus !== 'connected'}
                    />
                    <VirtualKeyboard visible={showInlineKeyboard} mode="inline" focusedElementRef={focusedElementRef} syncInputValueRef={syncInputValueRef} />
                </motion.div>
            </div>
        </motion.div>
    );
}
