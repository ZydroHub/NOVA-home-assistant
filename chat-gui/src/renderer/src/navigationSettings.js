import { CloudSun, House, MessageCircle, Music2, Newspaper, SlidersHorizontal } from 'lucide-react';

export const KEY_HIDDEN_TABS = 'nova.hiddenTabs';

export const NAV_ITEMS = [
    { to: '/', id: 'home', label: 'Home', icon: House, required: true },
    { to: '/chat', id: 'chat', label: 'Chat', icon: MessageCircle },
    { to: '/music', id: 'music', label: 'Music', icon: Music2 },
    { to: '/news', id: 'news', label: 'News', icon: Newspaper },
    { to: '/weather', id: 'weather', label: 'Weather', icon: CloudSun },
    { to: '/settings', id: 'settings', label: 'Config', icon: SlidersHorizontal, required: true },
];

const configurableIds = new Set(NAV_ITEMS.filter((item) => !item.required).map((item) => item.id));

export function readHiddenTabs() {
    try {
        const parsed = JSON.parse(localStorage.getItem(KEY_HIDDEN_TABS) || '[]');
        if (!Array.isArray(parsed)) return [];
        return parsed.filter((id) => configurableIds.has(id));
    } catch {
        return [];
    }
}

export function writeHiddenTabs(hiddenTabs) {
    try {
        const nextHiddenTabs = Array.from(new Set(hiddenTabs)).filter((id) => configurableIds.has(id));
        localStorage.setItem(KEY_HIDDEN_TABS, JSON.stringify(nextHiddenTabs));
        window.dispatchEvent(new CustomEvent('nova-settings-updated'));
    } catch {
        // localStorage can be unavailable in restricted browser contexts.
    }
}

export function getVisibleNavItems(hiddenTabs = readHiddenTabs()) {
    const hidden = new Set(hiddenTabs);
    return NAV_ITEMS.filter((item) => item.required || !hidden.has(item.id));
}

export function isRouteVisible(pathname, hiddenTabs = readHiddenTabs()) {
    const item = NAV_ITEMS.find((navItem) => navItem.to === pathname);
    if (!item) return true;
    return item.required || !hiddenTabs.includes(item.id);
}
