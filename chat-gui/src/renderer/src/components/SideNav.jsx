import React from 'react';
import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import { itemEntrance } from '../motionPresets.js';
import { getVisibleNavItems, readHiddenTabs } from '../navigationSettings.js';

export default function SideNav() {
    const [hiddenTabs, setHiddenTabs] = React.useState(readHiddenTabs);

    React.useEffect(() => {
        const syncHiddenTabs = () => setHiddenTabs(readHiddenTabs());
        window.addEventListener('storage', syncHiddenTabs);
        window.addEventListener('nova-settings-updated', syncHiddenTabs);
        return () => {
            window.removeEventListener('storage', syncHiddenTabs);
            window.removeEventListener('nova-settings-updated', syncHiddenTabs);
        };
    }, []);

    const items = getVisibleNavItems(hiddenTabs);

    return (
        <motion.aside className="nova-side-nav" aria-label="NOVA navigation" initial="hidden" animate="visible">
            {items.map((item, index) => {
                const Icon = item.icon;
                return (
                    <motion.div
                        key={item.id}
                        layout
                        custom={index}
                        variants={itemEntrance}
                        initial="hidden"
                        animate="visible"
                        exit="hidden"
                        whileTap={{ scale: 0.95 }}
                    >
                        <NavLink
                            to={item.to}
                            className={({ isActive }) => `nova-side-btn ${isActive ? 'active' : ''}`}
                            title={item.label}
                        >
                            <Icon size={28} />
                            <span>{item.label}</span>
                        </NavLink>
                    </motion.div>
                );
            })}
        </motion.aside>
    );
}
