import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { useWebSocket } from '../contexts/WebSocketContext.jsx';
import NovaOrb from './NovaOrb';
import MusicStatus from './MusicStatus';
import { pageEntrance, panelEntrance } from '../motionPresets.js';
import {
    ALERT_REFRESH_MS,
    WEATHER_REFRESH_MS,
    fetchLatestAlerts,
    fetchLatestWeather,
    getAlertsCache,
    getWeatherCache,
    isCacheFresh,
} from '../integrationCache.js';

const ALERT_REGION_STORAGE_KEY = 'nova.alertRegion';
const DEFAULT_HOME_ALERT_REGION = 'nacka';
const INTERRUPTIBLE_VOICE_STATES = new Set(['thinking', 'generating', 'speaking']);

function normalizeAlertRegion(region) {
    if (region === 'nacka' || region === 'stockholm' || region === 'sweden') return region;
    return DEFAULT_HOME_ALERT_REGION;
}

function readHomeAlertRegion() {
    try {
        return normalizeAlertRegion(localStorage.getItem(ALERT_REGION_STORAGE_KEY) || DEFAULT_HOME_ALERT_REGION);
    } catch {
        return DEFAULT_HOME_ALERT_REGION;
    }
}

function isExtremeAlert(item) {
    return String(item?.priority_label || item?.priority || '').trim().toUpperCase() === 'EXTREME';
}

function isVmaAlert(item) {
    return String(item?.source || '').toLowerCase().includes('vma');
}

