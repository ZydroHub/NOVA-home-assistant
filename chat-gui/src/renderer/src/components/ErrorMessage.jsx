/**
 * Shared error message with optional retry. Use after failed fetch or operation.
 */
export default function ErrorMessage({ message, onRetry, className = '' }) {
    return (
        <div
            className={`p-4 bg-red-500/20 border-b-2 border-red-500 text-red-200 text-[10px] font-['Press_Start_2P'] flex items-center justify-between gap-2 ${className}`}
            role="alert"
        >
            <span className="flex-1 truncate" title={message}>{message}</span>
            {onRetry && (
                <button
                    type="button"
                    onClick={onRetry}
                    className="pixel-btn px-2 py-1 text-[8px]"
                >
                    RETRY
                </button>
            )}
        </div>
    );
}
