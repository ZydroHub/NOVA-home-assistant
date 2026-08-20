#!/usr/bin/env bash
# Start NOVA: backend (FastAPI) then Electron GUI.
# When you close the GUI, the backend is stopped too.

# When run from desktop, PATH may not include node/npm — load your shell profile
if [ -f "$HOME/.profile" ]; then
    source "$HOME/.profile"
fi
if [ -f "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi

# Still no npm? Add common locations and try nvm
if ! command -v npm &>/dev/null; then
    export PATH="/usr/local/bin:/usr/bin:$HOME/.local/bin:$PATH"
    # NVM (Node Version Manager)
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        source "$HOME/.nvm/nvm.sh"
    fi
    # NVM puts node in versions/node/*/bin
    for nvm_dir in "$HOME/.nvm/versions/node"/*/bin; do
        [ -d "$nvm_dir" ] && PATH="$nvm_dir:$PATH"
    done
fi

resolve_script_path() {
    local src="$1"
    if command -v readlink >/dev/null 2>&1; then
        readlink -f "$src" 2>/dev/null || echo "$src"
    else
        echo "$src"
    fi
}

find_project_root() {
    local start_dir="$1"
    local current="$start_dir"
    while [ "$current" != "/" ]; do
        if [ -f "$current/requirements.txt" ] && [ -f "$current/app.py" ]; then
            echo "$current"
            return 0
        fi
        current="$(dirname "$current")"
    done
    return 1
}

SCRIPT_PATH="$(resolve_script_path "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(find_project_root "$SCRIPT_DIR")"

if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="$(find_project_root "$(pwd)")"
fi

if [ -z "$PROJECT_ROOT" ]; then
    echo "ERROR: Could not find project root (missing requirements.txt/app.py)."
    echo "Run this script from inside your NOVA project or fix the desktop Exec path."
    exit 1
fi

REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
cd "$PROJECT_ROOT"

echo "=== NOVA launcher ==="
echo "Project: $PROJECT_ROOT"

ensure_linux_packages() {
    echo "Checking Linux build tools..."
    MISSING_TOOLS=()
    for tool in ninja cmake gcc g++; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            MISSING_TOOLS+=("$tool")
        fi
    done

    if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
        return 0
    fi

    echo "Missing system build tools: ${MISSING_TOOLS[*]}"
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        SUDO=""
    fi

    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y ninja-build cmake build-essential python3-dev || return 1
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y ninja-build cmake gcc gcc-c++ python3-devel || return 1
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -S --needed ninja cmake base-devel python || return 1
    else
        echo "No supported package manager found. Install ninja, cmake, gcc, g++, and Python development headers manually."
        return 1
    fi
}

# Create and activate venv if needed
if [ ! -f ".venv/bin/activate" ]; then
    echo "Creating Python venv (.venv)..."
    python3 -m venv .venv || {
        echo "ERROR: Could not create .venv. Ensure python3-venv is installed."
        exit 1
    }
fi

echo "Activating Python venv..."
source .venv/bin/activate

ensure_linux_packages || {
    echo "ERROR: Failed to install Linux build tools automatically."
    echo "Try manually with your distro package manager: install ninja, cmake, gcc, g++, and Python development headers."
    exit 1
}

# Ensure virtual environment is active before installing
if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERROR: Virtual environment is not active. Run: source .venv/bin/activate"
    exit 1
fi

# Ensure required Python dependencies are installed
echo "Installing Python dependencies from requirements.txt..."
python -m pip install --upgrade pip setuptools wheel || {
    echo "ERROR: Failed to upgrade pip/setuptools"
    exit 1
}

python -m pip install --upgrade ninja cmake scikit-build-core || {
    echo "WARNING: Some build tools failed to install; continuing..."
}

python -m pip install --no-build-isolation -r "$REQUIREMENTS_FILE" || {
    echo "ERROR: Failed to install Python dependencies from $REQUIREMENTS_FILE"
    exit 1
}

# Explicitly install semantic-router with local extras for advanced routing
echo "Installing semantic-router[local] for AI routing capabilities..."
python -m pip install "semantic-router[local]" || {
    echo "WARNING: semantic-router[local] install failed; continuing (optional feature)..."
}

echo "Python dependencies synchronized."

# Start backend in background
echo "Starting backend..."
python app.py &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend (up to 30s)..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null | grep -q 200; then
        echo "Backend is ready."
        break
    fi
    sleep 1
done

# Sync frontend dependencies
echo ""
echo "Synchronizing frontend dependencies..."
cd "$PROJECT_ROOT/chat-gui" || {
    echo "ERROR: Could not enter chat-gui directory."
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
}

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add Node.js/npm to your PATH or run this script from a terminal."
    echo "Backend is still running (PID $BACKEND_PID). Close this window to stop it, or run: kill $BACKEND_PID"
    echo "Press Enter to close..."
    read -r
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo "Running npm install (this may take a minute on first run)..."
npm install || {
    echo "ERROR: npm install failed."
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
}

echo "Frontend dependencies synchronized."
echo ""
echo "Starting NOVA window..."
if [ -f "out/main/index.js" ]; then
    npx electron . 2>/dev/null || npm run dev
else
    npm run dev
fi
GUI_EXIT=$?

# When GUI exits, stop the backend
echo "Stopping backend..."
kill $BACKEND_PID 2>/dev/null || true
exit $GUI_EXIT
