import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { API_URL, WS_URL, CHAT_WS_URL } from '../config.js';
import { apiFetch, authorizedWebSocketUrl } from '../apiClient.js';

const WebSocketContext = createContext(null);

const KEY_VOICE_AUTO_RECONNECT = 'nova.voiceAutoReconnect';
const MUSIC_DUCK_VOLUME_PERCENT = 20;
const MUSIC_DUCK_ACTIVE_STATUSES = new Set(['listening', 'transcribing', 'thinking', 'generating', 'speaking']);

function readVoiceReconnectEnabled() {
    try {
        const value = localStorage.getItem(KEY_VOICE_AUTO_RECONNECT);
        return value !== 'false';
    } catch {
        return true;
    }
}

export function WebSocketProvider({ children }) {
    const [connStatus, setConnStatus] = useState('connecting'); // connected | disconnected | connecting
    const [chatConnStatus, setChatConnStatus] = useState('disconnected');
    const [messages, setMessages] = useState([]); // Chat messages
    const [streamText, setStreamText] = useState('');
    const [streaming, setStreaming] = useState(false);
    const [voiceStreamText, setVoiceStreamText] = useState('');
    const [isVoiceStreaming, setIsVoiceStreaming] = useState(false);
    const [isRecording, setIsRecording] = useState(false);
    const [isVoskRecording, setIsVoskRecording] = useState(false);
    const [voiceStatus, setVoiceStatus] = useState('idle'); // idle | listening | thinking | speaking
    const [voiceStage, setVoiceStage] = useState('idle'); // idle | listening | transcribing | thinking | generating | speaking
    const [voskText, setVoskText] = useState('');
    const [thinking, setThinking] = useState(false);

    // Multi-conversation state
    const [conversations, setConversations] = useState([]);
    const [currentConvId, setCurrentConvId] = useState(null);
    const [lastApiError, setLastApiError] = useState(null);

    // Generic event listeners for other components
    const eventListeners = useRef({});

    const wsRef = useRef(null);
    const reconnectTimer = useRef(null);
    const shouldReconnectRef = useRef(true);
    const connectRef = useRef(null);
    const connectChatRef = useRef(null);
    const stageResetTimerRef = useRef(null);
    const voiceStatusRef = useRef(voiceStatus);
    const voiceStageRef = useRef(voiceStage);
    const isRecordingRef = useRef(isRecording);
    const isVoiceStreamingRef = useRef(isVoiceStreaming);
    const audioContextRef = useRef(null);
    const audioPlayTimeRef = useRef(0);
    const audioSourcesRef = useRef(new Set());
    const acceptTtsAudioRef = useRef(false);
    const suppressInterruptedVoiceRef = useRef(false);
    const musicDuckActiveRef = useRef(false);
    const musicDuckQueueRef = useRef(Promise.resolve());

    useEffect(() => {
        voiceStatusRef.current = voiceStatus;
    }, [voiceStatus]);

    useEffect(() => {
        voiceStageRef.current = voiceStage;
    }, [voiceStage]);

    useEffect(() => {
        isRecordingRef.current = isRecording;
    }, [isRecording]);

    useEffect(() => {
        isVoiceStreamingRef.current = isVoiceStreaming;
    }, [isVoiceStreaming]);

    const setMusicDucking = useCallback((shouldDuck) => {
        if (shouldDuck === musicDuckActiveRef.current) return;
        musicDuckActiveRef.current = shouldDuck;
        const path = shouldDuck
            ? `/nova/spotify/duck?volume_percent=${MUSIC_DUCK_VOLUME_PERCENT}`
            : '/nova/spotify/duck?restore=true';
        musicDuckQueueRef.current = musicDuckQueueRef.current
            .catch(() => {})
            .then(() => apiFetch(path, { method: 'POST' }))
            .catch((error) => {
                musicDuckActiveRef.current = !shouldDuck;
                console.warn('[voice] Spotify volume ducking failed', error);
            });
    }, []);

    useEffect(() => () => {
        if (musicDuckActiveRef.current) {
            musicDuckActiveRef.current = false;
            apiFetch('/nova/spotify/duck?restore=true', { method: 'POST' }).catch(() => {});
        }
    }, []);

    const resetVoiceActivity = useCallback(() => {
        setMusicDucking(false);
        setVoiceStatus('idle');
        setVoiceStage('idle');
        setIsVoiceStreaming(false);
        setVoiceStreamText('');
        setIsRecording(false);
    }, [setMusicDucking]);

    const setStageWithAutoReset = useCallback((stage, timeoutMs = 0) => {
        if (stageResetTimerRef.current) {
            clearTimeout(stageResetTimerRef.current);
            stageResetTimerRef.current = null;
        }
        setVoiceStage(stage);
        if (timeoutMs > 0) {
            stageResetTimerRef.current = setTimeout(() => {
                setVoiceStage((prev) => (prev === stage ? 'idle' : prev));
                stageResetTimerRef.current = null;
            }, timeoutMs);
        }
    }, []);

    const addEventListener = useCallback((type, callback) => {
        if (!eventListeners.current[type]) {
            eventListeners.current[type] = [];
        }
        eventListeners.current[type].push(callback);

        // Return unsubscribe function
        return () => {
            eventListeners.current[type] = eventListeners.current[type].filter(cb => cb !== callback);
        };
    }, []);

    const resetTtsAudioPlayback = useCallback(() => {
        const audioContext = audioContextRef.current;
        if (audioContext) {
            audioPlayTimeRef.current = audioContext.currentTime;
        } else {
            audioPlayTimeRef.current = 0;
        }
    }, []);

    const stopTtsAudioPlayback = useCallback(() => {
        acceptTtsAudioRef.current = false;
        const audioContext = audioContextRef.current;
        audioPlayTimeRef.current = audioContext ? audioContext.currentTime : 0;
        audioSourcesRef.current.forEach((source) => {
            source.onended = null;
            try {
                source.stop();
            } catch {
                // The source may already have ended.
            }
            try {
                source.disconnect();
            } catch {
                // Already disconnected.
            }
        });
        audioSourcesRef.current.clear();
    }, []);

    const playPcmChunk = useCallback((base64Audio, sampleRate = 22050) => {
        if (!base64Audio || !acceptTtsAudioRef.current) return;
        try {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass) return;
            if (!audioContextRef.current) {
                audioContextRef.current = new AudioContextClass();
            }
            const audioContext = audioContextRef.current;
            if (audioContext.state === 'suspended') {
                audioContext.resume().catch(() => {});
            }

            const binary = atob(base64Audio);
            const sampleCount = Math.floor(binary.length / 2);
            const audioBuffer = audioContext.createBuffer(1, sampleCount, sampleRate);
            const channel = audioBuffer.getChannelData(0);
            for (let i = 0; i < sampleCount; i += 1) {
                const lo = binary.charCodeAt(i * 2);
                const hi = binary.charCodeAt(i * 2 + 1);
                let value = (hi << 8) | lo;
                if (value >= 0x8000) value -= 0x10000;
                channel[i] = value / 32768;
            }

            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);
            audioSourcesRef.current.add(source);
            source.onended = () => {
                audioSourcesRef.current.delete(source);
                try {
                    source.disconnect();
                } catch {
                    // Already disconnected.
                }
            };
            const startAt = Math.max(audioContext.currentTime + 0.02, audioPlayTimeRef.current || 0);
            source.start(startAt);
            audioPlayTimeRef.current = startAt + audioBuffer.duration;
        } catch (error) {
            console.error('[voice] failed to play TTS audio chunk', error);
        }
    }, []);

    const handleServerMessage = useCallback((data) => {
        // 1. Dispatch to generic listeners first
        if (eventListeners.current[data.type]) {
            eventListeners.current[data.type].forEach(cb => cb(data));
        }

        if (data.type === 'voice_status') {
            console.debug('[voice] status update', data.status, data);
        } else if (data.type === 'voice_transcription') {
            console.debug('[voice] transcription received', data.text?.slice?.(0, 120) || '');
        } else if (data.type === 'vosk_partial') {
            console.debug('[voice] partial transcript', data.text?.slice?.(0, 120) || '');
        } else if (data.type === 'error') {
            console.error('[voice] backend error event', data.message || data.error || data);
        }

        if (suppressInterruptedVoiceRef.current && data.type === 'voice_status' && data.status === 'thinking') {
            suppressInterruptedVoiceRef.current = false;
        }
        if (suppressInterruptedVoiceRef.current && data.type === 'voice_transcription') {
            suppressInterruptedVoiceRef.current = false;
        }

        const interruptSensitiveMessage = [
            'ai_start',
            'ai_delta',
            'ai_final',
            'tts_audio_start',
            'tts_audio_chunk',
            'tts_audio_end',
            'voice_done',
            'ai_aborted',
        ].includes(data.type);
        if (suppressInterruptedVoiceRef.current && interruptSensitiveMessage) {
            if (data.type === 'ai_start' && !isRecordingRef.current) {
                suppressInterruptedVoiceRef.current = false;
            } else {
                return;
            }
        }
        if (suppressInterruptedVoiceRef.current && data.type === 'voice_status' && data.status === 'idle' && isRecordingRef.current) {
            return;
        }

        // 2. Handle core chat messages locally (or we could move this out too, but keeping it here for simplicity of migration)
        switch (data.type) {
            case 'history': {
                const history = (data.messages || [])
                    .filter((m) => !m.hidden)
                    .map((m) => ({
                        role: m.role,
                        text: m.text,
                    }));
                setMessages(history);
                break;
            }
            case 'stream_start':
                setStreaming(true);
                setStreamText('');
                break;
            case 'stream_delta':
                setStreamText((prev) => `${prev}${data.text || ''}`);
                break;
            case 'stream_final':
                if (voiceStatusRef.current !== 'speaking' && !isRecordingRef.current) setStageWithAutoReset('idle');
                setStreaming(false);
                setMessages((prev) => [
                    ...prev,
                    { role: 'assistant', text: data.text || '' },
                ]);
                setStreamText('');
                break;
            case 'stream_error':
                setStageWithAutoReset('idle');
                setStreaming(false);
                setMessages((prev) => [
                    ...prev,
                    { role: 'assistant', text: `⚠ Error: ${data.error || 'Unknown error'}` },
                ]);
                setStreamText('');
                break;
            case 'error':
                console.error('WS backend error', data.message || data.error || data);
                setMusicDucking(false);
                resetVoiceActivity();
                setStageWithAutoReset('idle');
                break;
            case 'stream_aborted':
                setMusicDucking(false);
                setStageWithAutoReset('idle');
                setStreaming(false);
                setStreamText((prevStreamText) => {
                    if (prevStreamText) {
                        setMessages((prev) => [
                            ...prev,
                            { role: 'assistant', text: prevStreamText + '\n[aborted]' },
                        ]);
                    }
                    return '';
                });
                break;
            case 'session_reset':
                setMusicDucking(false);
                setStageWithAutoReset('idle');
                setMessages([]);
                setStreamText('');
                setStreaming(false);
                break;
            case 'voice_status':
                voiceStatusRef.current = data.status;
                isRecordingRef.current = data.status === 'listening';
                setMusicDucking(MUSIC_DUCK_ACTIVE_STATUSES.has(data.status));
                setVoiceStatus(data.status);
                setIsRecording(data.status === 'listening');
                console.debug('[voice] stage transition', voiceStageRef.current, '->', data.status);
                if (data.status === 'listening') {
                    voiceStageRef.current = 'listening';
                    setStageWithAutoReset('listening');
                }
                if (data.status === 'thinking') {
                    voiceStageRef.current = 'thinking';
                    setStageWithAutoReset('thinking');
                }
                if (data.status === 'transcribing') {
                    voiceStageRef.current = 'transcribing';
                    setStageWithAutoReset('transcribing');
                }
                if (data.status === 'speaking') {
                    voiceStageRef.current = 'speaking';
                    setStageWithAutoReset('speaking');
                }
                if (data.status === 'idle') {
                    voiceStageRef.current = 'idle';
                    setStageWithAutoReset('idle');
                    setIsVoiceStreaming(false);
                    setVoiceStreamText('');
                }
                break;
            case 'voice_transcription':
                console.info('[voice] final transcription accepted, entering transcribing stage');
                setStageWithAutoReset('transcribing');
                setMessages((prev) => [...prev, { role: 'user', text: data.text }]);
                setVoskText('');
                break;
            case 'vosk_partial':
                console.debug('[voice] transcribing partial text');
                setStageWithAutoReset('transcribing');
                setVoskText(data.text || '');
                break;
            case 'vosk_final':
                console.info('[voice] final Vosk text received');
                setStageWithAutoReset('transcribing');
                // Final Vosk result
                setMessages((prev) => [...prev, { role: 'user', text: data.text }]);
                setVoskText('');
                break;
            case 'ai_start':
                console.info('[voice] AI generation started');
                setMusicDucking(true);
                setStageWithAutoReset('thinking');
                setVoiceStreamText('');
                setIsVoiceStreaming(true);
                break;
            case 'ai_delta':
                console.debug('[voice] AI stream delta received');
                setMusicDucking(true);
                setStageWithAutoReset('generating');
                setVoiceStreamText(data.text || '');
                break;
            case 'ai_final':
                console.info('[voice] AI generation finished');
                setMusicDucking(true);
                setStageWithAutoReset(voiceStatusRef.current === 'speaking' ? 'speaking' : 'generating');
                setVoiceStreamText(data.text || '');
                // We keep isVoiceStreaming true while speaking, speaking status comes from voice_status
                break;
            case 'tts_audio_start':
                console.info('[voice] TTS audio stream started');
                setMusicDucking(true);
                acceptTtsAudioRef.current = true;
                resetTtsAudioPlayback();
                setStageWithAutoReset('speaking');
                break;
            case 'tts_audio_chunk':
                playPcmChunk(data.audio, data.sample_rate || data.sampleRate || 22050);
                break;
            case 'tts_audio_end':
                console.info('[voice] TTS audio stream ended');
                setMusicDucking(false);
                acceptTtsAudioRef.current = false;
                resetTtsAudioPlayback();
                break;
            case 'tts_audio_cancel':
                console.info('[voice] TTS audio stream cancelled');
                setMusicDucking(false);
                stopTtsAudioPlayback();
                break;
            case 'voice_done':
                console.info('[voice] full voice execution finished');
                setMusicDucking(false);
                setIsVoiceStreaming(false);
                setVoiceStreamText('');
                if (!isRecordingRef.current) setStageWithAutoReset('idle');
                break;
            case 'ai_aborted':
                console.warn('[voice] AI generation aborted');
                setMusicDucking(false);
                setStageWithAutoReset('idle');
                setVoiceStreamText((prev) => prev + ' [aborted]');
                setTimeout(() => setIsVoiceStreaming(false), 2000);
                break;
            default:
                break;
        }
    }, [playPcmChunk, resetTtsAudioPlayback, resetVoiceActivity, setMusicDucking, setStageWithAutoReset, stopTtsAudioPlayback]);

    const connect = useCallback(async () => {
        if (!shouldReconnectRef.current) return;
        if (reconnectTimer.current) {
            clearTimeout(reconnectTimer.current);
            reconnectTimer.current = null;
        }
        if (wsRef.current) {
            wsRef.current.onclose = null;
            wsRef.current.close();
        }

        setConnStatus('connecting');
        let url;
        try {
            url = await authorizedWebSocketUrl(WS_URL);
        } catch (error) {
            console.error('[voice] websocket authorization failed', error);
            setConnStatus('disconnected');
            return;
        }
        if (!shouldReconnectRef.current) return;
        const ws = new WebSocket(url);
        wsRef.current = ws;
        console.info('[voice] websocket connecting', WS_URL);

        ws.onopen = () => {
            setConnStatus('connected');
            clearTimeout(reconnectTimer.current);
            console.info('[voice] websocket open');
        };

        ws.onclose = (event) => {
            if (wsRef.current !== ws) {
                console.debug('[voice] ignoring stale websocket close event');
                return;
            }
            console.warn('[voice] websocket closed', { code: event.code, reason: event.reason, wasClean: event.wasClean });
            setConnStatus('disconnected');
            resetVoiceActivity();
            wsRef.current = null;
            if (shouldReconnectRef.current && readVoiceReconnectEnabled()) {
                reconnectTimer.current = setTimeout(() => {
                    connectRef.current?.();
                }, 3000);
            } else {
                console.info('[voice] auto reconnect disabled by settings');
            }
        };

        ws.onerror = (event) => {
            if (wsRef.current !== ws) {
                console.debug('[voice] ignoring stale websocket error event');
                return;
            }
            console.error('[voice] websocket error', event);
            resetVoiceActivity();
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error("WS Parse error", e);
            }
        };
    }, [handleServerMessage, resetVoiceActivity]);
    useEffect(() => {
        connectRef.current = connect;
    }, [connect]);

    const fetchConversations = useCallback(async () => {
        try {
            setLastApiError(null);
            const data = await apiFetch('/conversations');
            setConversations(data);
            return data;
        } catch (e) {
            const msg = e?.message || 'Failed to fetch conversations';
            setLastApiError(msg);
            console.error(msg, e);
        }
    }, []);

    const createConversation = useCallback(async () => {
        try {
            setLastApiError(null);
            const data = await apiFetch('/conversations', { method: 'POST' });
            await fetchConversations();
            return data;
        } catch (e) {
            const msg = e?.message || 'Failed to create conversation';
            setLastApiError(msg);
            console.error(msg, e);
        }
    }, [fetchConversations]);

    const deleteConversation = useCallback(async (id) => {
        try {
            setLastApiError(null);
            await apiFetch(`/conversations/${id}`, { method: 'DELETE' });
            await fetchConversations();
            if (currentConvId === id) {
                setCurrentConvId(null);
                setMessages([]);
            }
        } catch (e) {
            const msg = e?.message || 'Failed to delete conversation';
            setLastApiError(msg);
            console.error(msg, e);
        }
    }, [currentConvId, fetchConversations]);

    const renameConversation = useCallback(async (id, newTitle) => {
        try {
            setLastApiError(null);
            await apiFetch(`/conversations/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle })
            });
            await fetchConversations();
        } catch (e) {
            const msg = e?.message || 'Failed to rename conversation';
            setLastApiError(msg);
            console.error(msg, e);
        }
    }, [fetchConversations]);

    const chatWsRef = useRef(null);
    const chatReconnectTimer = useRef(null);
    const currentConvIdRef = useRef(currentConvId);

    useEffect(() => {
        currentConvIdRef.current = currentConvId;
    }, [currentConvId]);

    const connectChat = useCallback(async (convId) => {
        if (!shouldReconnectRef.current) return;
        if (!convId) {
            setChatConnStatus('disconnected');
            return;
        }
        if (chatWsRef.current) {
            chatWsRef.current.onclose = null;
            chatWsRef.current.close();
            chatWsRef.current = null;
        }

        setChatConnStatus('connecting');
        let url;
        try {
            url = await authorizedWebSocketUrl(`${CHAT_WS_URL}/${convId}`);
        } catch (error) {
            console.error('[chat] websocket authorization failed', error);
            setChatConnStatus('disconnected');
            return;
        }
        if (!shouldReconnectRef.current) return;
        const ws = new WebSocket(url);
        chatWsRef.current = ws;
        console.info('[chat] websocket connecting', `${CHAT_WS_URL}/${convId}`);

        ws.onopen = () => {
            setChatConnStatus('connected');
            console.info('[chat] websocket open', convId);
            if (chatReconnectTimer.current) {
                clearTimeout(chatReconnectTimer.current);
                chatReconnectTimer.current = null;
            }
        };
        ws.onclose = (event) => {
            if (chatWsRef.current !== ws) {
                console.debug('[chat] ignoring stale websocket close event', convId);
                return;
            }
            console.warn('[chat] websocket closed', { convId, code: event.code, reason: event.reason, wasClean: event.wasClean });
            chatWsRef.current = null;
            setChatConnStatus('disconnected');
            if (!shouldReconnectRef.current) return;
            chatReconnectTimer.current = setTimeout(() => {
                chatReconnectTimer.current = null;
                if (shouldReconnectRef.current && currentConvIdRef.current === convId) {
                    connectChatRef.current?.(convId);
                }
            }, 2000);
        };
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error("Chat WS Parse error", e);
            }
        };
    }, [handleServerMessage]);
    useEffect(() => {
        connectChatRef.current = connectChat;
    }, [connectChat]);

    useEffect(() => {
        shouldReconnectRef.current = true;
        connect();
        fetchConversations();
        return () => {
            shouldReconnectRef.current = false;
            clearTimeout(reconnectTimer.current);
            clearTimeout(chatReconnectTimer.current);
            if (stageResetTimerRef.current) clearTimeout(stageResetTimerRef.current);
            if (wsRef.current) {
                wsRef.current.onclose = null;
                wsRef.current.onerror = null;
                wsRef.current.onmessage = null;
                wsRef.current.close();
                wsRef.current = null;
            }
            if (chatWsRef.current) {
                chatWsRef.current.onclose = null;
                chatWsRef.current.onerror = null;
                chatWsRef.current.onmessage = null;
                chatWsRef.current.close();
                chatWsRef.current = null;
            }
            stopTtsAudioPlayback();
            if (audioContextRef.current) audioContextRef.current.close().catch(() => {});
        };
    }, [connect, fetchConversations, stopTtsAudioPlayback]);

    useEffect(() => {
        if (currentConvId) {
            connectChat(currentConvId);
        }
    }, [currentConvId, connectChat]);

    const sendMessage = useCallback((type, payload = {}) => {
        // task.* commands are only handled by the voice WebSocket (/ws/voice), not chat
        const useVoiceWs = typeof type === 'string' && type.startsWith('task.');
        const targetWs = useVoiceWs ? wsRef.current : (chatWsRef.current?.readyState === WebSocket.OPEN ? chatWsRef.current : wsRef.current);
        if (targetWs && targetWs.readyState === WebSocket.OPEN) {
            if (useVoiceWs) {
                console.debug('[voice] sendMessage', type, payload);
            } else {
                console.debug('[chat] sendMessage', type, payload);
            }
            targetWs.send(JSON.stringify({ type, ...payload }));
        } else {
            console.warn("WS not connected, cannot send", type);
        }
    }, []);
    const sendVoiceCommand = useCallback((type, payload = {}) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            console.debug('[voice] sendVoiceCommand', type, payload);
            wsRef.current.send(JSON.stringify({ type, ...payload }));
        } else {
            console.warn("Voice WS not connected, cannot send", type);
        }
    }, []);

    const toggleVoice = useCallback((options = {}) => {
        const { transcriptionOnly = false, interrupt = false } = options;
        const outputActive = (
            isVoiceStreamingRef.current ||
            ['thinking', 'speaking'].includes(voiceStatusRef.current) ||
            ['thinking', 'generating', 'speaking'].includes(voiceStageRef.current)
        );
        if ((interrupt || outputActive) && !transcriptionOnly) {
            suppressInterruptedVoiceRef.current = true;
            stopTtsAudioPlayback();
            voiceStatusRef.current = 'listening';
            voiceStageRef.current = 'listening';
            isRecordingRef.current = true;
            isVoiceStreamingRef.current = false;
            setIsVoiceStreaming(false);
            setVoiceStreamText('');
            setVoiceStatus('listening');
            setIsRecording(true);
            setStageWithAutoReset('listening');
            setMusicDucking(true);
            sendVoiceCommand('interrupt_voice', { start_listening: true });
            return;
        }
        sendVoiceCommand('toggle_voice', { transcription_only: transcriptionOnly });
    }, [sendVoiceCommand, setMusicDucking, setStageWithAutoReset, stopTtsAudioPlayback]);

    const startVosk = useCallback((options = {}) => {
        setIsVoskRecording(true);
        setVoskText('');
        const { transcriptionOnly = false } = options;
        sendVoiceCommand('start_vosk', { transcription_only: transcriptionOnly });
    }, [sendVoiceCommand]);

    const stopVosk = useCallback((options = {}) => {
        setIsVoskRecording(false);
        const { transcriptionOnly = false } = options;
        sendVoiceCommand('stop_vosk', { transcription_only: transcriptionOnly });
    }, [sendVoiceCommand]);

    const abort = useCallback(() => {
        suppressInterruptedVoiceRef.current = true;
        stopTtsAudioPlayback();
        if (chatWsRef.current?.readyState === WebSocket.OPEN) {
            chatWsRef.current.send(JSON.stringify({ type: 'abort' }));
        }
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'abort' }));
        }
    }, [stopTtsAudioPlayback]);

    const toggleThinking = useCallback(() => {
        setThinking(prev => !prev);
    }, []);

    const value = {
        connStatus,
        connect,
        chatConnStatus,
        messages,
        setMessages,
        streamText,
        streaming,
        isRecording: isRecording || isVoskRecording,
        isVoskRecording,
        voiceStatus,
        voiceStage,
        voskText,
        conversations,
        currentConvId,
        setCurrentConvId,
        fetchConversations,
        createConversation,
        deleteConversation,
        renameConversation,
        sendMessage,
        toggleVoice,
        startVosk,
        stopVosk,
        abort,
        addEventListener,
        voiceStreamText,
        isVoiceStreaming,
        thinking,
        toggleThinking,
        lastApiError,
        clearApiError: () => setLastApiError(null),
    };

    return (
        <WebSocketContext.Provider value={value}>
            {children}
        </WebSocketContext.Provider>
    );
}

export function useWebSocket() {
    return useContext(WebSocketContext);
}
