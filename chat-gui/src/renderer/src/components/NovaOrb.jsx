import React from 'react';
import { motion } from 'framer-motion';

const ACTIVE_STATES = new Set(['listening', 'transcribing', 'thinking', 'generating', 'speaking']);

export default function NovaOrb({ voiceState = 'idle', onClick }) {
    const isActive = ACTIVE_STATES.has(voiceState);
    const handleKeyDown = (event) => {
        if (!onClick || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        onClick(event);
    };

    return (
        <motion.div
            className={`nova-orb-wrap ${isActive ? 'nova-orb-wrap-active' : 'nova-orb-wrap-idle'}`}
            aria-label="NOVA core orb"
            role="button"
            tabIndex={0}
            onClick={onClick}
            onKeyDown={handleKeyDown}
            style={{ cursor: 'pointer' }}
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.96 }}
        >
            <motion.div
                className={`nova-orb ${isActive ? 'nova-orb-active' : 'nova-orb-idle'}`}
                animate={{
                    y: isActive ? [0, -12, 0] : [0, -6, 0],
                    scale: isActive ? [1, 1.025, 1] : [1, 1.012, 1],
                }}
                transition={{ duration: isActive ? 0.9 : 2.8, repeat: Infinity, ease: 'easeInOut' }}
            >
                <div className="nova-orb-core">NOVA</div>
            </motion.div>
            <div
                className={`nova-orb-ring ${isActive ? 'nova-orb-ring-fast' : 'nova-orb-ring-slow'}`}
            />
        </motion.div>
    );
}
