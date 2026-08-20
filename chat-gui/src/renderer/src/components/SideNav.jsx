import React from 'react';
import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import { House, MessageCircle, Music2, Newspaper, CloudSun, SlidersHorizontal } from 'lucide-react';
import { itemEntrance } from '../motionPresets.js';

const items = [
    { to: '/', label: 'Home', icon: House },
    { to: '/chat', label: 'Chat', icon: MessageCircle },
    { to: '/music', label: 'Music', icon: Music2 },
    { to: '/news', label: 'News', icon: Newspaper },
    { to: '/weather', label: 'Weather', icon: CloudSun },
    { to: '/settings', label: 'Config', icon: SlidersHorizontal }
];

export default function SideNav() {
    return (
        <motion.aside className="nova-side-nav" aria-label="NOVA navigation" initial="hidden" animate="visible">
            {items.map((item, index) => {
                const Icon = item.icon;
                return (
                    <motion.div key={item.to} custom={index} variants={itemEntrance} whileTap={{ scale: 0.95 }}>
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
