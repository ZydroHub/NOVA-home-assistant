/**
 * Single source of truth for backend API and WebSocket base URLs.
 * Uses the local host by default. Override only for a separately secured deployment.
 */
const host = typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_HOST != null
    ? import.meta.env.VITE_API_HOST
    : (typeof window !== 'undefined' ? (window.location?.hostname || '127.0.0.1') : '127.0.0.1');
const port = typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_PORT != null
    ? String(import.meta.env.VITE_API_PORT)
    : '8000';

const base = `${host}:${port}`;
export const API_BASE_URL = `http://${base}`;
export const WS_BASE_URL = `ws://${base}`;

export const API_URL = API_BASE_URL;
export const WS_URL = `${WS_BASE_URL}/ws/voice`;
export const CHAT_WS_URL = `${WS_BASE_URL}/ws/chat`;
