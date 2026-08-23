import React from 'react';
import { motion } from 'framer-motion';
import {
    Activity,
    Bell,
    Brain,
    Check,
    Eye,
    EyeOff,
    Keyboard,
    Languages,
    Loader2,
    MapPin,
    Power,
    Radio,
    ScanLine,
    Send,
    Volume2,
} from 'lucide-react';
import { apiFetch } from '../apiClient.js';
import { useKeyboardSettings } from '../contexts/KeyboardContext.jsx';
import { pageEntrance, panelEntrance, tactile } from '../motionPresets.js';
import { NAV_ITEMS, readHiddenTabs, writeHiddenTabs } from '../navigationSettings.js';

const KEY_SCANLINES_ENABLED = 'nova.scanlinesEnabled';
const KEY_STATUS_BAR_ENABLED = 'nova.statusBarEnabled';
const CONFIGURABLE_NAV_ITEMS = NAV_ITEMS.filter((item) => !item.required);
const VOICE_LANGUAGE_OPTIONS = [
    { value: 'en', title: 'English', description: 'Voice commands in English' },
    { value: 'sv', title: 'Swedish', description: 'Voice commands in Swedish' },
    { value: 'auto', title: 'Auto', description: 'Let Whisper detect speech language' },
];
function readStoredBool(key, defaultValue = true) {
    try {
        const value = localStorage.getItem(key);
        if (value === null) return defaultValue;
        return value === 'true';
    } catch {
        return defaultValue;
    }
}

function Panel({ title, icon: Icon, accent = 'cyan', children, className = '' }) {
    const accentClass = accent === 'emerald' ? 'from-emerald-300/25 to-cyan-300/10' : accent === 'rose' ? 'from-rose-300/25 to-cyan-300/10' : 'from-cyan-300/25 to-sky-300/10';
    return (
        <motion.section variants={panelEntrance} className={`relative overflow-hidden rounded-[28px] border border-cyan-100/[0.14] bg-[rgba(6,13,30,0.62)] p-5 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-2xl ${className}`}>
            <div className={`pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r ${accentClass}`} />
            <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                    <h2 className="mt-1 flex items-center gap-2 font-['Plus_Jakarta_Sans'] text-lg font-bold text-cyan-50">
                        {Icon ? <Icon size={18} className="text-cyan-200/[0.85]" /> : null}
                        {title}
                    </h2>
                </div>
                <div className="h-2 w-2 rounded-full bg-cyan-200 nova-breathing-glow shadow-[0_0_18px_rgba(103,232,249,0.9)]" />
            </div>
            {children}
        </motion.section>
    );
}

