import React from 'react';

export default class ErrorBoundary extends React.Component {
    state = { hasError: false, error: null };

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info);
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="w-full h-full flex flex-col items-center justify-center gap-4 p-6 bg-[var(--pixel-bg)] text-[var(--pixel-text)]">
                    <p className="text-center font-['Press_Start_2P'] text-sm text-[var(--pixel-primary)]">
                        Something went wrong
                    </p>
                    <p className="text-center text-xs opacity-80 max-w-md">
                        {this.state.error?.message || 'An unexpected error occurred.'}
                    </p>
                    <button
                        type="button"
                        onClick={this.handleRetry}
                        className="pixel-btn px-6 py-3 bg-[var(--pixel-primary)] text-white text-[10px] font-['Press_Start_2P']"
                    >
                        Retry
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
