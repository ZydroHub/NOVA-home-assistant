import React, { useEffect, useState, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Plus, Trash2, Clock, Zap, Pencil } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';

const formatSchedule = (schedule) => {
    if (!schedule || typeof schedule !== 'object') return 'No schedule';
    if (schedule.kind === 'every') {
        const ms = schedule.everyMs;
        const days = ms / (1000 * 60 * 60 * 24);
        if (days >= 1 && Number.isInteger(days)) return `Every ${days} day${days > 1 ? 's' : ''}`;
        const hours = ms / (1000 * 60 * 60);
        if (hours >= 1 && Number.isInteger(hours)) return `Every ${hours} hour${hours > 1 ? 's' : ''}`;
        const mins = ms / (1000 * 60);
        return `Every ${Math.round(mins)} minute${Math.round(mins) !== 1 ? 's' : ''}`;
    }
    if (schedule.kind === 'at') {
        return `At ${new Date(schedule.atMs).toLocaleString()}`;
    }
    return 'Scheduled';
};

export default function TaskManager() {
    const navigate = useNavigate();
    const scrollContainerRef = useRef(null);
    const dragScrollRef = useRef(null);
    const { sendMessage, addEventListener } = useWebSocket();
    const [jobs, setJobs] = useState([]);

    const onScrollPointerDown = useCallback((e) => {
        if (e.target.closest?.('button, a, input, select, textarea, [role="button"]')) return;
        const el = scrollContainerRef.current;
        if (!el || el.scrollHeight <= el.clientHeight) return;
        dragScrollRef.current = { clientY: e.clientY, scrollTop: el.scrollTop };
        el.setPointerCapture(e.pointerId);
    }, []);
    const onScrollPointerMove = useCallback((e) => {
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
    }, []);
    const onScrollPointerUp = useCallback((e) => {
        if (dragScrollRef.current) {
            scrollContainerRef.current?.releasePointerCapture(e.pointerId);
            dragScrollRef.current = null;
        }
    }, []);

    useEffect(() => {
        sendMessage('task.list', {});

        const removeList = addEventListener('task_list', (data) => {
            setJobs(data.jobs || []);
        });
        const removeRemoved = addEventListener('task_removed', () => {
            sendMessage('task.list', {});
        });
        const removeUpdated = addEventListener('task_updated', () => {
            sendMessage('task.list', {});
        });

        return () => {
            removeList();
            removeRemoved();
            removeUpdated();
        };
    }, [sendMessage, addEventListener]);

    const handleEditJob = (job) => {
        navigate('/tasks/edit', { state: { job } });
    };

    const handleRemoveJob = (id) => {
        if (confirm('Delete this scheduled task?')) {
            sendMessage('task.remove', { id });
        }
    };

    return (
        <div className="w-full h-full mx-auto flex flex-col bg-[var(--pixel-bg)] text-[var(--pixel-text)] font-['VT323'] overflow-hidden min-h-0">
            <div className="flex-shrink-0 flex items-center justify-between px-4 py-4 bg-[var(--pixel-surface)] border-b-4 border-[var(--pixel-border)] z-10">
                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        onClick={() => navigate('/')}
                        className="pixel-btn p-3 min-h-[48px] min-w-[48px] touch-manipulation"
                        aria-label="Back"
                    >
                        <ArrowLeft size={24} />
                    </button>
                    <h1 className="text-lg font-['Press_Start_2P'] text-[var(--pixel-primary)] leading-tight">TASKS</h1>
                </div>
                <button
                    type="button"
                    onClick={() => navigate('/tasks/add')}
                    className="pixel-btn p-3 min-h-[48px] min-w-[48px] touch-manipulation bg-[var(--pixel-accent)] text-black"
                    aria-label="New task"
                >
                    <Plus size={24} />
                </button>
            </div>

            <div
                ref={scrollContainerRef}
                className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 scroller-pixel touch-scroll-y"
                onPointerDown={onScrollPointerDown}
                onPointerMove={onScrollPointerMove}
                onPointerUp={onScrollPointerUp}
                onPointerCancel={onScrollPointerUp}
                onPointerLeave={onScrollPointerUp}
            >
                {jobs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-[var(--pixel-border)]">
                        <Clock size={48} className="mb-4 opacity-50" />
                        <p className="text-xl">NO ACTIVE TASKS</p>
                    </div>
                ) : (
                    jobs.map((job) => (
                        <motion.div
                            key={job.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="bg-[var(--pixel-surface)] p-5 border-4 border-[var(--pixel-border)] shadow-[4px_4px_0_0_rgba(0,0,0,0.5)] group"
                        >
                            <div className="flex justify-between items-start gap-3 mb-3">
                                <div className="min-w-0 flex-1">
                                    <h3 className="font-['Press_Start_2P'] text-[var(--pixel-text)] text-xs mb-1 uppercase leading-relaxed">{job.name}</h3>
                                    {job.description && (
                                        <p className="text-lg text-gray-500 mt-0.5">{job.description}</p>
                                    )}
                                </div>
                                <div className="flex items-center gap-1">
                                    <button
                                        type="button"
                                        onClick={() => handleEditJob(job)}
                                        className="p-3 min-h-[44px] min-w-[44px] flex items-center justify-center text-[var(--pixel-primary)] hover:bg-[var(--pixel-primary)]/20 border-2 border-transparent hover:border-[var(--pixel-primary)] transition-all touch-manipulation"
                                        aria-label="Edit task"
                                    >
                                        <Pencil size={20} />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveJob(job.id)}
                                        className="p-3 min-h-[44px] min-w-[44px] flex items-center justify-center text-red-500 hover:bg-red-900/30 border-2 border-transparent hover:border-red-500 transition-all touch-manipulation"
                                        aria-label="Delete task"
                                    >
                                        <Trash2 size={20} />
                                    </button>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <div className="flex items-center text-sm text-[var(--pixel-secondary)]">
                                    <div className="w-6 flex justify-center mr-2 opacity-70">
                                        <Clock size={16} />
                                    </div>
                                    <span className="font-medium bg-[var(--pixel-bg)] px-2 py-1 border border-[var(--pixel-border)]">
                                        {formatSchedule(job.schedule)}
                                    </span>
                                </div>

                                {job.payload && (
                                    <div className="flex items-start text-sm text-gray-400 mt-1">
                                        <div className="w-6 flex justify-center mr-2 opacity-70 mt-0.5">
                                            <Zap size={16} />
                                        </div>
                                        <div className="flex-1 bg-[var(--pixel-bg)] p-2 border border-[var(--pixel-border)] text-[var(--pixel-primary)] text-sm font-['VT323']">
                                            {job.payload.text || job.payload.message || JSON.stringify(job.payload)}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </motion.div>
                    ))
                )}
            </div>
        </div>
    );
}
