import React, { useState, useCallback } from 'react';
import { ArrowUp, CornerDownLeft, Delete, Space } from 'lucide-react';

const ROW_NUM = '1234567890'.split('');
const ROW1 = 'QWERTYUIOP'.split('');
const ROW2 = 'ASDFGHJKL'.split('');
const ROW3 = 'ZXCVBNM'.split('');

const KEY_BASE =
    'flex min-w-0 items-center justify-center rounded-[16px] border border-cyan-100/[0.14] bg-white/[0.055] text-cyan-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_8px_20px_rgba(0,0,0,0.18)] transition-all duration-150 hover:border-cyan-200/35 hover:bg-cyan-300/[0.1] active:translate-y-0.5 active:scale-[0.98] active:bg-cyan-300/[0.14] select-none touch-manipulation focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#07101f]';

const KEY_STYLE =
    `${KEY_BASE} flex-1 h-12 px-1 font-['Inter'] text-lg font-semibold sm:h-[52px]`;

const KEY_SPECIAL =
    `${KEY_BASE} flex-[1.25] h-12 gap-1.5 px-2 font-['Plus_Jakarta_Sans'] text-[11px] font-bold text-cyan-100/85 sm:h-[52px]`;

const KEY_ACCENT =
    'flex min-w-0 items-center justify-center rounded-[16px] border border-cyan-200/45 bg-[linear-gradient(145deg,rgba(33,211,255,0.86),rgba(31,112,255,0.76))] text-slate-950 shadow-[0_0_24px_rgba(26,209,255,0.2),0_10px_24px_rgba(0,0,0,0.22)] transition-all duration-150 hover:brightness-110 active:translate-y-0.5 active:scale-[0.98] select-none touch-manipulation focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-100/80 focus-visible:ring-offset-2 focus-visible:ring-offset-[#07101f]';

const KEY_SPACE = `${KEY_ACCENT} flex-[3] h-12 gap-2 px-3 font-['Plus_Jakarta_Sans'] text-xs font-bold sm:h-[52px]`;
const KEY_ENTER = `${KEY_ACCENT} flex-1 h-12 min-w-[76px] gap-1.5 px-3 font-['Plus_Jakarta_Sans'] text-xs font-bold sm:h-[52px]`;

const SELECTION_TYPES = new Set(['text', 'search', 'url', 'tel', 'password']);

function supportsSelection(el) {
    if (!el) return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    return SELECTION_TYPES.has((el.type || 'text').toLowerCase());
}

