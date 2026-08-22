import React, { useEffect, useRef, useState } from 'react';
import { HashRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import Home from './components/Home';
import ChatInterface from './components/ChatInterface';
import SideNav from './components/SideNav';
import MusicPage from './components/MusicPage';
import NewsPage from './components/NewsPage';
import WeatherPage from './components/WeatherPage';
import Settings from './components/Settings';
import StatusBar from './components/StatusBar';
import HeartbeatManager from './components/HeartbeatManager';
import GPIOControl from './components/GPIOControl';
import ErrorBoundary from './components/ErrorBoundary';
import VirtualKeyboard from './components/VirtualKeyboard';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { KeyboardProvider, useKeyboardSettings } from './contexts/KeyboardContext';
import { isRouteVisible, readHiddenTabs } from './navigationSettings';

const KEY_SCANLINES_ENABLED = 'nova.scanlinesEnabled';
const KEY_STATUS_BAR_ENABLED = 'nova.statusBarEnabled';

function readScanlinesEnabled() {
  try {
    const value = localStorage.getItem(KEY_SCANLINES_ENABLED);
    return value !== 'false';
  } catch {
    return true;
  }
}

function readStatusBarEnabled() {
  try {
    const value = localStorage.getItem(KEY_STATUS_BAR_ENABLED);
    return value !== 'false';
  } catch {
    return true;
  }
}

// HashRouter so routes work when the app is loaded from file:// (built Electron app)

function OverlayKeyboard() {
  const location = useLocation();
  const { keyboardEnabled, focusState, focusedElementRef, syncInputValueRef } = useKeyboardSettings();
  const isOnChatRoute = location.pathname === '/chat';
  const show = keyboardEnabled && focusState && (!isOnChatRoute || !focusState.isChatInput);
  return <VirtualKeyboard visible={show} mode="overlay" focusedElementRef={focusedElementRef} syncInputValueRef={syncInputValueRef} />;
}

const AnimatedRoutes = () => {
  const location = useLocation();
  const [hiddenTabs, setHiddenTabs] = React.useState(readHiddenTabs);
  const navigate = useNavigate();

  React.useEffect(() => {
    const syncHiddenTabs = () => setHiddenTabs(readHiddenTabs());
    window.addEventListener('storage', syncHiddenTabs);
    window.addEventListener('nova-settings-updated', syncHiddenTabs);
    return () => {
      window.removeEventListener('storage', syncHiddenTabs);
      window.removeEventListener('nova-settings-updated', syncHiddenTabs);
    };
  }, []);

  React.useEffect(() => {
    if (!isRouteVisible(location.pathname, hiddenTabs)) {
      navigate('/', { replace: true });
    }
  }, [hiddenTabs, location.pathname, navigate]);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        className="h-full min-h-0 overflow-hidden touch-pan-y"
        initial={{ opacity: 0, y: 18, scale: 0.992 }}
        animate={{ opacity: 1, x: 0, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -10, scale: 0.996 }}
        transition={{ type: 'spring', stiffness: 420, damping: 34, mass: 0.65 }}
      >
        <Routes location={location}>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<ChatInterface />} />
          <Route path="/music" element={<MusicPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/weather" element={<WeatherPage />} />
          <Route path="/heartbeat" element={<HeartbeatManager />} />
          <Route path="/gpio" element={<GPIOControl />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
};

function RandomScanlineOverlay() {
  const [active, setActive] = useState(false);
  const delayRef = useRef(null);
  const burstRef = useRef(null);

  useEffect(() => {
    const triggerBurst = () => {
      setActive(true);
      burstRef.current = setTimeout(() => {
        setActive(false);
        scheduleNext();
      }, 8000);
    };

    const scheduleNext = () => {
      const nextDelayMs = (20 + Math.random() * 10) * 1000;
      delayRef.current = setTimeout(triggerBurst, nextDelayMs);
    };

    // Show a first pulse quickly so users can verify the feature is working.
    delayRef.current = setTimeout(triggerBurst, 1200);

    return () => {
      if (delayRef.current) clearTimeout(delayRef.current);
      if (burstRef.current) clearTimeout(burstRef.current);
    };
  }, []);

  return (
    <>
      <div className={`scanline-overlay ${active ? 'active' : ''}`} />
      <div className={`scanline-sweep ${active ? 'active' : ''}`} />
    </>
  );
}

export default function App() {
  const [scanlinesEnabled, setScanlinesEnabled] = useState(readScanlinesEnabled);
  const [statusBarEnabled, setStatusBarEnabled] = useState(readStatusBarEnabled);

  useEffect(() => {
    const applyPrefs = () => {
      setScanlinesEnabled(readScanlinesEnabled());
      setStatusBarEnabled(readStatusBarEnabled());
    };

    applyPrefs();
    window.addEventListener('storage', applyPrefs);
    window.addEventListener('nova-settings-updated', applyPrefs);
    return () => {
      window.removeEventListener('storage', applyPrefs);
      window.removeEventListener('nova-settings-updated', applyPrefs);
    };
  }, []);

  return (
    <HashRouter>
      <WebSocketProvider>
        <KeyboardProvider>
          <div className="flex flex-col h-screen w-screen overflow-hidden bg-[var(--nova-bg)] text-[var(--nova-text)]">
            {statusBarEnabled ? <StatusBar /> : null}
            <div className="flex-1 overflow-hidden relative w-full flex">
              {/* CRT scanline overlay only for the route content area */}
              {scanlinesEnabled ? <RandomScanlineOverlay /> : null}
              <SideNav />
              <ErrorBoundary>
                <div className="flex-1 min-w-0 min-h-0">
                  <AnimatedRoutes />
                </div>
              </ErrorBoundary>
            </div>
            <OverlayKeyboard />
          </div>
        </KeyboardProvider>
      </WebSocketProvider>
    </HashRouter>
  );
}
