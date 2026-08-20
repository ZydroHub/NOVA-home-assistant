import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import MessageBubble from './MessageBubble';
import { itemEntrance } from '../motionPresets.js';

export default function MessageList({ messages, streaming, streamText }) {
    const bottomRef = useRef(null);
    const scrollContainerRef = useRef(null);
    const dragScrollRef = useRef(null); // { clientY, scrollTop } when pointer-drag scrolling

    // Pointer-drag scroll: touch screens often send touch as mouse/pointer, so native touch scroll never runs. Manually scroll on pointer move.
    const onPointerDown = (e) => {
        if (e.target.closest?.('button, a, input, select, textarea, [role="button"]')) return;
        const el = scrollContainerRef.current;
        if (!el || el.scrollHeight <= el.clientHeight) return;
        dragScrollRef.current = { clientY: e.clientY, scrollTop: el.scrollTop };
        el.setPointerCapture(e.pointerId);
    };
    const onPointerMove = (e) => {
        const state = dragScrollRef.current;
        if (!state) return;
        const el = scrollContainerRef.current;
        if (!el) return;
        const deltaY = e.clientY - state.clientY;
        const newTop = Math.max(0, Math.min(el.scrollHeight - el.clientHeight, state.scrollTop - deltaY));
        el.scrollTop = newTop;
        state.scrollTop = newTop;
        state.clientY = e.clientY;
        e.preventDefault();
    };
    const onPointerUp = (e) => {
        if (dragScrollRef.current) {
            scrollContainerRef.current?.releasePointerCapture(e.pointerId);
            dragScrollRef.current = null;
        }
    };

    // Auto-scroll when messages change or stream updates
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, streamText]);

    const mainContent = streamText.replace(/<think>[\s\S]*?(?:<\/think>|$)/gi, '').trim();

    const isEmpty = messages.length === 0 && !streaming;

    return (
        <div
            ref={scrollContainerRef}
            className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-x-hidden px-3 py-4 sm:px-5 scroller-pixel touch-scroll-y"
            data-chat-messages
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onPointerLeave={onPointerUp}
        >
            {isEmpty && (
                <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
                    <div className="rounded-full border border-cyan-300/20 bg-cyan-300/[0.06] px-4 py-2 text-[0.68rem] font-bold uppercase tracking-[0.24em] text-cyan-100/70 shadow-[0_0_28px_rgba(26,209,255,0.12)]">
                        Secure Link Ready
                    </div>
                    <div className="max-w-[18rem] text-2xl font-black tracking-tight text-white">
                        Start a conversation with NOVA
                    </div>
                    <div className="max-w-[22rem] text-sm leading-relaxed text-cyan-100/55">
                        The chat core is idle and ready for typed or voice input.
                    </div>
                </div>
            )}

            {messages.map((msg, i) => (
                <motion.div key={i} custom={i} variants={itemEntrance} initial="hidden" animate="visible">
                    <MessageBubble role={msg.role} text={msg.text} />
                </motion.div>
            ))}

            {/* Streaming AI response */}
            {streaming && streamText && (
                <div className="flex justify-start animate-message-in">
                    <div className="relative max-w-[88%] overflow-hidden rounded-3xl border border-cyan-300/20 bg-slate-900/55 px-5 py-4 text-[15px] leading-relaxed text-cyan-50 shadow-[0_18px_50px_rgba(0,0,0,0.32),inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-md">
                        <div className="absolute inset-y-0 left-0 w-[3px] nova-breathing-glow-fast bg-cyan-300 shadow-[0_0_18px_rgba(26,209,255,0.9)]" />
                        <div className="mb-3 flex items-center gap-2 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-cyan-100/75">
                            <span className="h-1.5 w-1.5 rounded-full nova-breathing-glow-fast bg-cyan-300 shadow-[0_0_12px_rgba(26,209,255,0.9)]" />
                            NOVA Streaming
                        </div>

                        <div className="markdown-content whitespace-pre-wrap break-words">
                            {mainContent} <span className="animate-blink">_</span>
                        </div>
                    </div>
                </div>
            )}

            {/* Typing indicator (shown while streaming but no text yet) */}
            {streaming && !streamText && (
                <div className="flex justify-start animate-message-in">
                    <div className="flex items-center gap-3 rounded-full border border-cyan-300/20 bg-slate-900/55 px-5 py-4 shadow-[0_16px_40px_rgba(0,0,0,0.28)] backdrop-blur-md">
                        <div className="h-2 w-8 overflow-hidden rounded-full bg-cyan-300/15">
                            <div className="h-full w-1/2 animate-pulse rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(26,209,255,0.8)]" />
                        </div>
                        <div className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-100/65">
                            NOVA thinking
                        </div>
                    </div>
                </div>
            )}

            <div ref={bottomRef} />
        </div>
    );
}
