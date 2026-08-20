import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Pause, Play, Repeat, Shuffle, SkipBack, SkipForward } from 'lucide-react';
import { apiFetch } from '../apiClient.js';

function emptySpotifyState() {
    return {
        spotify_connected: false,
        title: '',
        artist: '',
        is_playing: false,
        progress_ms: 0,
        duration_ms: 0,
        repeat_state: 'off',
        shuffle_state: false,
        device_id: '',
        device_name: '',
        devices: [],
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

export default function MusicStatus({ onPlaybackStateChange }) {
    const [spotifyState, setSpotifyState] = useState(() => emptySpotifyState());
    const [musicActionState, setMusicActionState] = useState('idle');
    const [repeatActionState, setRepeatActionState] = useState('idle');
    const [error, setError] = useState('');
    const mountedRef = useRef(false);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    const devices = useMemo(() => sortDevices(Array.isArray(spotifyState.devices) ? spotifyState.devices : []), [spotifyState.devices]);
    const currentDevice = useMemo(() => {
        return (
            devices.find((device) => device.id && device.id === spotifyState.device_id)
            || devices.find((device) => device.is_active)
            || devices[0]
            || null
        );
    }, [devices, spotifyState.device_id]);

    useEffect(() => {
        onPlaybackStateChange?.(Boolean(spotifyState.is_playing));
    }, [onPlaybackStateChange, spotifyState.is_playing]);

    const fetchSpotifyState = useCallback(async () => {
        try {
            const result = await apiFetch('/nova/spotify/audio-state');
            const normalized = { ...emptySpotifyState(), ...result };
            if (!mountedRef.current) return;
            setSpotifyState(normalized);
            setError('');
        } catch (err) {
            console.error('Spotify state fetch failed:', err);
            if (!mountedRef.current) return;
            setSpotifyState(emptySpotifyState());
            setError(err?.message || 'Spotify is unavailable right now.');
        }
    }, []);

    useEffect(() => {
        fetchSpotifyState();
        const interval = window.setInterval(fetchSpotifyState, 5000);
        return () => window.clearInterval(interval);
    }, [fetchSpotifyState]);

    const withCurrentDevice = useCallback((path) => {
        if (!currentDevice?.id) return path;
        const separator = path.includes('?') ? '&' : '?';
        return `${path}${separator}device_id=${encodeURIComponent(currentDevice.id)}`;
    }, [currentDevice]);

    const sendMusicControl = useCallback(async (path) => {
        if (!path || musicActionState !== 'idle') return;
        setMusicActionState(path);
        try {
            const result = await apiFetch(withCurrentDevice(path), { method: 'POST' });
            if (result && typeof result === 'object') {
                setSpotifyState((prev) => ({ ...prev, ...result }));
            }
            await fetchSpotifyState();
            setError('');
        } catch (err) {
            console.error('Spotify control failed:', err);
            setError(err?.message || 'Spotify control failed.');
        } finally {
            setMusicActionState('idle');
        }
    }, [fetchSpotifyState, musicActionState, withCurrentDevice]);

    const toggleRepeat = useCallback(async () => {
        if (repeatActionState !== 'idle') return;
        setRepeatActionState('busy');
        try {
            const result = await apiFetch(withCurrentDevice('/nova/spotify/repeat'), { method: 'POST' });
            if (result && typeof result === 'object') {
                setSpotifyState((prev) => ({ ...prev, ...result }));
            }
            await fetchSpotifyState();
            setError('');
        } catch (err) {
            console.error('Repeat toggle failed:', err);
            setError(err?.message || 'Repeat toggle failed.');
        } finally {
            setRepeatActionState('idle');
        }
    }, [fetchSpotifyState, repeatActionState, withCurrentDevice]);

    return (
        <AnimatePresence initial={false} mode="popLayout">
            {spotifyState.is_playing ? (
                <motion.div
                    key="home-music-status"
                    className="w-full overflow-hidden"
                    layout
                    initial={{ opacity: 0, height: 0, y: 18, scale: 0.985 }}
                    animate={{ opacity: 1, height: 'auto', y: 0, scale: 1 }}
                    exit={{ opacity: 0, height: 0, y: 12, scale: 0.985 }}
                    transition={{
                        height: { duration: 0.42, ease: [0.22, 1, 0.36, 1] },
                        opacity: { duration: 0.24 },
                        y: { duration: 0.34, ease: [0.22, 1, 0.36, 1] },
                        scale: { duration: 0.34, ease: [0.22, 1, 0.36, 1] },
                        layout: { type: 'spring', stiffness: 220, damping: 28 },
                    }}
                >
                    <div className="glass-card p-3 mb-4">
                <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(70px,0.75fr)] items-baseline gap-3 pb-2">
                    <div className="truncate text-lg font-semibold text-white">
                        {spotifyState.title || (spotifyState.spotify_connected ? 'No track playing' : 'Spotify offline')}
                    </div>
                    {spotifyState.artist ? (
                        <div className="truncate text-right text-base text-white/65">{spotifyState.artist}</div>
                    ) : null}
                </div>

                <div className="music-controls grid grid-cols-5 gap-2">
                    <button
                        className={`music-touch-btn w-full h-12 ${spotifyState.shuffle_state ? 'text-cyan-200 bg-cyan-400/18' : ''}`}
                        aria-label="Shuffle"
                        onClick={() => sendMusicControl('/nova/spotify/shuffle')}
                        disabled={musicActionState !== 'idle'}
                        title={`Shuffle ${spotifyState.shuffle_state ? 'on' : 'off'}`}
                    >
                        <Shuffle size={20} />
                    </button>
                    <button
                        className="music-touch-btn w-full h-12"
                        aria-label="Previous"
                        onClick={() => sendMusicControl('/nova/spotify/prev')}
                        disabled={musicActionState !== 'idle'}
                    >
                        <SkipBack size={20} />
                    </button>
                    <button
                        className="music-touch-btn music-touch-btn-main w-full h-12"
                        onClick={() => sendMusicControl('/nova/spotify/toggle')}
                        aria-label={spotifyState.is_playing ? 'Pause' : 'Play'}
                        disabled={musicActionState !== 'idle'}
                    >
                        {spotifyState.is_playing ? <Pause size={22} /> : <Play size={22} />}
                    </button>
                    <button
                        className="music-touch-btn w-full h-12"
                        aria-label="Next"
                        onClick={() => sendMusicControl('/nova/spotify/next')}
                        disabled={musicActionState !== 'idle'}
                    >
                        <SkipForward size={20} />
                    </button>
                    <button
                        className="music-touch-btn w-full h-12"
                        aria-label="Repeat"
                        onClick={toggleRepeat}
                        disabled={repeatActionState !== 'idle'}
                        title={`Repeat ${spotifyState.repeat_state || 'off'}`}
                    >
                        <Repeat size={20} />
                    </button>
                </div>

                {error ? <div className="mt-2 text-[11px] text-rose-100/80">{error}</div> : null}
                    </div>
                </motion.div>
            ) : null}
        </AnimatePresence>
    );
}
