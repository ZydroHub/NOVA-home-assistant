import { API_BASE_URL } from './config.js';

let runtimeControlToken = '';
let runtimeControlTokenPromise = null;

export async function resolveControlToken(forceRefresh = false) {
    if (forceRefresh) {
        runtimeControlToken = '';
        runtimeControlTokenPromise = null;
    }
    if (runtimeControlToken) return runtimeControlToken;
    if (!runtimeControlTokenPromise) {
        runtimeControlTokenPromise = fetch(`${API_BASE_URL}/system/control-token`)
            .then(async (res) => {
                if (!res.ok) return '';
                const body = await res.json().catch(() => null);
                runtimeControlToken = typeof body?.token === 'string' ? body.token : '';
                return runtimeControlToken;
            })
            .catch(() => '')
            .finally(() => {
                runtimeControlTokenPromise = null;
            });
    }
    return runtimeControlTokenPromise;
}

export async function authorizedWebSocketUrl(url) {
    const token = await resolveControlToken();
    const authorizedUrl = new URL(url);
    if (token) {
        authorizedUrl.searchParams.set('token', token);
    }
    return authorizedUrl.toString();
}

/**
 * Fetch with resp.ok check. Throws with a message if not ok.
 * @param {string} path - Path relative to API_BASE_URL (e.g. '/conversations')
 * @param {RequestInit} [options] - fetch options
 * @returns {Promise<unknown>} - Parsed JSON body
 */
export async function apiFetch(path, options = {}) {
    const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
    const method = String(options.method || 'GET').toUpperCase();
    const needsControlToken = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const headers = new Headers(options.headers || {});
    if (needsControlToken && !headers.has('X-NOVA-Token')) {
        const token = await resolveControlToken();
        if (token) headers.set('X-NOVA-Token', token);
    }
    let res = await fetch(url, { ...options, headers });
    if (needsControlToken && (res.status === 401 || res.status === 403)) {
        const refreshedToken = await resolveControlToken(true);
        if (refreshedToken) {
            headers.set('X-NOVA-Token', refreshedToken);
            res = await fetch(url, { ...options, headers });
        }
    }
    let body;
    const contentType = res.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
        try {
            body = await res.json();
        } catch {
            body = null;
        }
    } else {
        body = null;
    }
    if (!res.ok) {
        let msg = null;
        if (body != null) {
            if (body.detail != null) msg = body.detail;
            else if (body.message != null) msg = body.message;
            else if (typeof body === 'string') msg = body;
        }
        if (msg == null) msg = res.statusText || `Request failed (${res.status})`;
        const err = new Error(msg);
        err.status = res.status;
        err.body = body;
        throw err;
    }
    return body;
}
