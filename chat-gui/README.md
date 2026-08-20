# NOVA Chat GUI

The NOVA Chat GUI is the Electron + React frontend for the NOVA local AI assistant. It is built for a Raspberry Pi touchscreen dashboard, but it can also run on a development laptop while connected to the NOVA backend.

The app provides chat, voice controls, system status, weather, Swedish alert views, Spotify controls, scheduled screen settings, Telegram alert settings, and a compact home dashboard.

## Stack

- Electron for the desktop shell
- Vite for local development and production builds
- React for the renderer UI
- Tailwind CSS for styling
- Framer Motion for transitions
- Lucide React for interface icons
- WebSockets for chat, voice, and system status updates

## Project Structure

```text
chat-gui/
  src/main/              Electron main process
  src/preload/           Safe bridge between Electron and renderer
  src/renderer/          React renderer app
    src/components/      Dashboard, chat, settings, music, weather, alerts
    src/contexts/        WebSocket and keyboard state
    src/config.js        Backend URL and control-token config
  electron.vite.config.js
  eslint.config.js
  package.json
```

## Requirements

- Node.js 18+
- npm
- NOVA backend running on the configured host and port

The backend lives in the repository root and normally runs on port `8000`.

## Development

Install dependencies:

```bash
npm install
```

Start the Electron development app:

```bash
npm run dev
```

Start the backend from this folder:

```bash
npm run backend
```

In normal development, run the backend in one terminal and the GUI in another.

## Configuration

The renderer reads Vite environment variables:

```env
VITE_API_HOST=127.0.0.1
VITE_API_PORT=8000
```

State-changing actions and WebSocket connections receive a per-process control token from the loopback-only backend endpoint.

If `VITE_API_HOST` is not set, the GUI uses `window.location.hostname`. The supported deployment uses `127.0.0.1` on the same Raspberry Pi or desktop as the backend.

## Scripts

```bash
npm run dev       # Run Electron + Vite in development mode
npm run backend   # Run ../app.py
npm run lint      # Run ESLint
npm run build     # Build Electron main, preload, and renderer output
npm run preview   # Preview the production build
```

On Windows PowerShell, use `npm.cmd` if script execution policy blocks `npm`:

```powershell
npm.cmd run lint
npm.cmd run build
```

## Build Output

Production output is written to `out/`. This folder is generated and should not be committed to git.

## Backend Contract

The GUI expects the backend to provide:

- `GET /health`
- `GET /conversations`
- `POST /conversations`
- `GET /conversations/{id}`
- `WS /ws/chat/{conversation_id}`
- `WS /ws/voice`
- `GET /system/stats`
- `WS /ws/system-stats`
- Weather, alert, Spotify, Telegram, screen, and audio-source endpoints documented in the root README

State-changing requests and WebSocket connections use the local runtime authorization flow.

## Notes

This GUI is intentionally optimized for a small always-on assistant screen rather than a generic web page. Layout, spacing, controls, and navigation are designed for repeated touch use on a Raspberry Pi display.
