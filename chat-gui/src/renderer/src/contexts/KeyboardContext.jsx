import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

const STORAGE_KEY = 'nova.popupKeyboard';

const KeyboardContext = createContext(null);

function readStored() {
    try {
        const v = localStorage.getItem(STORAGE_KEY);
        if (v === null) return true; // default on
        return v === 'true';
    } catch {
        return true;
    }
}

function writeStored(enabled) {
    try {
        localStorage.setItem(STORAGE_KEY, String(enabled));
    } catch {
        // localStorage can be unavailable in restricted browser contexts.
    }
}

export function KeyboardProvider({ children }) {
    const [keyboardEnabled, setKeyboardEnabledState] = useState(readStored);
    const [focusState, setFocusState] = useState(null); // null | { isChatInput: boolean }
    const focusedElementRef = useRef(null);
    const syncInputValueRef = useRef(null); // (value: string) => void — so virtual keyboard updates React state

    useEffect(() => {
        writeStored(keyboardEnabled);
    }, [keyboardEnabled]);

    const setKeyboardEnabled = useCallback((enabled) => {
        setKeyboardEnabledState(Boolean(enabled));
    }, []);

    const value = {
        keyboardEnabled,
        setKeyboardEnabled,
        focusState,
        setFocusState,
        focusedElementRef,
        syncInputValueRef,
    };

    return (
        <KeyboardContext.Provider value={value}>
            {children}
        </KeyboardContext.Provider>
    );
}

export function useKeyboardSettings() {
    const ctx = useContext(KeyboardContext);
    if (!ctx) throw new Error('useKeyboardSettings must be used within KeyboardProvider');
    return ctx;
}

/** Call with true when this input is the main chat input. Returns { onFocus, onBlur } to attach to input/textarea. */
export function useFocusableInput(isChatInput) {
    const { setFocusState, focusedElementRef } = useKeyboardSettings();
    const onFocus = useCallback(
        (e) => {
            const el = e?.target;
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
                focusedElementRef.current = el;
            }
            setFocusState({ isChatInput: Boolean(isChatInput) });
        },
        [setFocusState, isChatInput, focusedElementRef]
    );
    const onBlur = useCallback(
        (e) => {
            const next = e?.relatedTarget;
            if (next?.closest?.('[data-virtual-keyboard]')) return;
            if (next?.closest?.('[data-chat-input-bar]')) return;
            focusedElementRef.current = null;
            setFocusState(null);
        },
        [setFocusState, focusedElementRef]
    );
    return { onFocus, onBlur };
}