function insertAtCursor(el, text) {
    if (!el || typeof el.value === 'undefined') return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    const before = el.value.slice(0, start);
    const after = el.value.slice(end);
    const newValue = before + text + after;
    el.value = newValue;
    if (supportsSelection(el)) {
        const newPos = start + text.length;
        el.setSelectionRange(newPos, newPos);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function backspace(el) {
    if (!el || typeof el.value === 'undefined') return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    if (start === 0 && end === 0) return;
    const delStart = start === end ? start - 1 : start;
    const delEnd = end;
    const before = el.value.slice(0, delStart);
    const after = el.value.slice(delEnd);
    el.value = before + after;
    if (supportsSelection(el)) {
        el.setSelectionRange(delStart, delStart);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function keyEnter(el) {
    if (!el) return;
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: false, bubbles: true }));
}

function syncStateAfterChange(el, syncRef) {
    if (el && typeof el.value !== 'undefined' && syncRef?.current) {
        syncRef.current(el.value);
    }
}

export default function VirtualKeyboard({ visible, mode = 'inline', focusedElementRef = null, syncInputValueRef = null }) {
    const [shift, setShift] = useState(false);

    const getTarget = useCallback(() => {
        if (focusedElementRef?.current) return focusedElementRef.current;
        const el = document.activeElement;
        if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return el;
        return null;
    }, [focusedElementRef]);

    const handleKey = useCallback(
        (char) => (e) => {
            e.preventDefault();
            const el = getTarget();
            if (!el) return;
            insertAtCursor(el, shift ? char : char.toLowerCase());
            syncStateAfterChange(el, syncInputValueRef);
            setShift(false);
        },
        [getTarget, shift, syncInputValueRef]
    );

    const handleNumberKey = useCallback(
        (char) => (e) => {
            e.preventDefault();
            const el = getTarget();
            if (!el) return;
            insertAtCursor(el, char);
            syncStateAfterChange(el, syncInputValueRef);
        },
        [getTarget, syncInputValueRef]
    );

    const handleBackspace = useCallback(
        (e) => {
            e.preventDefault();
            const el = getTarget();
            backspace(el);
            syncStateAfterChange(el, syncInputValueRef);
        },
        [getTarget, syncInputValueRef]
    );

    const handleSpace = useCallback(
        (e) => {
            e.preventDefault();
            const el = getTarget();
            insertAtCursor(el, ' ');
            syncStateAfterChange(el, syncInputValueRef);
        },
        [getTarget, syncInputValueRef]
    );

    const handleEnter = useCallback(
        (e) => {
            e.preventDefault();
            keyEnter(getTarget());
        },
        [getTarget]
    );

    const handleShift = useCallback((e) => {
        e.preventDefault();
        setShift((s) => !s);
    }, []);

    if (!visible) {
        if (mode === 'inline') return <div className="h-0 overflow-hidden" aria-hidden />;
        return null;
    }

    const containerClass =
        mode === 'overlay'
            ? 'fixed inset-x-0 bottom-0 z-50 border-t border-cyan-100/[0.16] bg-[rgba(6,13,30,0.82)] px-2 py-3 pb-[max(12px,env(safe-area-inset-bottom))] shadow-[0_-22px_54px_rgba(0,0,0,0.4)] backdrop-blur-2xl'
            : 'flex-shrink-0 border-t border-white/[0.08] bg-slate-950/45 px-2 py-3 pb-[max(10px,env(safe-area-inset-bottom))] backdrop-blur-xl';

    const shellClass =
        mode === 'overlay'
            ? 'mx-auto flex w-full max-w-5xl flex-col gap-2 rounded-[24px] border border-cyan-100/[0.12] bg-white/[0.035] p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]'
            : 'flex w-full flex-col gap-2 rounded-b-[28px] bg-transparent px-1';

    const renderCharacterKey = (char, handler) => (
        <button
            key={char}
            type="button"
            className={KEY_STYLE}
            onMouseDown={(e) => {
                e.preventDefault();
                handler(char)(e);
            }}
            onTouchEnd={(e) => {
                e.preventDefault();
                handler(char)(e);
            }}
        >
            {char}
        </button>
    );

    return (
        <div
            className={containerClass}
            role="group"
            aria-label="On-screen keyboard"
            data-virtual-keyboard
        >
            <div className={shellClass}>
                <div className="flex w-full gap-1.5">
                    {ROW_NUM.map((char) => renderCharacterKey(char, handleNumberKey))}
                </div>
                <div className="flex w-full gap-1.5">
                    {(shift ? ROW1 : ROW1.map((c) => c.toLowerCase())).map((char) => renderCharacterKey(char, handleKey))}
                </div>
                <div className="flex w-full gap-1.5 px-[4.5%]">
                    {(shift ? ROW2 : ROW2.map((c) => c.toLowerCase())).map((char) => renderCharacterKey(char, handleKey))}
                </div>
                <div className="flex w-full gap-1.5">
                    <button
                        type="button"
                        className={`${KEY_SPECIAL} ${shift ? 'border-cyan-200/55 bg-cyan-300/[0.16] text-cyan-50 shadow-[0_0_22px_rgba(34,211,238,0.18),inset_0_1px_0_rgba(255,255,255,0.08)]' : ''}`}
                        onMouseDown={handleShift}
                        onTouchEnd={(e) => {
                            e.preventDefault();
                            handleShift(e);
                        }}
                        aria-pressed={shift}
                        aria-label="Shift"
                        title="Shift"
                    >
                        <ArrowUp size={16} />
                        <span>{shift ? 'Caps' : 'Shift'}</span>
                    </button>
                    {(shift ? ROW3 : ROW3.map((c) => c.toLowerCase())).map((char) => renderCharacterKey(char, handleKey))}
                    <button
                        type="button"
                        className={KEY_SPECIAL}
                        onMouseDown={handleBackspace}
                        onTouchEnd={(e) => {
                            e.preventDefault();
                            handleBackspace(e);
                        }}
                        aria-label="Backspace"
                        title="Backspace"
                    >
                        <Delete size={17} />
                    </button>
                </div>
                <div className="flex w-full gap-2">
                    <button
                        type="button"
                        className={KEY_SPACE}
                        onMouseDown={handleSpace}
                        onTouchEnd={(e) => {
                            e.preventDefault();
                            handleSpace(e);
                        }}
                        aria-label="Space"
                        title="Space"
                    >
                        <Space size={18} />
                        <span>Space</span>
                    </button>
                    <button
                        type="button"
                        className={KEY_ENTER}
                        onMouseDown={handleEnter}
                        onTouchEnd={(e) => {
                            e.preventDefault();
                            handleEnter(e);
                        }}
                        aria-label="Enter"
                        title="Enter"
                    >
                        <CornerDownLeft size={17} />
                        <span>Enter</span>
                    </button>
                </div>
            </div>
        </div>
    );
}
