import { apiFetch } from './apiClient.js';

export const WEATHER_REFRESH_MS = 120000;
export const ALERT_REFRESH_MS = 900000;

const ALERT_FETCH_TIMEOUT_MS = 45000;

let latestWeatherCache = null;
let weatherRequest = null;

const alertsCacheByRegion = new Map();
const alertRequestsByRegion = new Map();

export function isCacheFresh(entry, maxAgeMs) {
    return entry && Date.now() - entry.updatedAt < maxAgeMs;
}

export function getWeatherCache() {
    return latestWeatherCache;
}

export async function fetchLatestWeather() {
    if (weatherRequest) return weatherRequest;

    weatherRequest = apiFetch('/integrations/weather?latitude=59.3293&longitude=18.0686')
        .then((data) => {
            if (data?.error) {
                const err = new Error(data.error);
                err.body = data;
                throw err;
            }

            latestWeatherCache = {
                data,
                updatedAt: Date.now(),
            };
            return latestWeatherCache;
        })
        .finally(() => {
            weatherRequest = null;
        });

    return weatherRequest;
}

function toDisplayText(value) {
    if (value == null) return '';
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return String(value).trim();
    }
    if (Array.isArray(value)) {
        return value.map(toDisplayText).filter(Boolean).join(', ').trim();
    }
    if (typeof value === 'object') {
        const preferred = value.Description || value.description || value.name || value.title || value.Type || value.type;
        if (preferred != null) return toDisplayText(preferred);
        try {
            return JSON.stringify(value);
        } catch {
            return '';
        }
    }
    return '';
}

function normalizeAlertItem(item) {
    const source = toDisplayText(item?.source) || 'Alert';
    const title = toDisplayText(item?.title) || toDisplayText(item?.Description) || 'Untitled alert';
    const location = toDisplayText(item?.location ?? item?.Area ?? item?.area);
    const published = toDisplayText(item?.published);
    const priorityLabel = toDisplayText(item?.priority_label) || 'News';
    const priorityRank = Number(item?.priority_rank) || 0;

    return {
        ...item,
        source,
        title,
        location,
        published,
        priority_label: priorityLabel,
        priority_rank: priorityRank,
    };
}

export function getAlertsCache(region) {
    return alertsCacheByRegion.get(region) || null;
}

export function clearAlertsCache() {
    alertsCacheByRegion.clear();
    alertRequestsByRegion.clear();
}

export async function fetchLatestAlerts(region) {
    const activeRequest = alertRequestsByRegion.get(region);
    if (activeRequest) return activeRequest;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), ALERT_FETCH_TIMEOUT_MS);
    const requestedLimit = region === 'sweden' ? '180' : '60';
    const query = new URLSearchParams({
        limit: requestedLimit,
        region,
    });

    const request = apiFetch(`/integrations/swedish-alerts?${query.toString()}`, { signal: controller.signal })
        .then((data) => {
            const entry = {
                items: (Array.isArray(data?.items) ? data.items : []).map(normalizeAlertItem),
                statistics: data?.statistics && typeof data.statistics === 'object' ? data.statistics : {},
                updatedAt: Date.now(),
            };
            alertsCacheByRegion.set(region, entry);
            return entry;
        })
        .finally(() => {
            clearTimeout(timeoutId);
            alertRequestsByRegion.delete(region);
        });

    alertRequestsByRegion.set(region, request);
    return request;
}
