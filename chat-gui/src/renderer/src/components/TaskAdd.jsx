import React, { useEffect, useState, useRef, useCallback } from 'react';
import { ArrowLeft, MessageSquare } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import { useFocusableInput, useKeyboardSettings } from '../contexts/KeyboardContext.jsx';
import VirtualKeyboard from './VirtualKeyboard.jsx';

function jobToFormState(job) {
    if (!job) return { name: '', description: '', scheduleType: 'every', intervalValue: 30, intervalUnit: 'minutes', targetDate: '', agentMessage: '' };
    const s = job.schedule || {};
    const payload = job.payload || {};
    let scheduleType = 'every';
    let intervalValue = 30;
    let intervalUnit = 'minutes';
    let targetDate = '';
    if (s.kind === 'at' && s.atMs != null) {
        scheduleType = 'at';
        const d = new Date(s.atMs);
        targetDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    } else if (s.kind === 'every' && s.everyMs != null) {
        const ms = s.everyMs;
        const days = ms / (1000 * 60 * 60 * 24);
        const hours = ms / (1000 * 60 * 60);
        const mins = ms / (1000 * 60);
        if (days >= 1 && Math.abs(days - Math.round(days)) < 0.01) {
            intervalValue = Math.round(days);
            intervalUnit = 'days';
        } else if (hours >= 1 && Math.abs(hours - Math.round(hours)) < 0.01) {
            intervalValue = Math.round(hours);
            intervalUnit = 'hours';
        } else {
            intervalValue = Math.max(1, Math.round(mins));
            intervalUnit = 'minutes';
        }
    }
    const agentMessage = (payload && (payload.message || payload.text)) || '';
    return { name: job.name || '', description: job.description || '', scheduleType, intervalValue, intervalUnit, targetDate, agentMessage };
}

