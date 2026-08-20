import { motion } from 'framer-motion';
import { ArrowLeft, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { tactile } from '../motionPresets.js';

export default function ChatHeader({ connected, onToggleSidebar, onCloseKeyboard }) {
    const navigate = useNavigate();

    const handleBack = () => {
        onCloseKeyboard?.();
        navigate('/');
    };

    return (
        <header className="z-10 grid h-16 min-h-[64px] grid-cols-3 items-center border-b border-white/[0.08] bg-slate-950/35 px-3 backdrop-blur-md">
            <div className="flex justify-start">
                <motion.button
                    onClick={handleBack}
                    className="flex min-h-[46px] min-w-[46px] items-center justify-center rounded-2xl border border-white/[0.1] bg-white/[0.04] text-cyan-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition-all hover:border-cyan-300/50 hover:bg-cyan-300/10 active:scale-95"
                    aria-label="Go back"
                    {...tactile}
                >
                    <ArrowLeft size={22} />
                </motion.button>
            </div>
            <div className="flex flex-col items-center justify-center text-center">
                <div className="text-[1.15rem] font-black leading-none tracking-[0.18em] text-white drop-shadow-[0_0_18px_rgba(26,209,255,0.32)]">NOVA</div>
                <div className="mt-1 flex items-center gap-2 text-[0.68rem] font-bold uppercase tracking-[0.22em] text-cyan-100/70">
                    <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'nova-breathing-glow bg-emerald-300 shadow-[0_0_12px_rgba(110,231,183,0.9)]' : 'nova-breathing-glow-fast bg-amber-300 shadow-[0_0_12px_rgba(252,211,77,0.8)]'}`} />
                    {connected ? 'Chat Engine Online' : 'Connecting to AI'}
                </div>
            </div>
            <div className="flex justify-end">
                <motion.button
                    onClick={onToggleSidebar}
                    className="flex min-h-[46px] min-w-[46px] items-center justify-center rounded-2xl border border-white/[0.1] bg-white/[0.04] text-cyan-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition-all hover:border-cyan-300/50 hover:bg-cyan-300/10 active:scale-95"
                    aria-label="Toggle sidebar"
                    {...tactile}
                >
                    <Menu size={22} />
                </motion.button>
            </div>
        </header>
    );
}