export default function Home() {
    const { voiceStatus, voiceStage, toggleVoice } = useWebSocket();
    const [weather, setWeather] = useState(() => getWeatherCache()?.data || null);
    const [homeAlertRegion, setHomeAlertRegion] = useState(readHomeAlertRegion);
    const [alerts, setAlerts] = useState(() => getAlertsCache(readHomeAlertRegion())?.items || []);
    const [alertsError, setAlertsError] = useState(null);
    const [musicPlaying, setMusicPlaying] = useState(false);

    useEffect(() => {
        let mounted = true;
        async function loadData() {
            const cachedWeather = getWeatherCache();
            const cachedAlerts = getAlertsCache(homeAlertRegion);

            if (cachedWeather?.data) setWeather(cachedWeather.data);
            if (cachedAlerts?.items) {
                setAlerts(cachedAlerts.items);
                setAlertsError(null);
            }

            const requests = [];
            if (!isCacheFresh(cachedWeather, WEATHER_REFRESH_MS)) {
                requests.push(
                    fetchLatestWeather()
                        .then((entry) => ({ type: 'weather', entry }))
                        .catch((error) => ({ type: 'weather', error }))
                );
            }
            if (!isCacheFresh(cachedAlerts, ALERT_REFRESH_MS)) {
                requests.push(
                    fetchLatestAlerts(homeAlertRegion)
                        .then((entry) => ({ type: 'alerts', entry }))
                        .catch((error) => ({ type: 'alerts', error }))
                );
            }
            if (requests.length === 0) return;

            const results = await Promise.allSettled(requests);

            if (!mounted) return;

            results.forEach((result) => {
                if (result?.status !== 'fulfilled' || !result.value) return;
                const { type, entry, error } = result.value;
                if (type === 'weather') {
                    if (entry?.data) {
                        setWeather(entry.data);
                    } else if (error) {
                        console.error('Weather load failed', error);
                        const fallback = getWeatherCache();
                        setWeather(fallback?.data || null);
                    }
                }
                if (type === 'alerts') {
                    if (entry?.items) {
                        setAlerts(entry.items);
                        setAlertsError(null);
                    } else if (error) {
                        console.error('Alerts load failed', error);
                        const fallback = getAlertsCache(homeAlertRegion);
                        if (fallback?.items) {
                            setAlerts(fallback.items);
                            setAlertsError(null);
                        } else {
                            setAlerts([]);
                            setAlertsError('Could not load alerts right now.');
                        }
                    }
                }
            });
        }
        loadData();
        const timer = setInterval(loadData, WEATHER_REFRESH_MS);
        return () => {
            mounted = false;
            clearInterval(timer);
        };
    }, [homeAlertRegion]);

    useEffect(() => {
        const syncAlertRegion = () => {
            setHomeAlertRegion(readHomeAlertRegion());
        };
        window.addEventListener('storage', syncAlertRegion);
        window.addEventListener('focus', syncAlertRegion);
        return () => {
            window.removeEventListener('storage', syncAlertRegion);
            window.removeEventListener('focus', syncAlertRegion);
        };
    }, []);

    const currentWeatherCode = weather?.current?.weather_code ?? 0;
    const alertsSorted = useMemo(() => {
        return [...alerts].sort((a, b) => (b.priority_rank || 0) - (a.priority_rank || 0));
    }, [alerts]);

    const getWeatherEmoji = useCallback((code) => {
        if (code === 0) return '☀️';     // Clear
        if (code === 1 || code === 2) return '🌤️';  // Mostly clear/Partly cloudy
        if (code === 3) return '☁️';     // Overcast
        if (code === 45 || code === 48) return '🌫️';  // Foggy
        if (code >= 51 && code <= 55) return '🌧️';  // Drizzle
        if (code >= 61 && code <= 67) return '🌧️';  // Rain
        if (code >= 71 && code <= 77) return '❄️';   // Snow
        if (code >= 80 && code <= 82) return '⛈️';   // Rain showers
        if (code >= 85 && code <= 86) return '❄️';   // Snow showers
        return '🌤️';
    }, []);

    const onNovaClick = useCallback(() => {
        const shouldInterrupt = (
            INTERRUPTIBLE_VOICE_STATES.has(voiceStatus) ||
            INTERRUPTIBLE_VOICE_STATES.has(voiceStage)
        );
        console.info('[voice] home nova click -> toggleVoice', { interrupt: shouldInterrupt });
        toggleVoice({ interrupt: shouldInterrupt });
    }, [toggleVoice, voiceStage, voiceStatus]);

    const stageLabel = {
        idle: '• SYSTEMS ONLINE',
        listening: '• LISTENING...',
        transcribing: '• STT...',
        thinking: '• THINKING...',
        generating: '• GENERATING RESPONSE...',
        speaking: '• TURNING TTS...',
    }[voiceStage] || '• SYSTEMS ONLINE';

    return (
        <motion.div 
            className="nova-home touch-scroll-y overflow-y-auto h-full min-h-0"
            variants={pageEntrance}
            initial="hidden"
            animate="visible"
            exit="exit"
        >
            {/* Left Section: NOVA Orb + Current Weather */}
            <motion.section 
                className={`nova-home-left ${musicPlaying ? 'nova-home-left-music' : 'nova-home-left-idle'}`}
                data-home-control-mode={musicPlaying ? 'music' : 'nova'}
                variants={panelEntrance}
                layout
                transition={{ layout: { type: 'spring', stiffness: 210, damping: 28 } }}
            >
                <motion.div
                    className={`nova-orb-section ${musicPlaying ? 'nova-orb-section-music' : 'nova-orb-section-idle'}`}
                    variants={panelEntrance}
                    layout
                    transition={{ type: 'spring', stiffness: 210, damping: 28 }}
                >
                    <motion.div
                        className="nova-orb-stage"
                        layout
                        animate={{ y: -6 }}
                        transition={{ type: 'spring', stiffness: 220, damping: 26 }}
                    >
                        <NovaOrb voiceState={voiceStatus} onClick={onNovaClick} />
                    </motion.div>
                    <motion.div
                        className="nova-orb-status"
                        layout
                        animate={{ y: -4 }}
                        transition={{ type: 'spring', stiffness: 220, damping: 28 }}
                    >
                        {stageLabel}
                    </motion.div>
                </motion.div>

                <MusicStatus onPlaybackStateChange={setMusicPlaying} />

            </motion.section>

            {/* Right Section: Today + Alerts */}
            <motion.section 
                className="nova-home-right"
                variants={panelEntrance}
            >
                <motion.div
                    className="weather-today-card"
                    variants={panelEntrance}
                >
                    <div className="weather-today-head">
                        <div>
                            <div className="rain-chance-label">TODAY'S WEATHER</div>
                            <div className="weather-today-subtitle">Stockholm</div>
                        </div>
                        <div className="weather-today-icon">{getWeatherEmoji(currentWeatherCode)}</div>
                    </div>

                    <div className="weather-today-grid">
                        <div className="weather-today-item">
                            <span className="weather-today-item-label">Rain</span>
                            <span className="weather-today-item-value">{weather?.daily?.precipitation_probability_max?.[0] ?? '-'}%</span>
                        </div>
                        <div className="weather-today-item">
                            <span className="weather-today-item-label">Wind</span>
                            <span className="weather-today-item-value">{typeof weather?.current?.wind_speed_10m === 'number' ? Math.round(weather.current.wind_speed_10m) : '-'} km/h</span>
                        </div>
                        <div className="weather-today-item">
                            <span className="weather-today-item-label">Feels like</span>
                            <span className="weather-today-item-value">{typeof weather?.current?.apparent_temperature === 'number' ? Math.round(weather.current.apparent_temperature) : '-'}°</span>
                        </div>
                        <div className="weather-today-item">
                            <span className="weather-today-item-label">Humidity</span>
                            <span className="weather-today-item-value">{weather?.current?.relative_humidity_2m ?? '-'}%</span>
                        </div>
                    </div>
                </motion.div>

                {/* Swedish Alerts */}
                <motion.div 
                    className="alerts-ticker"
                    variants={panelEntrance}
                >
                    <div className="text-xs opacity-70 mb-2 font-semibold tracking-[0.18em]">ALERTS</div>
                    <div className="alerts-ticker-list space-y-1">
                        {alertsError && <div className="text-xs opacity-70">{alertsError}</div>}
                        {alertsSorted.length > 0 ? alertsSorted.map((item, idx) => {
                            const extreme = isExtremeAlert(item);
                            const vma = isVmaAlert(item);
                            const priorityLabel = String(item.priority_label || '').trim();
                            return (
                                <div
                                    key={`${item.title}-${idx}`}
                                    className={`alert-item alert-item-static ${extreme ? 'alert-item-extreme' : ''}`}
                                >
                                    {extreme && (
                                        <div className="alert-emergency-kicker">
                                            <span>{vma ? 'VMA' : 'EXTREME ALERT'}</span>
                                            <span>GLOBAL</span>
                                        </div>
                                    )}
                                    <div className="alert-row-top">
                                        <span className="alert-source">{item.source || 'Alert'}</span>
                                        {priorityLabel ? <span className="alert-priority">{priorityLabel}</span> : null}
                                    </div>
                                    <span className="alert-title">{item.title}</span>
                                    {extreme && item.location && <span className="alert-emergency-location">{item.location}</span>}
                                </div>
                            );
                        }) : <div className="text-xs opacity-50">No items yet</div>}
                    </div>
                </motion.div>
            </motion.section>
        </motion.div>
    );
}
