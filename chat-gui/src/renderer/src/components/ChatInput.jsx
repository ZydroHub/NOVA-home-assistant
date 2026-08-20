import React, { useState, useRef, useCallback, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Mic, SendHorizontal, Square } from 'lucide-react';
import { useFocusableInput, useKeyboardSettings } from '../contexts/KeyboardContext.jsx';
import { tactile } from '../motionPresets.js';

export default function ChatInput({ onSend, onAbort, onMicPress, isRecording, streaming, disabled }) {
    const [text, setText] = useState('');
    const textareaRef = useRef(null);
    const { onFocus: onKeyboardFocus, onBlur: onKeyboardBlur } = useFocusableInput(true);
    const { syncInputValueRef } = useKeyboardSettings();

    // Sync React state when virtual keyboard types (controlled input otherwise stays empty)
    useEffect(() => {
        if (!syncInputValueRef) return;
        const sync = (value) => setText(value ?? '');
        syncInputValueRef.current = sync;
        return () => { syncInputValueRef.current = null; };
    }, [syncInputValueRef]);

    const onFocus = useCallback(
        (e) => {
            onKeyboardFocus(e);
            syncInputValueRef.current = (value) => setText(value ?? '');
            const domValue = textareaRef.current?.value;
            if (domValue !== undefined) setText(domValue);
        },
        [onKeyboardFocus, syncInputValueRef]
    );
    const onBlur = useCallback(
        (e) => {
            onKeyboardBlur(e);
            syncInputValueRef.current = null;
        },
        [onKeyboardBlur, syncInputValueRef]
    );

    const handleSend = useCallback(() => {
        const trimmed = text.trim();
        if (!trimmed || streaming || disabled) return;
        onSend(trimmed);
        setText('');
        // Reset textarea height
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }
    }, [text, streaming, disabled, onSend]);

    const handleKeyDown = useCallback(
        (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        },
        [handleSend]
    );

    const handleInput = useCallback((e) => {
        setText(e.target.value);
        // Auto-resize textarea
        const el = e.target;
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }, []);

    return (
        <div className="flex min-h-[82px] items-end gap-3 border-t border-white/[0.08] bg-slate-950/35 px-3 py-3 pb-[max(12px,env(safe-area-inset-bottom,12px))] backdrop-blur-md" data-chat-input-bar>
            <div className="flex min-h-[56px] flex-1 items-end rounded-[28px] border border-white/[0.1] bg-white/[0.055] px-5 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_14px_36px_rgba(0,0,0,0.22)] transition-all focus-within:border-cyan-300/50 focus-within:bg-cyan-300/[0.06] focus-within:shadow-[0_0_28px_rgba(26,209,255,0.14),inset_0_1px_0_rgba(255,255,255,0.1)]">
                <textarea
                    ref={textareaRef}
                    className="min-h-[34px] max-h-[120px] flex-1 resize-none border-none bg-transparent py-1 font-['Inter'] text-[1rem] leading-relaxed text-white outline-none placeholder:text-cyan-100/35 disabled:cursor-not-allowed"
                    value={text}
                    onChange={handleInput}
                    onKeyDown={handleKeyDown}
                    onFocus={onFocus}
                    onBlur={onBlur}
                    placeholder="Message NOVA..."
                    rows={1}
                    disabled={disabled}
                    autoComplete="off"
                    autoCorrect="off"
                />
            </div>

            {streaming ? (
                <motion.button
                    className="flex h-14 w-14 cursor-pointer items-center justify-center rounded-full border border-rose-300/50 bg-rose-500/80 text-white shadow-[0_0_24px_rgba(244,63,94,0.32)] transition-all hover:bg-rose-400 active:scale-95"
                    onClick={onAbort}
                    aria-label="Stop response"
                    {...tactile}
                >
                    <Square size={20} fill="currentColor" />
                </motion.button>
            ) : (
                <>
                    <motion.button
                        type="button"
                        onClick={onMicPress}
                        aria-label={isRecording ? 'Stop recording' : 'Record voice message'}
                        disabled={disabled}
                        className={`flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-full border touch-manipulation transition-all active:scale-95 disabled:cursor-not-allowed disabled:opacity-45 ${isRecording
                            ? 'nova-breathing-glow-fast border-rose-300/70 bg-rose-500/80 text-white shadow-[0_0_28px_rgba(244,63,94,0.42)]'
                            : 'border-cyan-300/25 bg-white/[0.06] text-cyan-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] hover:border-cyan-300/55 hover:bg-cyan-300/10 hover:shadow-[0_0_22px_rgba(26,209,255,0.18)]'}`}
                        animate={isRecording ? { scale: [1, 1.04, 1] } : { scale: 1 }}
                        transition={isRecording ? { duration: 0.9, repeat: Infinity, ease: 'easeInOut' } : tactile.transition}
                        whileTap={tactile.whileTap}
                    >
                        <Mic size={24} />
                    </motion.button>
                    <motion.button
                        type="button"
                        className="flex h-14 w-14 cursor-pointer items-center justify-center rounded-full border border-cyan-200/60 bg-cyan-300 text-slate-950 shadow-[0_0_26px_rgba(26,209,255,0.32)] transition-all hover:bg-white hover:shadow-[0_0_34px_rgba(26,209,255,0.45)] active:scale-95 disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/10 disabled:text-white/35 disabled:shadow-none touch-manipulation"
                        onClick={handleSend}
                        disabled={!text.trim() || disabled}
                        aria-label="Send message"
                        {...tactile}
                    >
                        <SendHorizontal size={23} />
                    </motion.button>
                </>
            )}
        </div>
    );
}
