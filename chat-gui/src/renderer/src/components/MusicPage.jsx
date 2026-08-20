import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
    ChevronDown,
    ListMusic,
    Loader2,
    LogIn,
    Music4,
    Pause,
    Play,
    Repeat2,
    Shuffle,
    SkipBack,
    SkipForward,
} from 'lucide-react';
import { apiFetch } from '../apiClient.js';
import { API_BASE_URL } from '../config.js';
import { pageEntrance, panelEntrance } from '../motionPresets.js';

const REQUEST_TIMEOUT_MS = 7000;
// removed global fetch guard so playlists reload on remount

function formatTime(ms) {
    const totalSeconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
}

function emptyTrack() {
    return {
        title: '',
        artist: '',
        album_art_url: '',
        progress_ms: 0,
        duration_ms: 0,
        is_playing: false,
        repeat_state: 'off',
        shuffle_state: false,
        audio_source: 'spotify',
        device_id: '',
        device_name: '',
        devices: [],
        spotify_connected: false,
    };
}

function sortDevices(devices) {
    return [...devices].sort((left, right) => {
        const leftPreferred = Boolean(left?.is_preferred_local);
        const rightPreferred = Boolean(right?.is_preferred_local);
        if (leftPreferred !== rightPreferred) return leftPreferred ? -1 : 1;

        const leftActive = Boolean(left?.is_active);
        const rightActive = Boolean(right?.is_active);
        if (leftActive !== rightActive) return leftActive ? -1 : 1;

        return String(left?.name || '').localeCompare(String(right?.name || ''));
    });
}

async function apiFetchWithTimeout(path, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await apiFetch(path, { ...options, signal: controller.signal });
    } finally {
        window.clearTimeout(timer);
    }
}

