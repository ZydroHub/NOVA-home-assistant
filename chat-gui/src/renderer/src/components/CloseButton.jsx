import React from 'react';
import { X } from 'lucide-react';

const CloseButton = () => {
    const handleClose = () => {
        if (window.electron && window.electron.quit) {
            window.electron.quit();
        } else {
            console.log('Close button clicked (Electron API not available)');
            // Fallback for non-electron environments or if API is missing
            window.close();
        }
    };

    return (
        <button
            onClick={handleClose}
            className="absolute top-4 right-4 z-[9999] w-10 h-10 flex items-center justify-center bg-red-500 hover:bg-red-600 text-white border-2 border-white shadow-[4px_4px_0_0_rgba(0,0,0,1)] active:translate-y-1 active:shadow-none transition-all"
            aria-label="Close Application"
            title="CLOSE SYSTEM"
        >
            <X size={20} classname="pixel-icon" />
        </button>
    );
};

export default CloseButton;
