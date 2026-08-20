import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../contexts/WebSocketContext';
import { ArrowLeft, RefreshCw, Zap, Activity } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import LoadingSpinner from './LoadingSpinner';

const GPIOControl = () => {
    const { sendMessage, addEventListener, connStatus } = useWebSocket();
    const isConnected = connStatus === 'connected';
    const navigate = useNavigate();
    const [pins, setPins] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedPin, setSelectedPin] = useState(null);

    // Initial fetch of GPIO state
    useEffect(() => {
        if (isConnected) {
            sendMessage('gpio.get_all');
        }

        const handleGpioState = (data) => {
            if (data.pins) {
                setPins(data.pins);
                setLoading(false);
                // Update selected pin data if it exists
                if (selectedPin) {
                    const updated = data.pins.find(p => p.pin === selectedPin.pin);
                    if (updated) setSelectedPin(updated);
                }
            }
        };

        const unsubscribeState = addEventListener('gpio_state', handleGpioState);

        return () => {
            unsubscribeState();
        };
    }, [isConnected, sendMessage, addEventListener, selectedPin]);

    const handlePinClick = (pin) => {
        if (pin.type === 'gpio' && !pin.restricted) {
            setSelectedPin(pin);
        } else {
            setSelectedPin(null);
        }
    };

    const toggleMode = () => {
        if (!selectedPin || !isConnected) return;
        const newMode = selectedPin.mode === 'output' ? 'input' : 'output';
        sendMessage('gpio.set_mode', {
            bcm: selectedPin.bcm,
            mode: newMode
        });
    };

    const toggleValue = () => {
        if (!selectedPin || selectedPin.mode !== 'output' || !isConnected) return;
        const newValue = selectedPin.value === 1 ? 0 : 1;
        sendMessage('gpio.write', {
            bcm: selectedPin.bcm,
            value: newValue
        });
    };

    const getPinColor = (pin) => {
        if (pin.type === 'power') {
            if (pin.name.includes("5V")) return "bg-red-500 shadow-[2px_2px_0_0_rgba(0,0,0,1)]";
            return "bg-orange-500 shadow-[2px_2px_0_0_rgba(0,0,0,1)]";
        }
        if (pin.type === 'ground') return "bg-black border-2 border-[var(--pixel-border)] shadow-[2px_2px_0_0_rgba(255,255,255,0.2)]";
        if (pin.restricted) return "bg-yellow-600 border border-yellow-800 opacity-50";

        // GPIO Logic
        if (pin.mode === 'output') {
            return pin.value === 1
                ? "bg-green-500 border-2 border-green-700 animate-pulse shadow-[0_0_10px_rgba(34,197,94,0.8)]"
                : "bg-green-900 border-2 border-green-800";
        }
        if (pin.mode === 'input') {
            return pin.value === 1
                ? "bg-blue-500 border-2 border-blue-700 shadow-[0_0_10px_rgba(59,130,246,0.8)]"
                : "bg-blue-900 border-2 border-blue-800";
        }

        return "bg-slate-700 border border-slate-600";
    };

    // Split pins into left and right columns
    const leftColumn = pins.filter((_, i) => i % 2 === 0);
    const rightColumn = pins.filter((_, i) => i % 2 !== 0);

    return (
        <div className="h-full flex flex-col bg-[var(--pixel-bg)] overflow-hidden relative text-[var(--pixel-text)] font-['VT323']">
            {/* Header */}
            <div className="flex items-center justify-between p-4 z-10 bg-[var(--pixel-surface)] border-b-4 border-[var(--pixel-border)]">
                <button
                    onClick={() => navigate('/')}
                    className="pixel-btn p-3 flex items-center justify-center"
                >
                    <ArrowLeft size={24} />
                </button>
                <div className="flex items-center gap-2 text-[var(--pixel-primary)]">
                    <Activity size={20} />
                    <h1 className="text-xl font-['Press_Start_2P'] tracking-wider">GPIO CTL</h1>
                </div>
                <div className="w-10" />
            </div>

            <div className="flex-1 flex gap-4 overflow-hidden z-10 h-full p-4 pt-4">

                {/* Pin Header Visualization */}
                <div className="flex-1 flex items-center justify-center h-full min-h-0 overflow-y-auto pb-20 scroller-pixel touch-scroll-y">
                    {loading && pins.length === 0 ? (
                        <LoadingSpinner label="CONNECTING..." className="h-full" />
                    ) : (
                    <div className="bg-[var(--pixel-surface)] p-6 border-4 border-[var(--pixel-border)] shadow-[8px_8px_0_0_rgba(0,0,0,0.5)] relative">
                        {/* Board Label */}
                        <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-[var(--pixel-bg)] px-4 py-1 border-2 border-[var(--pixel-border)] text-[10px] font-['Press_Start_2P'] text-[var(--pixel-secondary)] uppercase tracking-wider">
                            RPI HEADER
                        </div>

                        <div className="flex gap-8 mt-4">
                            {/* Left Column */}
                            <div className="flex flex-col gap-3">
                                {leftColumn.map(pin => (
                                    <div key={pin.pin} className="flex items-center justify-end gap-3 h-8">
                                        <span className={`text-lg ${pin.type === 'gpio' ? 'text-[var(--pixel-text)]' : 'text-gray-500'}`}>
                                            {pin.name}
                                        </span>
                                        <button
                                            onClick={() => handlePinClick(pin)}
                                            className={`w-4 h-4 transition-all duration-75 ${getPinColor(pin)} ${selectedPin?.pin === pin.pin ? 'ring-2 ring-[var(--pixel-accent)] scale-125' : ''}`}
                                        />
                                        <span className="text-[12px] text-gray-400 w-3 text-center">{pin.pin}</span>
                                    </div>
                                ))}
                            </div>

                            {/* Right Column */}
                            <div className="flex flex-col gap-3">
                                {rightColumn.map(pin => (
                                    <div key={pin.pin} className="flex items-center justify-start gap-3 h-8">
                                        <span className="text-[12px] text-gray-400 w-3 text-center">{pin.pin}</span>
                                        <button
                                            onClick={() => handlePinClick(pin)}
                                            className={`w-4 h-4 transition-all duration-75 ${getPinColor(pin)} ${selectedPin?.pin === pin.pin ? 'ring-2 ring-[var(--pixel-accent)] scale-125' : ''}`}
                                        />
                                        <span className={`text-lg ${pin.type === 'gpio' ? 'text-[var(--pixel-text)]' : 'text-gray-500'}`}>
                                            {pin.name}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                    )}
                </div>

                {/* Controls Panel (Side or Overlay) */}
                <div className="w-48 bg-[var(--pixel-surface)] border-4 border-[var(--pixel-border)] p-4 flex flex-col gap-4 shadow-[8px_8px_0_0_rgba(0,0,0,0.5)] h-fit self-center">
                    <h2 className="text-[10px] font-['Press_Start_2P'] text-[var(--pixel-secondary)] uppercase tracking-widest border-b-2 border-[var(--pixel-border)] pb-2 mb-2">
                        PIN CONFIG
                    </h2>

                    {selectedPin ? (
                        <div className="flex flex-col gap-4">
                            <div>
                                <div className="text-xl font-bold text-[var(--pixel-primary)]">{selectedPin.name.replace('GPIO ', 'GP-')}</div>
                                <div className="text-sm text-gray-400 mt-0.5">BCM: {selectedPin.bcm}</div>
                            </div>

                            <div className="space-y-1">
                                <div className="text-xs text-gray-400 uppercase">Current Mode</div>
                                <div className={`text-lg font-bold ${selectedPin.mode === 'output' ? 'text-green-400' : selectedPin.mode === 'input' ? 'text-blue-400' : 'text-gray-400'}`}>
                                    {selectedPin.mode ? selectedPin.mode.toUpperCase() : 'UNKNOWN'}
                                </div>
                            </div>

                            <div className="space-y-1">
                                <div className="text-xs text-gray-400 uppercase">State</div>
                                <div className="flex items-center gap-2">
                                    <div className={`w-3 h-3 ${selectedPin.value ? 'bg-green-500 shadow-[0_0_5px_rgba(0,255,0,0.8)]' : 'bg-gray-700'}`} />
                                    <div className="text-xl font-bold">{selectedPin.value === 1 ? 'HIGH' : 'LOW'}</div>
                                </div>
                            </div>

                            <hr className="border-[var(--pixel-border)] my-1" />

                            <div className="flex flex-col gap-3">
                                <button
                                    onClick={toggleMode}
                                    className="pixel-btn bg-[var(--pixel-bg)] text-[var(--pixel-text)] text-sm py-2"
                                >
                                    SET {selectedPin.mode === 'output' ? 'INPUT' : 'OUTPUT'}
                                </button>

                                {selectedPin.mode === 'output' && (
                                    <button
                                        onClick={toggleValue}
                                        className={`pixel-btn text-sm py-2 font-bold ${selectedPin.value
                                            ? 'bg-red-900 text-red-100 border-red-500 hover:bg-red-800'
                                            : 'bg-green-900 text-green-100 border-green-500 hover:bg-green-800'
                                            }`}
                                    >
                                        TURN {selectedPin.value ? 'OFF' : 'ON'}
                                    </button>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-8 text-center text-gray-500 gap-2">
                            <Zap size={24} className="opacity-30" />
                            <span className="text-sm">SELECT PIN<br />TO EDIT</span>
                        </div>
                    )}
                </div>
            </div>

            {/* Legend */}
            <div className="absolute bottom-4 left-0 w-full flex justify-center gap-6 text-[10px] text-gray-400 uppercase tracking-wider font-medium z-10 bg-[var(--pixel-bg)] py-2 border-t-2 border-[var(--pixel-border)]">
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 bg-orange-500" /> Power</div>
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 bg-black border border-gray-600" /> GND</div>
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 bg-green-500" /> Output</div>
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 bg-blue-500" /> Input</div>
            </div>
        </div>
    );
};

export default GPIOControl;