function ToggleSwitch({ checked, onChange, disabled = false, label }) {
    return (
        <motion.button
            type="button"
            role="switch"
            aria-label={label}
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            disabled={disabled}
            className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full border transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[rgba(6,13,30,0.96)] disabled:cursor-not-allowed disabled:opacity-55 ${
                checked
                    ? 'border-cyan-200/70 bg-cyan-300/25 shadow-[0_0_26px_rgba(34,211,238,0.24)]'
                    : 'border-white/[0.15] bg-white/5'
            }`}
            {...tactile}
        >
            <span
                className={`pointer-events-none inline-block h-4 w-4 rounded-full border border-white/30 bg-cyan-50 shadow-[0_6px_16px_rgba(0,0,0,0.32)] transition-transform duration-200 ${
                    checked ? 'translate-x-5' : 'translate-x-0.5'
                }`}
            />
        </motion.button>
    );
}

function SettingRow({ icon: Icon, title, description, children }) {
    return (
        <motion.div variants={panelEntrance} className="flex min-h-[64px] items-center justify-between gap-4 rounded-[20px] border border-white/[0.08] bg-white/[0.035] px-4 py-3 transition-colors hover:bg-white/[0.055]">
            <div className="flex min-w-0 items-center gap-3">
                {Icon ? (
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-2xl border border-cyan-100/[0.12] bg-cyan-300/[0.08] text-cyan-100">
                        <Icon size={18} />
                    </div>
                ) : null}
                <div className="min-w-0">
                    <div className="truncate font-['Plus_Jakarta_Sans'] text-sm font-semibold text-cyan-50">{title}</div>
                    {description ? <div className="mt-0.5 text-xs leading-snug text-cyan-100/50">{description}</div> : null}
                </div>
            </div>
            {children}
        </motion.div>
    );
}

export default function Settings() {
    const { keyboardEnabled, setKeyboardEnabled } = useKeyboardSettings();
    const [scanlinesEnabled, setScanlinesEnabled] = React.useState(() => readStoredBool(KEY_SCANLINES_ENABLED, true));
    const [statusBarEnabled, setStatusBarEnabled] = React.useState(() => readStoredBool(KEY_STATUS_BAR_ENABLED, true));
    const [hiddenTabs, setHiddenTabs] = React.useState(readHiddenTabs);
    const [voiceLanguage, setVoiceLanguage] = React.useState('en');
    const [voiceAlwaysListening, setVoiceAlwaysListening] = React.useState(true);
    const [voiceSettingsLoading, setVoiceSettingsLoading] = React.useState(true);
    const [voiceSettingsPending, setVoiceSettingsPending] = React.useState('');
    const [voiceSettingsError, setVoiceSettingsError] = React.useState('');
    const [modelOptions, setModelOptions] = React.useState([]);
    const [selectedModel, setSelectedModel] = React.useState('');
    const [activeModel, setActiveModel] = React.useState('');
    const [modelSettingsLoading, setModelSettingsLoading] = React.useState(true);
    const [modelSettingsPending, setModelSettingsPending] = React.useState(false);
    const [modelSwitching, setModelSwitching] = React.useState(false);
    const [modelSettingsError, setModelSettingsError] = React.useState('');
    const [telegramTestState, setTelegramTestState] = React.useState('idle');
    const [telegramTestError, setTelegramTestError] = React.useState('');
    const [telegramStartupNotifications, setTelegramStartupNotifications] = React.useState(true);
    const [telegramSettingsPending, setTelegramSettingsPending] = React.useState(false);
    const [alertSettings, setAlertSettings] = React.useState({ nacka: true, stockholm: true });
    const [alertSettingsLoading, setAlertSettingsLoading] = React.useState(true);
    const [alertSettingsPending, setAlertSettingsPending] = React.useState('');
    const [alertSettingsError, setAlertSettingsError] = React.useState('');
    const scrollContainerRef = React.useRef(null);
    const dragScrollRef = React.useRef(null);

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

    const endPointerDrag = (e) => {
        if (dragScrollRef.current) {
            scrollContainerRef.current?.releasePointerCapture(e.pointerId);
            dragScrollRef.current = null;
        }
    };

    React.useEffect(() => {
        localStorage.setItem(KEY_SCANLINES_ENABLED, String(scanlinesEnabled));
        window.dispatchEvent(new CustomEvent('nova-settings-updated'));
    }, [scanlinesEnabled]);

    React.useEffect(() => {
        localStorage.setItem(KEY_STATUS_BAR_ENABLED, String(statusBarEnabled));
        window.dispatchEvent(new CustomEvent('nova-settings-updated'));
    }, [statusBarEnabled]);

    React.useEffect(() => {
        const syncHiddenTabs = () => setHiddenTabs(readHiddenTabs());
        window.addEventListener('storage', syncHiddenTabs);
        window.addEventListener('nova-settings-updated', syncHiddenTabs);
        return () => {
            window.removeEventListener('storage', syncHiddenTabs);
            window.removeEventListener('nova-settings-updated', syncHiddenTabs);
        };
    }, []);

    React.useEffect(() => {
        let cancelled = false;

        const loadAlertSettings = async () => {
            try {
                const result = await apiFetch('/settings/alerts');
                if (!cancelled) {
                    setAlertSettings({
                        nacka: Boolean(result?.alerts?.nacka),
                        stockholm: Boolean(result?.alerts?.stockholm),
                    });
                    setTelegramStartupNotifications(result?.telegram?.startup_notifications !== false);
                    setAlertSettingsError('');
                }
            } catch (error) {
                if (!cancelled) {
                    setAlertSettingsError(error?.message || 'Failed to load alert settings.');
                }
            } finally {
                if (!cancelled) {
                    setAlertSettingsLoading(false);
                }
            }
        };

        loadAlertSettings();

        return () => {
            cancelled = true;
        };
    }, []);

    React.useEffect(() => {
        let cancelled = false;

        const loadModelSettings = async () => {
            try {
                const result = await apiFetch('/settings/models');
                if (!cancelled) {
                    setModelOptions(Array.isArray(result?.options) ? result.options : []);
                    setSelectedModel(typeof result?.selected_model === 'string' ? result.selected_model : '');
                    setActiveModel(typeof result?.active_model === 'string' ? result.active_model : '');
                    setModelSwitching(Boolean(result?.switching));
                    setModelSettingsError(result?.error || '');
                }
            } catch (error) {
                if (!cancelled) {
                    setModelSettingsError(error?.message || 'Failed to load chat model settings.');
                }
            } finally {
                if (!cancelled) {
                    setModelSettingsLoading(false);
                }
            }
        };

        loadModelSettings();
        const pollId = window.setInterval(loadModelSettings, 1500);
        return () => {
            cancelled = true;
            window.clearInterval(pollId);
        };
    }, []);

    React.useEffect(() => {
        let cancelled = false;

        const loadVoiceSettings = async () => {
            try {
                const result = await apiFetch('/settings/voice');
                if (!cancelled) {
                    setVoiceLanguage((result?.voice?.language || 'en').toString());
                    setVoiceAlwaysListening(Boolean(result?.voice?.always_listening));
                    setVoiceSettingsError('');
                }
            } catch (error) {
                if (!cancelled) {
                    setVoiceSettingsError(error?.message || 'Failed to load voice language setting.');
                }
            } finally {
                if (!cancelled) {
                    setVoiceSettingsLoading(false);
                }
            }
        };

        loadVoiceSettings();

        return () => {
            cancelled = true;
        };
    }, []);

    const handleVoiceLanguageChange = async (language) => {
        if (!language || language === voiceLanguage || voiceSettingsPending) return;

        setVoiceSettingsPending(language);
        setVoiceSettingsError('');
        try {
            const result = await apiFetch('/settings/voice', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ language }),
            });
            setVoiceLanguage((result?.voice?.language || language).toString());
            window.dispatchEvent(new CustomEvent('nova-settings-updated'));
        } catch (error) {
            setVoiceSettingsError(error?.message || 'Failed to update voice language.');
        } finally {
            setVoiceSettingsPending('');
        }
    };

    const handleVoiceAlwaysListeningChange = async (enabled) => {
        if (voiceSettingsPending) return;

        setVoiceSettingsPending('always_listening');
        setVoiceSettingsError('');
        try {
            const result = await apiFetch('/settings/voice', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ always_listening: enabled }),
            });
            setVoiceAlwaysListening(Boolean(result?.voice?.always_listening));
            window.dispatchEvent(new CustomEvent('nova-settings-updated'));
        } catch (error) {
            setVoiceSettingsError(error?.message || 'Failed to update always listening.');
        } finally {
            setVoiceSettingsPending('');
        }
    };

    const handleModelChange = async (modelId) => {
        if (!modelId || modelSettingsLoading || modelSettingsPending || modelSwitching || modelId === activeModel) return;

        setModelSettingsPending(true);
        setModelSettingsError('');
        try {
            const result = await apiFetch('/settings/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelId }),
            });
            setModelOptions(Array.isArray(result?.options) ? result.options : []);
            setSelectedModel(typeof result?.selected_model === 'string' ? result.selected_model : modelId);
            setActiveModel(typeof result?.active_model === 'string' ? result.active_model : '');
            setModelSwitching(Boolean(result?.switching));
            setModelSettingsError(result?.error || '');
        } catch (error) {
            setModelSettingsError(error?.message || 'Failed to switch chat model.');
        } finally {
            setModelSettingsPending(false);
        }
    };

    const handleAlertSettingChange = async (region, enabled) => {
        if (!region || alertSettingsPending) return;

        setAlertSettingsPending(region);
        setAlertSettingsError('');
        try {
            const result = await apiFetch('/settings/alerts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alerts: { [region]: enabled } }),
            });
            setAlertSettings({
                nacka: Boolean(result?.alerts?.nacka),
                stockholm: Boolean(result?.alerts?.stockholm),
            });
            window.dispatchEvent(new CustomEvent('nova-settings-updated'));
        } catch (error) {
            setAlertSettingsError(error?.message || 'Failed to update alert settings.');
        } finally {
            setAlertSettingsPending('');
        }
    };

    const handleTelegramStartupNotificationsChange = async (enabled) => {
        if (telegramSettingsPending) return;

        setTelegramSettingsPending(true);
        setAlertSettingsError('');
        try {
            const result = await apiFetch('/settings/alerts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram: { startup_notifications: enabled } }),
            });
            setTelegramStartupNotifications(result?.telegram?.startup_notifications !== false);
            window.dispatchEvent(new CustomEvent('nova-settings-updated'));
        } catch (error) {
            setAlertSettingsError(error?.message || 'Failed to update Telegram settings.');
        } finally {
            setTelegramSettingsPending(false);
        }
    };

    const handleTabVisibilityChange = (tabId, visible) => {
        setHiddenTabs((currentHiddenTabs) => {
            const hidden = new Set(currentHiddenTabs);
            if (visible) {
                hidden.delete(tabId);
            } else {
                hidden.add(tabId);
            }
            const nextHiddenTabs = Array.from(hidden);
            writeHiddenTabs(nextHiddenTabs);
            return nextHiddenTabs;
        });
    };

    const handleCloseApp = async () => {
        try {
            await apiFetch('/shutdown', { method: 'POST' });
        } catch (e) {
            console.error('Failed to notify backend of shutdown:', e);
        }

        if (window.electron && window.electron.quit) {
            window.electron.quit();
        } else {
            console.log('Close button clicked (Electron API not available)');
            window.close();
        }
    };

    const handleTelegramTest = async () => {
        setTelegramTestState('loading');
        setTelegramTestError('');
        try {
            const result = await apiFetch('/telegram/test-message', { method: 'POST' });
            const sentCount = Number(result?.sent || 0);
            setTelegramTestState(sentCount > 0 ? 'sent' : 'error');
            if (sentCount > 0) {
                setTelegramTestError(`Sent test message to ${sentCount} chat${sentCount === 1 ? '' : 's'}.`);
            } else {
                setTelegramTestError('No subscribed Telegram chats were found. Open Telegram and send /Nacka, /stockholm, or /test first.');
            }
        } catch (error) {
            console.error('Telegram test message failed:', error);
            setTelegramTestState('error');
            setTelegramTestError(error?.message || 'Telegram test message failed.');
        }
    };

    return (
        <motion.div
            variants={pageEntrance}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="relative h-full w-full overflow-hidden bg-[radial-gradient(circle_at_10%_0%,rgba(34,211,238,0.16),transparent_30%),linear-gradient(145deg,rgba(4,10,24,0.98),rgba(7,14,32,0.96)_46%,rgba(6,24,31,0.92))] text-cyan-50"
            data-scroll-lock-nav="true"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endPointerDrag}
            onPointerCancel={endPointerDrag}
            onPointerLeave={endPointerDrag}
        >
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.025)_1px,transparent_1px)] bg-[size:44px_44px] opacity-35" />

            <div className="relative flex h-full min-h-0 flex-col">
                <header className="flex flex-shrink-0 items-center justify-between gap-4 border-b border-cyan-100/[0.12] bg-black/20 px-5 py-4 backdrop-blur-xl">
                    <div className="flex min-w-0 items-center gap-4">
                        <div className="min-w-0">
                            <h1 className="truncate font-['Plus_Jakarta_Sans'] text-2xl font-black text-white md:text-3xl">Settings</h1>
                        </div>
                    </div>
                </header>

                <main
                    ref={scrollContainerRef}
                    className="flex-1 overflow-y-auto touch-scroll-y px-4 py-5 md:px-6 md:py-6"
                    data-scroll-lock-nav="true"
                >
                    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(360px,0.96fr)]">
                        <Panel title="Voice Recognition" icon={Languages}>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                {VOICE_LANGUAGE_OPTIONS.map((language) => {
                                    const active = voiceLanguage === language.value;
                                    const busy = voiceSettingsPending === language.value;
                                    return (
                                        <button
                                            key={language.value}
                                            type="button"
                                            onClick={() => handleVoiceLanguageChange(language.value)}
                                            disabled={voiceSettingsLoading || Boolean(voiceSettingsPending)}
                                            className={`min-h-[106px] rounded-[24px] border p-4 text-left transition-all duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 ${
                                                active
                                                    ? 'border-cyan-200/70 bg-cyan-300/[0.13] shadow-[0_0_32px_rgba(34,211,238,0.16)]'
                                                    : 'border-white/10 bg-white/[0.035] hover:border-cyan-100/[0.28] hover:bg-white/[0.055]'
                                            }`}
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="font-['Plus_Jakarta_Sans'] text-base font-bold text-cyan-50">{language.title}</span>
                                                {busy ? <Loader2 size={17} className="animate-spin text-cyan-100" /> : active ? <Check size={17} className="text-cyan-100" /> : null}
                                            </div>
                                            <div className="mt-2 text-sm text-cyan-100/50">{language.description}</div>
                                        </button>
                                    );
                                })}
                            </div>
                            <div className="mt-4">
                                <SettingRow
                                    icon={Radio}
                                    title="Always listening"
                                    description="Listens for Nova and interrupts active speech"
                                >
                                    <ToggleSwitch
                                        checked={voiceAlwaysListening}
                                        onChange={handleVoiceAlwaysListeningChange}
                                        disabled={voiceSettingsLoading || Boolean(voiceSettingsPending)}
                                        label="Always listening"
                                    />
                                </SettingRow>
                            </div>
                            {voiceSettingsError ? (
                                <div className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                                    {voiceSettingsError}
                                </div>
                            ) : null}
                        </Panel>

                        <Panel title="Chat Model" icon={Brain}>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                {modelOptions.map((model) => {
                                    const active = model.id === activeModel;
                                    const selected = model.id === selectedModel;
                                    const busy = modelSwitching && selected;
                                    return (
                                        <button
                                            key={model.id}
                                            type="button"
                                            onClick={() => handleModelChange(model.id)}
                                            disabled={modelSettingsLoading || modelSettingsPending || modelSwitching || active}
                                            className={`min-h-[116px] rounded-[24px] border p-4 text-left transition-all duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 ${
                                                active
                                                    ? 'border-cyan-200/70 bg-cyan-300/[0.13] shadow-[0_0_32px_rgba(34,211,238,0.16)]'
                                                    : 'border-white/10 bg-white/[0.035] hover:border-cyan-100/[0.28] hover:bg-white/[0.055]'
                                            }`}
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="font-['Plus_Jakarta_Sans'] text-base font-bold text-cyan-50">{model.label}</span>
                                                {busy ? <Loader2 size={17} className="animate-spin text-cyan-100" /> : active ? <Check size={17} className="text-cyan-100" /> : null}
                                            </div>
                                            <div className="mt-2 text-sm text-cyan-100/50">{model.description}</div>
                                            <div className="mt-2 text-xs text-cyan-100/35">{model.size_note}</div>
                                        </button>
                                    );
                                })}
                            </div>
                            {modelSettingsError ? (
                                <div className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                                    {modelSettingsError}
                                </div>
                            ) : null}
                        </Panel>

                        <Panel title="Interface Systems" icon={Activity}>
                            <div className="space-y-3">
                                <SettingRow icon={Keyboard} title="Popup keyboard" description="Touch-friendly overlay input">
                                    <ToggleSwitch checked={keyboardEnabled} onChange={setKeyboardEnabled} label="Popup keyboard" />
                                </SettingRow>
                                <SettingRow icon={ScanLine} title="Ambient scanlines" description="CRT atmosphere over content">
                                    <ToggleSwitch checked={scanlinesEnabled} onChange={setScanlinesEnabled} label="Ambient scanlines" />
                                </SettingRow>
                                <SettingRow icon={Activity} title="Status bar" description="System statistics and clock strip">
                                    <ToggleSwitch checked={statusBarEnabled} onChange={setStatusBarEnabled} label="Status bar" />
                                </SettingRow>
                            </div>
                        </Panel>

                        <Panel title="Visible Tabs" icon={Eye}>
                            <div className="space-y-3">
                                {CONFIGURABLE_NAV_ITEMS.map((item) => {
                                    const visible = !hiddenTabs.includes(item.id);
                                    const Icon = item.icon;
                                    return (
                                        <SettingRow
                                            key={item.id}
                                            icon={visible ? Icon : EyeOff}
                                            title={item.label}
                                            description={visible ? 'Shown in side navigation' : 'Hidden from side navigation'}
                                        >
                                            <ToggleSwitch
                                                checked={visible}
                                                onChange={(nextVisible) => handleTabVisibilityChange(item.id, nextVisible)}
                                                label={`${item.label} tab`}
                                            />
                                        </SettingRow>
                                    );
                                })}
                            </div>
                        </Panel>

                        <Panel title="Location Alerts" icon={MapPin}>
                            <div className="space-y-3">
                                {[
                                    ['nacka', 'Nacka', 'Local municipal alerts'],
                                    ['stockholm', 'Stockholm', 'Regional city signal'],
                                ].map(([region, label, description]) => {
                                    const enabled = Boolean(alertSettings[region]);
                                    const pending = alertSettingsPending === region;
                                    return (
                                        <SettingRow key={region} icon={MapPin} title={label} description={description}>
                                            <ToggleSwitch
                                                checked={enabled}
                                                onChange={(nextEnabled) => handleAlertSettingChange(region, nextEnabled)}
                                                disabled={alertSettingsLoading || Boolean(alertSettingsPending)}
                                                label={`${label} alerts`}
                                            />
                                            {pending ? <Loader2 size={16} className="ml-2 animate-spin text-cyan-100/70" /> : null}
                                        </SettingRow>
                                    );
                                })}
                            </div>
                            {alertSettingsError ? (
                                <div className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                                    {alertSettingsError}
                                </div>
                            ) : null}
                        </Panel>

                        <Panel title="Telegram Relay" icon={Bell}>
                            <div className="space-y-3">
                                <SettingRow icon={Bell} title="Startup notification" description="Send online signal when NOVA boots">
                                    <ToggleSwitch
                                        checked={telegramStartupNotifications}
                                        onChange={handleTelegramStartupNotificationsChange}
                                        disabled={alertSettingsLoading || telegramSettingsPending}
                                        label="Startup notification"
                                    />
                                    {telegramSettingsPending ? <Loader2 size={16} className="ml-2 animate-spin text-cyan-100/70" /> : null}
                                </SettingRow>
                                {telegramTestError ? (
                                    <div className={`rounded-2xl border px-4 py-3 text-sm ${telegramTestState === 'sent' ? 'border-emerald-300/25 bg-emerald-500/10 text-emerald-100' : 'border-rose-300/25 bg-rose-500/10 text-rose-100'}`}>
                                        {telegramTestError}
                                    </div>
                                ) : null}
                                <button
                                    type="button"
                                    onClick={handleTelegramTest}
                                    disabled={telegramTestState === 'loading'}
                                    className="flex min-h-[54px] w-full items-center justify-center gap-3 rounded-[20px] border border-cyan-200/[0.22] bg-cyan-300/[0.16] px-5 py-4 font-['Plus_Jakarta_Sans'] text-sm font-bold text-cyan-50 shadow-[0_0_28px_rgba(34,211,238,0.12)] transition-all hover:-translate-y-0.5 hover:bg-cyan-300/[0.22] disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                    {telegramTestState === 'loading' ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                                    {telegramTestState === 'loading' ? 'Sending test' : 'Send Telegram test'}
                                </button>
                            </div>
                        </Panel>

                        <Panel title="Power Control" icon={Power} accent="rose">
                            <div className="rounded-[22px] border border-rose-200/[0.14] bg-rose-500/[0.08] p-4">
                                <div className="font-['Plus_Jakarta_Sans'] text-base font-bold text-rose-50">Shutdown NOVA</div>
                                <p className="mt-1 text-sm leading-relaxed text-rose-100/[0.55]">Turn NOVA off.</p>
                                <button
                                    type="button"
                                    onClick={handleCloseApp}
                                    className="mt-4 flex min-h-[56px] w-full items-center justify-center gap-3 rounded-[20px] border border-rose-200/25 bg-rose-500/20 px-5 py-4 font-['Plus_Jakarta_Sans'] text-sm font-bold text-rose-50 transition-all hover:-translate-y-0.5 hover:bg-rose-500/[0.28] active:translate-y-0"
                                >
                                    <Power size={19} />
                                    Shutdown
                                </button>
                            </div>
                        </Panel>
                    </div>
                </main>
            </div>
        </motion.div>
    );
}
