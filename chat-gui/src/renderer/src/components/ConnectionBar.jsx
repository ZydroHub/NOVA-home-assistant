import React from 'react';

export default function ConnectionBar({ status, onRetry }) {
    const labels = {
        connected: 'Connected',
        disconnected: 'Disconnected — tap to retry',
        connecting: 'Connecting…',
    };

    const styles = {
        connected: 'bg-[var(--pixel-bg)] text-green-500 border-green-500',
        disconnected: 'bg-[var(--pixel-bg)] text-red-500 border-red-500',
        connecting: 'bg-[var(--pixel-bg)] text-yellow-500 border-yellow-500',
    };

    const handleClick = () => {
        if (status === 'disconnected' && onRetry) onRetry();
    };

    return (
        <div
            role={status === 'disconnected' && onRetry ? 'button' : undefined}
            tabIndex={status === 'disconnected' && onRetry ? 0 : undefined}
            onClick={handleClick}
            onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && status === 'disconnected' && onRetry) onRetry(); }}
            className={`flex items-center justify-center gap-2 p-1 text-xs font-['Press_Start_2P'] uppercase border-2 ${styles[status] || ''} ${status === 'disconnected' && onRetry ? 'cursor-pointer hover:opacity-90' : ''}`}
        >
            <span className={`w-2 h-2 ${status === 'connecting' ? 'animate-pulse' : ''} bg-current opacity-100`} />
            <span>{labels[status] || status}</span>
        </div>
    );
}
