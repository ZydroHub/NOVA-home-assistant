import React, { useState, useEffect } from 'react';
import { Thermometer, Clock } from 'lucide-react';
import { apiFetch, authorizedWebSocketUrl } from '../apiClient.js';
import { WS_BASE_URL } from '../config.js';

const toFiniteNumber = (value, fallback = 0) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const StatusBar = () => {
    const [stats, setStats] = useState({
        time: new Date().toLocaleTimeString('en-GB', { hour12: false }),
        cpu_percent: 0,
        memory_percent: 0,
        temperature: 0
    });

    useEffect(() => {
        let ws = null;
        let fallbackInterval = null;
        let timeInterval = null;
        let isMounted = true;

        const applyStats = (data) => {
            if (!isMounted) return;
            setStats({
                time: data.time || new Date().toLocaleTimeString('en-GB', { hour12: false }),
                cpu_percent: toFiniteNumber(data.cpu_percent ?? data.cpu ?? 0),
                memory_percent: toFiniteNumber(data.memory_percent ?? data.ram ?? 0),
                temperature: toFiniteNumber(data.temperature ?? data.temp ?? 0)
            });
        };

        const fetchStats = async () => {
            try {
                const data = await apiFetch('/system/stats');
                applyStats(data);
            } catch (error) {
                console.error('Stats fetch failed:', error);
            }
        };

        // Immediate first fetch
        fetchStats();

        // Update time every second
        timeInterval = setInterval(() => {
            if (isMounted) {
                setStats(prev => ({
                    ...prev,
                    time: new Date().toLocaleTimeString('en-GB', { hour12: false })
                }));
            }
        }, 1000);

        const startFallbackPolling = () => {
            if (isMounted && !fallbackInterval) {
                fallbackInterval = setInterval(fetchStats, 10000);
            }
        };

        const connectStatsWebSocket = async () => {
            try {
                const url = await authorizedWebSocketUrl(`${WS_BASE_URL}/ws/system-stats`);
                if (!isMounted) return;
                ws = new WebSocket(url);
                ws.onopen = () => {
                    console.log('Stats WebSocket connected');
                };
                ws.onmessage = (event) => {
                    try {
                        const payload = JSON.parse(event.data);
                        applyStats(payload);
                    } catch (err) {
                        console.error('Stats parse error:', err);
                    }
                };
                ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    startFallbackPolling();
                };
                ws.onclose = () => {
                    console.log('Stats WebSocket disconnected');
                    startFallbackPolling();
                };
            } catch (err) {
                console.error('WebSocket init failed:', err);
                startFallbackPolling();
            }
        };
        connectStatsWebSocket();

        return () => {
            isMounted = false;
            if (ws) {
                ws.onopen = null;
                ws.onmessage = null;
                ws.onerror = null;
                ws.onclose = null;
                ws.close();
            }
            if (fallbackInterval) {
                clearInterval(fallbackInterval);
            }
            if (timeInterval) {
                clearInterval(timeInterval);
            }
        };
    }, []);

    // Helper to determine color based on usage/temp
    const getStatusColor = (value, type) => {
        if (type === 'temp') {
            if (value > 80) return 'text-red-500';
            if (value > 60) return 'text-yellow-500';
            return 'text-green-500';
        }
        // usage percentage
        if (value > 80) return 'text-red-500';
        if (value > 50) return 'text-yellow-500';
        return 'text-green-500';
    };

    return (
        <div className="w-full h-11 bg-[var(--nova-glass)] z-50 flex items-center justify-between px-4 text-sm border-b border-white/20 select-none backdrop-blur-xl">

            {/* Time */}
            <div className="flex items-center gap-2 text-cyan-200/90">
                <Clock size={16} />
                <span className="tracking-wide">{stats.time}</span>
            </div>

            {/* System Stats Container */}
            <div className="flex items-center gap-5">

                {/* CPU */}
                <div className="flex items-center gap-1 text-[var(--nova-text)]">
                    <span className="text-cyan-200/70">CPU:</span>
                    <span className={`${getStatusColor(stats.cpu_percent, 'usage')}`}>
                        {Math.round(stats.cpu_percent)}%
                    </span>
                </div>

                {/* RAM */}
                <div className="flex items-center gap-1 text-[var(--nova-text)]">
                    <span className="text-cyan-200/70">RAM:</span>
                    <span className={`${getStatusColor(stats.memory_percent, 'usage')}`}>
                        {Math.round(stats.memory_percent)}%
                    </span>
                </div>

                {/* Temp */}
                <div className="flex items-center gap-1 text-[var(--nova-text)]">
                    <Thermometer size={14} className="text-cyan-200/70" />
                    <span className={`${getStatusColor(stats.temperature, 'temp')}`}>
                        {Math.round(stats.temperature)}°
                    </span>
                </div>

            </div>
        </div>
    );
};

export default StatusBar;