export default function MusicPage() {
    const [track, setTrack] = useState(emptyTrack);
    const [displayProgressMs, setDisplayProgressMs] = useState(0);
    const [isConnected, setIsConnected] = useState(false);
    const [loading, setLoading] = useState(true);
    const [actionState, setActionState] = useState('idle');
    const [deviceActionState, setDeviceActionState] = useState('idle');
    const [repeatActionState, setRepeatActionState] = useState('idle');
    const [error, setError] = useState('');
    const [playlists, setPlaylists] = useState([]);
    const [queue, setQueue] = useState([]);
    const [playlistLoading, setPlaylistLoading] = useState(true);
    const [playlistActionState, setPlaylistActionState] = useState('idle');
    const [deviceMenuOpen, setDeviceMenuOpen] = useState(false);
    const hasFetchedPlaylistsRef = useRef(false);
    const progressSyncRef = useRef({ progressMs: 0, durationMs: 0, isPlaying: false, syncedAt: Date.now() });

    const repeatState = track.repeat_state || 'off';
    const devices = useMemo(() => sortDevices(Array.isArray(track.devices) ? track.devices : []), [track.devices]);
    const visiblePlaylists = useMemo(() => (Array.isArray(playlists) ? playlists.slice(0, 4) : []), [playlists]);
    const currentDevice = useMemo(() => {
        return (
            devices.find((device) => device.id && device.id === track.device_id)
            || devices.find((device) => device.is_active)
            || devices[0]
            || null
        );
    }, [devices, track.device_id]);

    const loadDashboardState = useCallback(async () => {
        try {
            const data = await apiFetchWithTimeout('/nova/spotify/audio-state');
            const normalized = { ...emptyTrack(), ...data };
            setTrack(normalized);
            setDisplayProgressMs(Number(normalized.progress_ms || 0));
            progressSyncRef.current = {
                progressMs: Number(normalized.progress_ms || 0),
                durationMs: Number(normalized.duration_ms || 0),
                isPlaying: Boolean(normalized.is_playing),
                syncedAt: Date.now(),
            };
            setIsConnected(Boolean(normalized.spotify_connected));
            setError('');
        } catch (err) {
            if (err?.name === 'AbortError') {
                setError('Spotify dashboard timed out while loading.');
            } else if (err?.status === 401 || err?.status === 403) {
                setError('');
            } else {
                setError(err?.message || 'Spotify is unavailable right now.');
            }
            setIsConnected(false);
            setTrack(emptyTrack());
            setDisplayProgressMs(0);
            progressSyncRef.current = { progressMs: 0, durationMs: 0, isPlaying: false, syncedAt: Date.now() };
        } finally {
            setLoading(false);
        }
    }, []);

    const loadPlaylists = useCallback(async () => {
        try {
            const data = await apiFetchWithTimeout('/nova/spotify/playlists');
            const list = Array.isArray(data) ? data.slice(0, 4) : [];
            setPlaylists(list);
        } catch {
            setPlaylists([]);
        } finally {
            setPlaylistLoading(false);
        }
    }, []);

    const loadQueue = useCallback(async () => {
        try {
            const data = await apiFetchWithTimeout('/nova/spotify/queue');
            setQueue(Array.isArray(data) ? data.slice(0, 3) : []);
        } catch {
            setQueue([]);
        }
    }, []);

    useEffect(() => {
        loadDashboardState();
        loadQueue();

        const timer = window.setInterval(() => {
            loadDashboardState();
            loadQueue();
        }, 10000);

        return () => {
            window.clearInterval(timer);
        };
    }, [loadDashboardState, loadQueue]);

    useEffect(() => {
        const timer = window.setInterval(() => {
            const sync = progressSyncRef.current;
            if (!sync.durationMs) {
                setDisplayProgressMs(0);
                return;
            }

            if (!sync.isPlaying) {
                setDisplayProgressMs(sync.progressMs);
                return;
            }

            const elapsedMs = Date.now() - sync.syncedAt;
            const nextProgress = Math.min(sync.durationMs, sync.progressMs + Math.max(0, elapsedMs));
            setDisplayProgressMs(nextProgress);
        }, 1000);

        return () => {
            window.clearInterval(timer);
        };
    }, []);

    useEffect(() => {
        if (hasFetchedPlaylistsRef.current) return;
        hasFetchedPlaylistsRef.current = true;
        loadPlaylists();
        return () => {
            // allow refetch when the component is unmounted and mounted again
            hasFetchedPlaylistsRef.current = false;
        };
    }, [loadPlaylists]);

    const progressRatio = useMemo(() => {
        const duration = Number(track.duration_ms || 0);
        if (!duration) return 0;
        return Math.min(1, Math.max(0, Number(displayProgressMs || 0) / duration));
    }, [displayProgressMs, track.duration_ms]);

    const handleConnect = useCallback(() => {
        window.location.href = `${API_BASE_URL}/nova/spotify/login`;
    }, []);

    const refreshAfterAction = useCallback(async () => {
        await loadDashboardState();
    }, [loadDashboardState]);

    const withCurrentDevice = useCallback((path) => {
        if (!currentDevice?.id) return path;
        const separator = path.includes('?') ? '&' : '?';
        return `${path}${separator}device_id=${encodeURIComponent(currentDevice.id)}`;
    }, [currentDevice]);

    const sendControl = useCallback(async (path) => {
        setActionState(path);
        try {
            await apiFetch(withCurrentDevice(path), { method: 'POST' });
            await refreshAfterAction();
        } catch (err) {
            if (err && (err.status === 404 || err.status === 409 || String(err?.message || '').toLowerCase().includes('device'))) {
                setError('No active Spotify device found. Open Spotify on your phone or computer and start playback there.');
            } else {
                setError(err?.message || 'Spotify control failed.');
            }
        } finally {
            setActionState('idle');
        }
    }, [refreshAfterAction, withCurrentDevice]);

    const playPlaylist = useCallback(async (playlistId) => {
        if (!playlistId) return;
        setPlaylistActionState(playlistId);
        try {
            const deviceParam = currentDevice && currentDevice.id ? `?device_id=${encodeURIComponent(currentDevice.id)}` : '';
            await apiFetch(`/nova/spotify/play-playlist/${playlistId}${deviceParam}`, { method: 'POST' });
            await refreshAfterAction();
        } catch (err) {
            if (err && (err.status === 409 || String(err?.message || '').toLowerCase().includes('device'))) {
                setError('No active Spotify device found. Open Spotify on your phone or computer and start playback there.');
            } else {
                setError(err?.message || 'Playlist playback failed.');
            }
        } finally {
            setPlaylistActionState('idle');
        }
    }, [currentDevice, refreshAfterAction]);

    const toggleRepeat = useCallback(async () => {
        setRepeatActionState('busy');
        try {
            const result = await apiFetch(withCurrentDevice('/nova/spotify/repeat'), { method: 'POST' });
            if (result && typeof result === 'object') {
                const normalized = { ...emptyTrack(), ...track, ...result };
                setTrack(normalized);
                setDisplayProgressMs(Number(normalized.progress_ms || 0));
                progressSyncRef.current = {
                    progressMs: Number(normalized.progress_ms || 0),
                    durationMs: Number(normalized.duration_ms || 0),
                    isPlaying: Boolean(normalized.is_playing),
                    syncedAt: Date.now(),
                };
                setIsConnected(Boolean(normalized.spotify_connected || true));
            }
            await refreshAfterAction();
        } catch (err) {
            if (err && (err.status === 404 || err.status === 409 || String(err?.message || '').toLowerCase().includes('device'))) {
                setError('No active Spotify device found. Open Spotify on your phone or computer and start playback there.');
            } else {
                setError(err?.message || 'Repeat toggle failed.');
            }
        } finally {
            setRepeatActionState('idle');
        }
    }, [refreshAfterAction, track, withCurrentDevice]);

    const selectDevice = useCallback(async (deviceId) => {
        if (!deviceId) return;
        setDeviceActionState(deviceId);
        try {
            await apiFetch(`/nova/spotify/select-device/${deviceId}`, { method: 'POST' });
            setDeviceMenuOpen(false);
            await refreshAfterAction();
            setError('');
        } catch (err) {
            setError(err?.message || 'Device switch failed.');
        } finally {
            setDeviceActionState('idle');
        }
    }, [refreshAfterAction]);

    const showAuthPrompt = !loading && !isConnected;
    const hasTrack = Boolean(track.title || track.artist);
    const artUrl = track.album_art_url || '';
    const progressPercent = `${Math.round(progressRatio * 100)}%`;
    const repeatLabel = repeatState === 'context' ? 'Playlist' : repeatState === 'track' ? 'Track' : 'Off';

    return (
        <motion.div
            className="h-full min-h-0 w-full overflow-y-auto touch-scroll-y px-4 py-3 text-[#e9fbff] lg:px-6 lg:py-4"
            variants={pageEntrance}
            initial="hidden"
            animate="visible"
            exit="exit"
        >
            <motion.section
                className="mx-auto flex min-h-full w-full max-w-[1500px] flex-col gap-4"
                variants={panelEntrance}
            >
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                    <h1 className="font-['Plus_Jakarta_Sans'] text-3xl font-semibold text-white md:text-4xl">MUSIC</h1>

                    <div className="relative">
                        <button
                            type="button"
                            onClick={() => devices.length > 0 && setDeviceMenuOpen((value) => !value)}
                            disabled={devices.length === 0}
                            className="inline-flex min-h-11 max-w-[220px] items-center gap-2 rounded-md border border-white/15 bg-white/[0.04] px-4 text-sm text-white transition-all hover:border-cyan-200/30 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-60"
                            aria-label="Switch Spotify device"
                        >
                            <span className="truncate">{currentDevice?.name || 'Switch Device'}</span>
                            <ChevronDown size={14} className="shrink-0" />
                        </button>

                        {deviceMenuOpen && devices.length > 0 ? (
                            <div className="absolute right-0 top-[calc(100%+8px)] z-30 w-72 overflow-hidden rounded-md border border-cyan-200/15 bg-[#07101f]/96 shadow-[0_22px_40px_rgba(0,0,0,0.42)] backdrop-blur-xl">
                                <div className="border-b border-cyan-200/10 px-4 py-3 text-xs uppercase text-cyan-100/55">Spotify devices</div>
                                <div className="max-h-72 overflow-y-auto p-2">
                                    {devices.map((device) => {
                                        const isBusy = deviceActionState === device.id;
                                        const isCurrent = device.id && device.id === currentDevice?.id;
                                        const label = [device.is_preferred_local ? 'Local' : null, device.type || null].filter(Boolean).join(' / ');
                                        return (
                                            <button
                                                key={device.id || device.name}
                                                type="button"
                                                onClick={() => selectDevice(device.id)}
                                                disabled={deviceActionState !== 'idle'}
                                                className={`flex w-full items-start justify-between gap-3 rounded-md px-3 py-3 text-left transition-all disabled:opacity-60 ${
                                                    isCurrent ? 'bg-cyan-400/14 text-cyan-50' : 'text-cyan-50/90 hover:bg-white/[0.07]'
                                                }`}
                                            >
                                                <span className="min-w-0">
                                                    <span className="block truncate text-sm font-semibold">{device.name || 'Unnamed device'}</span>
                                                    <span className="block text-xs text-cyan-100/55">{label || 'Spotify Connect device'}</span>
                                                </span>
                                                <span className="flex items-center gap-2 text-xs text-cyan-100/55">
                                                    {device.is_active ? 'Active' : ''}
                                                    {isBusy ? <Loader2 size={14} className="animate-spin" /> : null}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        ) : null}
                    </div>
                </div>

                {error ? (
                    <div className="border border-rose-300/20 bg-rose-500/10 px-4 py-2.5 text-sm text-rose-100">
                        {error}
                    </div>
                ) : null}

                {showAuthPrompt ? (
                    <div className="flex min-h-[420px] items-center justify-center border border-cyan-200/10 bg-white/[0.03] p-6 text-center">
                        <div className="max-w-md space-y-4">
                            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-cyan-200/15 bg-cyan-400/10 text-cyan-100">
                                <LogIn size={30} />
                            </div>
                            <div>
                                <h3 className="text-xl font-semibold text-cyan-50">Connect Spotify</h3>
                                <p className="mt-2 text-sm text-cyan-100/70">
                                    NOVA needs your Spotify account connected before it can show playback, playlists, or playback controls.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={handleConnect}
                                className="inline-flex min-h-[56px] w-full items-center justify-center gap-3 rounded-2xl border border-cyan-300/20 bg-[rgba(33,93,216,0.42)] px-5 py-4 text-sm font-semibold text-cyan-50 transition-all hover:bg-[rgba(33,93,216,0.58)] active:scale-[0.99]"
                            >
                                <LogIn size={20} />
                                Connect Spotify
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(220px,0.72fr)_minmax(0,1.28fr)] lg:grid-cols-[minmax(220px,0.72fr)_minmax(300px,1.2fr)_minmax(210px,0.68fr)] lg:items-stretch">
                        <div className="relative aspect-square w-full max-w-[340px] self-center overflow-hidden rounded-md border border-white/10 bg-white/[0.04] shadow-[0_24px_70px_rgba(0,0,0,0.36)]">
                            {artUrl ? (
                                <img
                                    src={artUrl}
                                    alt={track.title ? `${track.title} album art` : 'Spotify album art'}
                                    className="h-full w-full object-cover"
                                />
                            ) : (
                                <div className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_30%_20%,rgba(26,209,255,0.22),transparent_40%),linear-gradient(160deg,rgba(16,33,74,0.84),rgba(7,11,34,0.98))]">
                                    <Music4 size={72} className="text-cyan-100/60" />
                                </div>
                            )}
                            <div className="absolute inset-0 bg-gradient-to-t from-black/50 via-transparent to-transparent" />
                        </div>

                        <div className="flex min-h-[260px] flex-col justify-center gap-5 border-y border-white/10 py-4 md:px-3 lg:border-y-0 lg:px-5 lg:py-1">
                            <div className="space-y-3">
                                <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1.35fr)_minmax(120px,0.65fr)] sm:items-start sm:gap-5">
                                    <h2 className="line-clamp-2 min-w-0 font-['Plus_Jakarta_Sans'] text-3xl font-bold leading-tight text-white md:text-4xl">
                                        {hasTrack ? track.title : 'Nothing playing'}
                                    </h2>
                                    <p className="min-w-0 truncate text-lg font-semibold leading-snug text-cyan-300 sm:pt-1 sm:text-right md:text-xl">
                                        {hasTrack ? track.artist : 'Open Spotify to start playback.'}
                                    </p>
                                </div>

                                <div className="space-y-2 pt-3">
                                    <div className="h-1.5 overflow-hidden rounded-full bg-white/12">
                                        <div
                                            className="h-full rounded-full bg-gradient-to-r from-cyan-300 via-sky-400 to-blue-500 transition-[width] duration-500"
                                            style={{ width: progressPercent }}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between text-sm font-medium text-white/55">
                                        <span>{formatTime(displayProgressMs)}</span>
                                        <span>{formatTime(track.duration_ms)}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="grid grid-cols-5 items-center gap-3">
                                <button
                                    type="button"
                                    onClick={() => sendControl('/nova/spotify/shuffle')}
                                    disabled={actionState !== 'idle'}
                                    className={`flex min-h-[58px] items-center justify-center rounded-md border transition-all hover:bg-white/10 active:scale-[0.98] disabled:opacity-60 ${
                                        track.shuffle_state ? 'border-cyan-300/30 bg-cyan-400/16 text-cyan-100' : 'border-white/10 bg-white/[0.03] text-white/75'
                                    }`}
                                    aria-label="Shuffle"
                                    title={`Shuffle ${track.shuffle_state ? 'on' : 'off'}`}
                                >
                                    <Shuffle size={24} />
                                </button>
                                <button
                                    onClick={() => sendControl('/nova/spotify/prev')}
                                    disabled={actionState !== 'idle'}
                                    className="flex min-h-[58px] items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-white/80 transition-all hover:bg-white/10 active:scale-[0.98] disabled:opacity-60"
                                    aria-label="Previous track"
                                    title="Previous track"
                                >
                                    <SkipBack size={24} />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => sendControl('/nova/spotify/toggle')}
                                    disabled={actionState !== 'idle'}
                                    className="mx-auto flex aspect-square w-[64px] items-center justify-center rounded-full border border-cyan-200/60 bg-black/30 text-white shadow-[0_0_28px_rgba(34,211,238,0.22)] transition-all hover:bg-cyan-300/10 hover:shadow-[0_0_34px_rgba(34,211,238,0.34)] active:scale-[0.96] disabled:opacity-60"
                                    aria-label={track.is_playing ? 'Pause' : 'Play'}
                                    title={track.is_playing ? 'Pause' : 'Play'}
                                >
                                    {track.is_playing ? <Pause size={28} /> : <Play size={28} className="translate-x-[2px]" />}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => sendControl('/nova/spotify/next')}
                                    disabled={actionState !== 'idle'}
                                    className="flex min-h-[58px] items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-white/80 transition-all hover:bg-white/10 active:scale-[0.98] disabled:opacity-60"
                                    aria-label="Next track"
                                    title="Next track"
                                >
                                    <SkipForward size={24} />
                                </button>
                                <button
                                    type="button"
                                    onClick={toggleRepeat}
                                    disabled={repeatActionState !== 'idle'}
                                    className={`flex min-h-[58px] items-center justify-center rounded-md border transition-all hover:bg-white/10 active:scale-[0.98] disabled:opacity-60 ${
                                        repeatState !== 'off' ? 'border-cyan-300/30 bg-cyan-400/16 text-cyan-100' : 'border-white/10 bg-white/[0.03] text-white/75'
                                    }`}
                                    aria-label={`Repeat ${repeatLabel}`}
                                    title={`Repeat ${repeatLabel}`}
                                >
                                    <Repeat2 size={24} />
                                </button>
                            </div>
                        </div>

                        <aside className="md:col-span-2 lg:col-span-1 lg:px-1">
                            <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase text-cyan-300">
                                <ListMusic size={18} />
                                Up Next
                            </div>
                            <div className="divide-y divide-white/10">
                                {queue.length > 0 ? queue.map((item, index) => (
                                    <div key={item.id || `${item.title}-${index}`} className="grid min-h-[76px] grid-cols-[54px_minmax(0,1fr)] items-center gap-3 py-2.5">
                                        <div className="h-[54px] w-[54px] overflow-hidden rounded-md bg-white/[0.05]">
                                            {item.album_art_url ? <img src={item.album_art_url} alt="" className="h-full w-full object-cover" /> : <Music4 className="m-[15px] text-white/35" size={24} />}
                                        </div>
                                        <div className="min-w-0">
                                            <div className="truncate text-base font-semibold text-white">{item.title || 'Unknown track'}</div>
                                            <div className="mt-1 truncate text-sm text-white/45">{item.artist || 'Unknown artist'}</div>
                                        </div>
                                    </div>
                                )) : (
                                    <div className="flex min-h-[120px] items-center text-sm text-white/40">The upcoming queue will appear here.</div>
                                )}
                            </div>
                        </aside>
                    </div>
                )}

                {visiblePlaylists.length > 0 || playlistLoading ? (
                    <div className="border-t border-white/10 pt-4">
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                            {playlistLoading ? (
                                <div className="flex min-h-[170px] items-center justify-center rounded-md border border-white/10 bg-white/[0.03] px-6 text-sm text-white/50 sm:col-span-2 lg:col-span-4">
                                    <Loader2 size={16} className="mr-2 animate-spin" />
                                    Loading playlists...
                                </div>
                            ) : visiblePlaylists.length > 0 ? visiblePlaylists.map((playlist) => {
                                const isBusy = playlistActionState === playlist.id;
                                return (
                                    <button
                                        key={playlist.id}
                                        type="button"
                                        onClick={() => playPlaylist(playlist.id)}
                                        disabled={playlistActionState !== 'idle'}
                                        className="group relative min-h-[190px] overflow-hidden rounded-md border border-white/10 bg-white/[0.03] text-left transition-all hover:-translate-y-0.5 hover:border-cyan-200/25 active:scale-[0.99] disabled:opacity-60"
                                        aria-label={`Play playlist ${playlist.name}`}
                                    >
                                        <div className="absolute inset-0 overflow-hidden bg-[linear-gradient(160deg,rgba(16,33,74,0.84),rgba(7,11,34,0.98))]">
                                            {playlist.image_url ? (
                                                <img
                                                    src={playlist.image_url}
                                                    alt={playlist.name ? `${playlist.name} cover art` : 'Playlist cover art'}
                                                    className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
                                                />
                                            ) : (
                                                <div className="flex h-full w-full items-center justify-center text-cyan-100/60">
                                                    <Music4 size={56} />
                                                </div>
                                            )}
                                            <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />
                                            {isBusy ? (
                                                <div className="absolute inset-0 flex items-center justify-center bg-black/35">
                                                    <Loader2 size={20} className="animate-spin text-cyan-100" />
                                                </div>
                                            ) : null}
                                        </div>
                                        <div className="absolute inset-x-0 bottom-0 z-10 px-5 py-4">
                                            <span className="line-clamp-2 font-['Plus_Jakarta_Sans'] text-xl font-bold leading-tight text-white">
                                                {playlist.name || 'Untitled Playlist'}
                                            </span>
                                        </div>
                                    </button>
                                );
                            }) : (
                                <div className="flex min-h-[170px] items-center justify-center rounded-md border border-white/10 bg-white/[0.03] px-6 text-sm text-white/50 sm:col-span-2 lg:col-span-4">
                                    No playlists found.
                                </div>
                            )}
                        </div>
                    </div>
                ) : null}

            </motion.section>
        </motion.div>
    );
}
