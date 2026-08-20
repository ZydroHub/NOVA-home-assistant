import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Clock, Activity, Power, Save } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import { useFocusableInput } from '../contexts/KeyboardContext.jsx';

export default function HeartbeatManager() {
    const navigate = useNavigate();
    const { sendMessage, addEventListener } = useWebSocket();
    const { onFocus: onKeyboardFocus, onBlur: onKeyboardBlur } = useFocusableInput(false);
    const [status, setStatus] = useState({ active: false, schedule: null });
    const [intervalStart, setIntervalStart] = useState(30);

    const checkStatus = useCallback(() => sendMessage("heartbeat.get", {}), [sendMessage]);

    useEffect(() => {
        checkStatus();

        const removeStatusListener = addEventListener("heartbeat_status", (data) => {
            setStatus(data.status);
            // Parse interval from schedule if possible: */30 * * * *
            if (data.status.schedule) {
                const match = data.status.schedule.match(/\*\/(\d+)/);
                if (match) {
                    setIntervalStart(parseInt(match[1]));
                }
            }
        });

        const removeUpdateListener = addEventListener("heartbeat_updated", () => {
            // Refresh
            checkStatus();
        });

        return () => {
            removeStatusListener();
            removeUpdateListener();
        };
    }, [checkStatus, addEventListener]);

    const handleSave = () => {
        sendMessage("heartbeat.set", {
            active: status.active,
            interval: intervalStart
        });
    };

    const toggleActive = () => {
        const newActive = !status.active;
        setStatus({ ...status, active: newActive });
        // Auto-save on toggle? Or let user click save? 
        // Let's auto-save for better UX on toggle
        sendMessage("heartbeat.set", {
            active: newActive,
            interval: intervalStart
        });
    };

    return (
        <div className="w-full h-full mx-auto flex flex-col bg-[var(--pixel-bg)] text-[var(--pixel-text)] font-['VT323'] relative overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between p-4 bg-[var(--pixel-surface)] border-b-4 border-[var(--pixel-border)] z-10">
                <div className="flex items-center">
                    <button
                        onClick={() => navigate('/')}
                        className="pixel-btn p-2 mr-4"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="text-xl font-['Press_Start_2P'] text-[var(--pixel-primary)] uppercase">Heartbeat</h1>
                </div>
                <div className="flex items-center gap-2">
                    <Activity size={20} className={status.active ? "animate-pulse text-[var(--pixel-accent)]" : "text-[var(--pixel-border)]"} />
                </div>
            </div>

            <div className="flex-1 p-6 flex flex-col items-center justify-center relative">

                {/* Background Grid Pattern */}
                <div className="absolute inset-0 opacity-10 pointer-events-none" style={{
                    backgroundImage: `linear-gradient(var(--pixel-border) 1px, transparent 1px), linear-gradient(90deg, var(--pixel-border) 1px, transparent 1px)`,
                    backgroundSize: '20px 20px'
                }} />

                <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="w-full max-w-sm bg-[var(--pixel-surface)] p-8 border-4 border-[var(--pixel-border)] shadow-[8px_8px_0_0_rgba(0,0,0,0.5)] relative"
                >
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[var(--pixel-bg)] px-2 text-[var(--pixel-primary)] font-['Press_Start_2P'] text-xs border-2 border-[var(--pixel-border)] uppercase">
                        SYSTEM STATUS
                    </div>

                    <div className="flex flex-col items-center text-center mt-4">
                        <div className={`w-24 h-24 border-4 border-[var(--pixel-text)] flex items-center justify-center mb-6 transition-colors duration-500 ${status.active ? 'bg-[var(--pixel-accent)] text-black shadow-[4px_4px_0_0_rgba(0,0,0,1)]' : 'bg-[var(--pixel-bg)] text-[var(--pixel-border)]'}`}>
                            <Activity size={48} className={status.active ? "animate-bounce" : ""} />
                        </div>

                        <h2 className="text-2xl font-['Press_Start_2P'] text-[var(--pixel-text)] mb-4 uppercase">
                            {status.active ? "ONLINE" : "OFFLINE"}
                        </h2>
                        <p className="text-[var(--pixel-secondary)] text-lg mb-8 uppercase leading-tight">
                            {status.active
                                ? "AUTOMATED SYSTEM CHECK: ENABLED"
                                : "AUTOMATED SYSTEM CHECK: DISABLED"}
                        </p>

                        {/* Controls */}
                        <div className="w-full space-y-6">
                            <div className="flex items-center justify-between p-4 bg-[var(--pixel-bg)] border-2 border-[var(--pixel-border)]">
                                <span className="text-xl font-medium uppercase">Active</span>
                                <button
                                    onClick={toggleActive}
                                    className={`w-16 h-8 border-2 border-[var(--pixel-text)] relative transition-all active:translate-y-1 ${status.active ? 'bg-[var(--pixel-primary)]' : 'bg-[var(--pixel-surface)]'}`}
                                >
                                    <div className={`absolute top-0 bottom-0 w-1/2 bg-black transition-all ${status.active ? 'right-0' : 'left-0'}`} />
                                </button>
                            </div>

                            <div className={`transition-opacity duration-300 ${status.active ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                                <label className="text-xs font-['Press_Start_2P'] text-[var(--pixel-secondary)] uppercase mb-2 block text-left">
                                    INTERVAL (MIN)
                                </label>
                                <div className="flex gap-2">
                                    <input
                                        type="number"
                                        min="1"
                                        max="1440"
                                        value={intervalStart}
                                        onChange={(e) => setIntervalStart(parseInt(e.target.value))}
                                        onFocus={onKeyboardFocus}
                                        onBlur={onKeyboardBlur}
                                        className="flex-1 p-3 bg-[var(--pixel-bg)] border-2 border-[var(--pixel-border)] text-center text-xl text-[var(--pixel-text)] focus:border-[var(--pixel-primary)] outline-none font-bold"
                                    />
                                    <button
                                        onClick={handleSave}
                                        className="pixel-btn bg-[var(--pixel-primary)] text-black px-4 flex items-center justify-center"
                                    >
                                        <Save size={18} />
                                    </button>
                                </div>
                            </div>
                        </div>

                    </div>
                </motion.div>

            </div>
        </div>
    );
}
