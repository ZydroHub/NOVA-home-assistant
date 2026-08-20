import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Pencil, Trash2, Check, X, Plus } from 'lucide-react';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import { useFocusableInput } from '../contexts/KeyboardContext.jsx';
import { itemEntrance, tactile } from '../motionPresets.js';

export default function ChatSidebar({ isOpen, onClose }) {
    const { onFocus: onKeyboardFocus, onBlur: onKeyboardBlur } = useFocusableInput(false);
    const {
        conversations,
        currentConvId,
        setCurrentConvId,
        createConversation,
        deleteConversation,
        renameConversation,
        lastApiError,
        clearApiError,
    } = useWebSocket();

    const [editingId, setEditingId] = useState(null);
    const [editTitle, setEditTitle] = useState('');

    const handleNewChat = async () => {
        const conv = await createConversation();
        if (conv) {
            setCurrentConvId(conv.id);
            onClose(); // Close sidebar on mobile/small screens if needed, but here we just follow user request
        }
    };

    const startEditing = (e, conv) => {
        e.stopPropagation();
        setEditingId(conv.id);
        setEditTitle(conv.title || "Untitled Chat");
    };

    const cancelEditing = (e) => {
        e.stopPropagation();
        setEditingId(null);
        setEditTitle('');
    };

    const saveRename = async (e, id) => {
        e.stopPropagation();
        if (editTitle.trim()) {
            await renameConversation(id, editTitle.trim());
        }
        setEditingId(null);
        setEditTitle('');
    };

    return (
        <>
            {/* Backdrop for overlay effect */}
            {isOpen && (
                <div
                    className="fixed inset-0 z-40 bg-black/55 backdrop-blur-sm lg:hidden"
                    onClick={onClose}
                />
            )}

            {/* Sidebar Overlay - slides in from the right */}
            <aside
                className={`fixed right-3 top-[76px] bottom-3 z-50 flex w-80 max-w-[88vw] flex-col overflow-hidden rounded-[28px] border border-white/[0.1] bg-slate-950/70 shadow-[0_24px_80px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-xl transition-transform duration-300 ease-out ${isOpen ? 'translate-x-0' : 'translate-x-[calc(100%+1rem)]'}`}
            >
                <div className="border-b border-white/[0.08] bg-white/[0.035] p-4">
                    <div className="mb-4 flex items-center justify-between gap-3">
                        <div>
                            <div className="text-[0.65rem] font-black uppercase tracking-[0.22em] text-cyan-100/55">
                                Conversation Core
                            </div>
                            <div className="mt-1 text-lg font-black tracking-tight text-white">
                                Chat Memory
                            </div>
                        </div>
                        <motion.button
                            type="button"
                            onClick={onClose}
                            className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/[0.1] bg-white/[0.04] text-cyan-100 transition-all hover:border-cyan-300/50 hover:bg-cyan-300/10 active:scale-95"
                            aria-label="Close conversations"
                            {...tactile}
                        >
                            <X size={19} />
                        </motion.button>
                    </div>
                    {lastApiError && (
                        <div className="mb-3 flex items-center justify-between gap-2 rounded-2xl border border-rose-300/30 bg-rose-500/15 p-3 text-xs font-semibold text-rose-100">
                            <span className="flex-1 truncate" title={lastApiError}>{lastApiError}</span>
                            <motion.button type="button" onClick={clearApiError} className="shrink-0 rounded-lg p-1 transition-colors hover:bg-rose-300/15" aria-label="Dismiss" {...tactile}><X size={14} /></motion.button>
                        </div>
                    )}
                    <motion.button
                        onClick={handleNewChat}
                        className="flex min-h-[56px] w-full items-center justify-center gap-2 rounded-2xl border border-cyan-200/60 bg-cyan-300 px-4 py-3 text-sm font-black uppercase tracking-[0.14em] text-slate-950 shadow-[0_0_30px_rgba(26,209,255,0.28)] transition-all hover:bg-white hover:shadow-[0_0_40px_rgba(26,209,255,0.42)] active:scale-[0.98]"
                        {...tactile}
                    >
                        <Plus size={18} /> New Chat
                    </motion.button>
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 custom-scrollbar touch-scroll-y">
                    {conversations.map((conv, index) => (
                        <motion.div
                            key={conv.id}
                            custom={index}
                            variants={itemEntrance}
                            initial="hidden"
                            animate="visible"
                            whileTap={{ scale: 0.975 }}
                            className={`group relative flex min-h-[64px] cursor-pointer items-center justify-between gap-3 overflow-hidden rounded-2xl border p-3 transition-all ${currentConvId === conv.id
                                ? 'border-cyan-300/70 bg-cyan-300/[0.12] shadow-[0_0_24px_rgba(26,209,255,0.16)]'
                                : 'border-white/[0.08] bg-white/[0.035] hover:border-cyan-300/35 hover:bg-cyan-300/[0.07]'
                                }`}
                            onClick={() => { setCurrentConvId(conv.id); }}
                        >
                            <div className={`absolute inset-y-3 left-0 w-[3px] rounded-full transition-opacity ${currentConvId === conv.id ? 'bg-cyan-300 opacity-100 shadow-[0_0_14px_rgba(26,209,255,0.85)]' : 'bg-cyan-300/50 opacity-0 group-hover:opacity-80'}`} />
                            {editingId === conv.id ? (
                                <div className="flex items-center gap-1 w-full" onClick={e => e.stopPropagation()}>
                                    <input
                                        type="text"
                                        className="min-h-[42px] w-full rounded-xl border border-cyan-300/25 bg-slate-950/60 px-3 py-2 text-sm font-semibold text-white outline-none transition-colors placeholder:text-cyan-100/35 focus:border-cyan-300/60"
                                        value={editTitle}
                                        onChange={e => setEditTitle(e.target.value)}
                                        onFocus={onKeyboardFocus}
                                        onBlur={onKeyboardBlur}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter') saveRename(e, conv.id);
                                            if (e.key === 'Escape') cancelEditing(e);
                                        }}
                                        autoFocus
                                    />
                                    <motion.button onClick={e => saveRename(e, conv.id)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-300/25 bg-emerald-300/10 text-emerald-200 transition-colors hover:bg-emerald-300/20" {...tactile}>
                                        <Check size={16} />
                                    </motion.button>
                                    <motion.button onClick={e => cancelEditing(e)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-rose-300/25 bg-rose-300/10 text-rose-200 transition-colors hover:bg-rose-300/20" {...tactile}>
                                        <X size={16} />
                                    </motion.button>
                                </div>
                            ) : (
                                <>
                                    <div className="min-w-0 flex-1 pl-2">
                                        <div className="truncate text-sm font-bold text-cyan-50">{conv.title || "Untitled Chat"}</div>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                                        <motion.button
                                            onClick={(e) => startEditing(e, conv)}
                                            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-cyan-100 transition-colors hover:border-cyan-300/40 hover:bg-cyan-300/10"
                                            title="Rename"
                                            {...tactile}
                                        >
                                            <Pencil size={14} />
                                        </motion.button>
                                        <motion.button
                                            onClick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
                                            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-cyan-100 transition-colors hover:border-rose-300/40 hover:bg-rose-300/10 hover:text-rose-200"
                                            title="Delete"
                                            {...tactile}
                                        >
                                            <Trash2 size={14} />
                                        </motion.button>
                                    </div>
                                </>
                            )}
                        </motion.div>
                    ))}
                </div>
            </aside>

            <style>{`
                .custom-scrollbar::-webkit-scrollbar {
                    width: 6px;
                }
                .custom-scrollbar::-webkit-scrollbar-track {
                    background: transparent;
                }
                .custom-scrollbar::-webkit-scrollbar-thumb {
                    background: rgba(124, 224, 255, 0.32);
                    border-radius: 3px;
                }
            `}</style>
        </>
    );
}