export default function TaskAdd() {
    const navigate = useNavigate();
    const location = useLocation();
    const editJob = location.state?.job;
    const isEdit = !!editJob;
    const initial = jobToFormState(editJob);

    useEffect(() => {
        if (location.pathname === '/tasks/edit' && !editJob) {
            navigate('/tasks', { replace: true });
        }
    }, [location.pathname, editJob, navigate]);
    const formRef = useRef(null);
    const scrollContainerRef = useRef(null);
    const dragScrollRef = useRef(null);
    const { sendMessage, addEventListener } = useWebSocket();
    const { onFocus: onKeyboardFocus, onBlur: onKeyboardBlur } = useFocusableInput(false);
    const { keyboardEnabled, focusState, setFocusState, focusedElementRef, syncInputValueRef } = useKeyboardSettings();
    const showInlineKeyboard = keyboardEnabled && !!focusState;

    // When keyboard opens, scroll the focused field into view so it stays above the keyboard
    const scrollFocusedIntoView = useCallback((el) => {
        if (!el) return;
        const timer = setTimeout(() => {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 150);
        return () => clearTimeout(timer);
    }, []);

    const bindKeyboardSync = (setState) => ({
        onFocus: (e) => {
            onKeyboardFocus(e);
            syncInputValueRef.current = (v) => setState(v ?? '');
            scrollFocusedIntoView(e.target);
        },
        onBlur: (e) => {
            onKeyboardBlur(e);
            syncInputValueRef.current = null;
        },
    });
    const bindKeyboardSyncNumber = (setState) => ({
        onFocus: (e) => {
            onKeyboardFocus(e);
            syncInputValueRef.current = (v) => setState(Math.max(1, parseInt(String(v), 10) || 1));
            scrollFocusedIntoView(e.target);
        },
        onBlur: (e) => {
            onKeyboardBlur(e);
            syncInputValueRef.current = null;
        },
    });

    const [name, setName] = useState(initial.name);
    const [description, setDescription] = useState(initial.description);
    const [scheduleType, setScheduleType] = useState(initial.scheduleType);
    const [intervalValue, setIntervalValue] = useState(initial.intervalValue);
    const [intervalUnit, setIntervalUnit] = useState(initial.intervalUnit);
    const [targetDate, setTargetDate] = useState(initial.targetDate);
    const [agentMessage, setAgentMessage] = useState(initial.agentMessage);

    useEffect(() => {
        const removeAdded = addEventListener('task_added', (data) => {
            if (data.result) navigate('/tasks', { replace: true });
        });
        const removeUpdated = addEventListener('task_updated', (data) => {
            if (data.result) navigate('/tasks', { replace: true });
        });
        return () => {
            removeAdded();
            removeUpdated();
        };
    }, [addEventListener, navigate]);

    const handleSubmit = (e) => {
        e.preventDefault();
        let schedule = null;
        if (scheduleType === 'every') {
            let ms = intervalValue * 1000 * 60;
            if (intervalUnit === 'hours') ms *= 60;
            if (intervalUnit === 'days') ms *= 60 * 24;
            schedule = { kind: 'every', everyMs: ms };
        } else if (scheduleType === 'at') {
            schedule = { kind: 'at', atMs: new Date(targetDate).getTime() };
        }
        const payload = agentMessage ? { kind: 'agentTurn', message: agentMessage } : {};
        if (Object.keys(payload).length === 0 && !confirm('No agent message provided. Save anyway?')) return;
        if (isEdit) {
            sendMessage('task.update', { id: editJob.id, name, description, schedule, payload });
        } else {
            sendMessage('task.add', { name, description, schedule, payload });
        }
    };

    const handleFormKeyDown = useCallback((e) => {
        if (e.key !== 'Enter') return;
        const target = e.target;
        if (target?.tagName !== 'INPUT' && target?.tagName !== 'TEXTAREA') return;
        if (target?.type === 'datetime-local') return;
        e.preventDefault();
        formRef.current?.requestSubmit();
    }, []);

    const closeKeyboard = useCallback(() => {
        setFocusState(null);
        focusedElementRef.current = null;
    }, [setFocusState, focusedElementRef]);

    const handleAreaPointerDown = useCallback(
        (e) => {
            if (!focusState) return;
            const target = e.target;
            if (target?.closest?.('[data-virtual-keyboard]')) return;
            if (target?.closest?.('[data-task-form]')) return;
            if (target?.closest?.('[data-task-scroll]')) return;
            closeKeyboard();
        },
        [focusState, closeKeyboard]
    );

    const onScrollAreaPointerDown = useCallback((e) => {
        if (e.target.closest?.('button, a, input, select, textarea, [role="button"]')) return;
        const el = scrollContainerRef.current;
        if (!el || el.scrollHeight <= el.clientHeight) return;
        dragScrollRef.current = { clientY: e.clientY, scrollTop: el.scrollTop };
        el.setPointerCapture(e.pointerId);
    }, []);
    const onScrollAreaPointerMove = useCallback((e) => {
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
    const onScrollAreaPointerUp = useCallback((e) => {
        if (dragScrollRef.current) {
            scrollContainerRef.current?.releasePointerCapture(e.pointerId);
            dragScrollRef.current = null;
        }
    }, []);

    return (
        <div
            className="w-full h-full flex flex-col bg-[var(--pixel-bg)] text-[var(--pixel-text)] font-['VT323'] overflow-hidden min-h-0"
            onPointerDown={handleAreaPointerDown}
        >
            <header className="flex-shrink-0 flex items-center justify-between px-4 py-4 bg-[var(--pixel-surface)] border-b-4 border-[var(--pixel-border)] z-10">
                <button
                    type="button"
                    onClick={() => navigate('/tasks')}
                    className="pixel-btn p-3 min-h-[48px] min-w-[48px] touch-manipulation"
                    aria-label="Back to tasks"
                >
                    <ArrowLeft size={24} />
                </button>
                <h1 className="text-lg font-['Press_Start_2P'] text-[var(--pixel-primary)] leading-tight">{isEdit ? 'EDIT TASK' : 'NEW TASK'}</h1>
                <div className="w-12" />
            </header>

            <div
                ref={scrollContainerRef}
                data-task-scroll
                className="flex-1 min-h-0 overflow-y-auto p-4 scroller-pixel touch-scroll-y"
                onPointerDown={onScrollAreaPointerDown}
                onPointerMove={onScrollAreaPointerMove}
                onPointerUp={onScrollAreaPointerUp}
                onPointerCancel={onScrollAreaPointerUp}
                onPointerLeave={onScrollAreaPointerUp}
            >
                <div className="bg-[var(--pixel-surface)] border-4 border-[var(--pixel-border)] p-5 shadow-[8px_8px_0_0_rgba(0,0,0,0.5)]" data-task-form>
                    <form ref={formRef} onSubmit={handleSubmit} onKeyDown={handleFormKeyDown} className="space-y-5">
                        <div className="space-y-2">
                            <label className="block text-sm font-['Press_Start_2P'] text-[var(--pixel-border)] uppercase">Name</label>
                            <input
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                {...bindKeyboardSync(setName)}
                                className="w-full p-4 min-h-[48px] text-xl bg-[var(--pixel-bg)] border-2 border-[var(--pixel-border)] text-[var(--pixel-text)] placeholder-[var(--pixel-border)] focus:border-[var(--pixel-primary)] outline-none touch-manipulation"
                                placeholder="TASK NAME..."
                                required
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="block text-sm font-['Press_Start_2P'] text-[var(--pixel-border)] uppercase">Description (optional)</label>
                            <input
                                value={description}
                                onChange={(e) => setDescription(e.target.value)}
                                {...bindKeyboardSync(setDescription)}
                                className="w-full p-4 min-h-[48px] text-xl bg-[var(--pixel-bg)] border-2 border-[var(--pixel-border)] text-[var(--pixel-text)] placeholder-[var(--pixel-border)] focus:border-[var(--pixel-primary)] outline-none touch-manipulation"
                                placeholder="OPTIONAL..."
                            />
                        </div>
                        <div className="space-y-3">
                            <label className="block text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)]">SCHEDULE TYPE</label>
                            <div className="flex bg-[var(--pixel-bg)] p-1.5 border-2 border-[var(--pixel-border)] gap-1">
                                <button
                                    type="button"
                                    onClick={() => setScheduleType('every')}
                                    className={`flex-1 py-4 text-center font-['VT323'] text-xl min-h-[48px] touch-manipulation transition-colors border-2 ${scheduleType === 'every' ? 'bg-[var(--pixel-primary)] text-black border-[var(--pixel-primary)]' : 'border-transparent text-[var(--pixel-text)] hover:bg-[var(--pixel-surface)]'}`}
                                >
                                    INTERVAL
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setScheduleType('at')}
                                    className={`flex-1 py-4 text-center font-['VT323'] text-xl min-h-[48px] touch-manipulation transition-colors border-2 ${scheduleType === 'at' ? 'bg-[var(--pixel-primary)] text-black border-[var(--pixel-primary)]' : 'border-transparent text-[var(--pixel-text)] hover:bg-[var(--pixel-surface)]'}`}
                                >
                                    DATE & TIME
                                </button>
                            </div>
                        </div>
                        {scheduleType === 'every' && (
                            <div className="flex flex-col sm:flex-row gap-4">
                                <div className="flex-1 space-y-2">
                                    <label className="block text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)]">INTERVAL</label>
                                    <input
                                        type="number"
                                        min="1"
                                        value={intervalValue}
                                        onChange={(e) => setIntervalValue(parseInt(e.target.value) || 1)}
                                        {...bindKeyboardSyncNumber(setIntervalValue)}
                                        className="pixel-input w-full min-h-[48px] text-xl p-4 touch-manipulation"
                                    />
                                </div>
                                <div className="flex-1 space-y-2">
                                    <label className="block text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)]">UNIT</label>
                                    <select
                                        value={intervalUnit}
                                        onChange={(e) => setIntervalUnit(e.target.value)}
                                        className="pixel-select w-full min-h-[48px] text-xl p-4 touch-manipulation"
                                    >
                                        <option value="minutes">MINUTES</option>
                                        <option value="hours">HOURS</option>
                                        <option value="days">DAYS</option>
                                    </select>
                                </div>
                            </div>
                        )}
                        {scheduleType === 'at' && (
                            <div className="space-y-2">
                                <label className="block text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)]">DATE & TIME</label>
                                <input
                                    type="datetime-local"
                                    value={targetDate}
                                    onChange={(e) => setTargetDate(e.target.value)}
                                    {...bindKeyboardSync(setTargetDate)}
                                    className="w-full p-4 min-h-[48px] text-xl bg-[var(--pixel-surface)] border-2 border-[var(--pixel-border)] text-[var(--pixel-text)] touch-manipulation"
                                    required={scheduleType === 'at'}
                                />
                            </div>
                        )}
                        <div className="space-y-2">
                            <label className="block text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)] flex items-center gap-2">
                                <MessageSquare size={14} /> Agent Instruction
                            </label>
                            <textarea
                                value={agentMessage}
                                onChange={(e) => setAgentMessage(e.target.value)}
                                {...bindKeyboardSync(setAgentMessage)}
                                className="w-full p-4 bg-[var(--pixel-bg)] border-2 border-[var(--pixel-border)] text-[var(--pixel-text)] text-xl focus:border-[var(--pixel-primary)] outline-none min-h-[100px] resize-none touch-manipulation"
                                placeholder="INSTRUCTIONS FOR AGENT..."
                            />
                        </div>
                        <div className="flex flex-col-reverse sm:flex-row gap-3 pt-2">
                            <button
                                type="button"
                                onClick={() => navigate('/tasks')}
                                className="pixel-btn flex-1 py-4 min-h-[52px] text-sm touch-manipulation bg-[var(--pixel-bg)] text-[var(--pixel-text)]"
                            >
                                CANCEL
                            </button>
                            <button type="submit" className="pixel-btn flex-1 py-4 min-h-[52px] text-sm touch-manipulation bg-[var(--pixel-primary)] text-black">
                                {isEdit ? 'SAVE TASK' : 'ADD TASK'}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            <VirtualKeyboard visible={showInlineKeyboard} mode="inline" focusedElementRef={focusedElementRef} syncInputValueRef={syncInputValueRef} />
        </div>
    );
}
