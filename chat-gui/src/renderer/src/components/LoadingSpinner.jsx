/**
 * Shared loading indicator. Use when fetching data or waiting for connection.
 */
export default function LoadingSpinner({ label = 'LOADING...', className = '' }) {
    return (
        <div
            className={`flex flex-col items-center justify-center gap-3 text-[var(--pixel-text)] font-['Press_Start_2P'] animate-pulse ${className}`}
            role="status"
            aria-label={label}
        >
            <div
                className="w-10 h-10 border-4 border-[var(--pixel-border)] border-t-[var(--pixel-primary)] rounded-full animate-spin"
                style={{ animationDuration: '0.8s' }}
            />
            {label && <span className="text-[10px] uppercase tracking-wider">{label}</span>}
        </div>
    );
}
