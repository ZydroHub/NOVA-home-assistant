export const springOut = [0.22, 1, 0.36, 1];

export const pageEntrance = {
    hidden: { opacity: 0, y: 18, scale: 0.992 },
    visible: {
        opacity: 1,
        y: 0,
        scale: 1,
        transition: {
            duration: 0.28,
            ease: springOut,
            when: 'beforeChildren',
            staggerChildren: 0.045,
            delayChildren: 0.03,
        },
    },
    exit: {
        opacity: 0,
        y: -10,
        scale: 0.996,
        transition: { duration: 0.16, ease: 'easeOut' },
    },
};

export const panelEntrance = {
    hidden: { opacity: 0, y: 20, scale: 0.985 },
    visible: {
        opacity: 1,
        y: 0,
        scale: 1,
        transition: { duration: 0.24, ease: springOut },
    },
};

export const itemEntrance = {
    hidden: { opacity: 0, y: 12, scale: 0.985 },
    visible: (index = 0) => ({
        opacity: 1,
        y: 0,
        scale: 1,
        transition: { duration: 0.22, delay: index * 0.025, ease: springOut },
    }),
};

export const tactile = {
    whileTap: { scale: 0.95 },
    transition: { type: 'spring', stiffness: 520, damping: 34, mass: 0.45 },
};
