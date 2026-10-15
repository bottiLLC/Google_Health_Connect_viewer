#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================================="
echo "  App Launcher (Mac/Linux / Python-only Env)"
echo "==================================================="
echo ""

# 0. Force uv to use local system Python (disable downloading Python binaries)
export UV_PYTHON_PREFERENCE=only-system
export UV_LINK_MODE=copy

# 1. Auto-detect existing uv in standard locations
if ! command -v uv &> /dev/null; then
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
fi

# 2. Bootstrap 'uv' via Python pip if missing
if ! command -v uv &> /dev/null; then
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        echo "[ERROR] Python is not installed or not in PATH."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi

    echo "[INFO] 'uv' package manager not found. Bootstrapping via pip..."
    $PYTHON_CMD -m pip install --upgrade pip >/dev/null 2>&1
    $PYTHON_CMD -m pip install uv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install 'uv'."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
    echo "[INFO] 'uv' installed successfully."
fi

# 3. Auto-detect Python entry point with multi-tier path resolution
ENTRY_POINT=""
PROJ_ROOT="$SCRIPT_DIR"

# Check 1: In script directory
for file in app.py main.py src/app.py; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        ENTRY_POINT="$file"
        break
    fi
done

# Check 2: In current working directory
if [ -z "$ENTRY_POINT" ]; then
    for file in app.py main.py src/app.py; do
        if [ -f "$PWD/$file" ]; then
            ENTRY_POINT="$file"
            PROJ_ROOT="$PWD"
            break
        fi
    done
fi

# Check 3: In parent directory
if [ -z "$ENTRY_POINT" ]; then
    if [ -f "$SCRIPT_DIR/../app.py" ]; then
        PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
        ENTRY_POINT="app.py"
    fi
fi

cd "$PROJ_ROOT"

if [ -z "$ENTRY_POINT" ]; then
    echo "[ERROR] Python entry point (app.py / main.py / src/app.py) not found."
    echo ""
    echo "-------------------------------------------------------------"
    echo "Diagnostic Information:"
    echo "  Script Directory : $SCRIPT_DIR"
    echo "  Current Directory: $PWD"
    echo "-------------------------------------------------------------"
    echo ""
    read -p "Press [Enter] key to exit..."
    exit 1
fi

echo "[INFO] Entry point found: $ENTRY_POINT"
echo "[INFO] Working directory: $PROJ_ROOT"

# 4. Auto-create .venv with copy mode and multi-tier fallback
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (copy mode)...
    uv venv --python python --link-mode copy
    if [ $? -ne 0 ]; then
        echo "[WARNING] Standard creation failed. Retrying with --clear..."
        uv venv --python python --link-mode copy --clear
    fi
    if [ $? -ne 0 ]; then
        echo "[WARNING] 'uv venv' failed. Falling back to 'python -m venv'..."
        if [ -n "$PYTHON_CMD" ]; then
            $PYTHON_CMD -m venv .venv
        else
            python3 -m venv .venv 2>/dev/null || python -m venv .venv
        fi
    fi
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment .venv."
        echo ""
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
    echo "[INFO] Virtual environment created successfully."
fi

if [ -f "pyproject.toml" ]; then
    echo "[INFO] Syncing dependencies..."
    uv sync
    if [ $? -ne 0 ]; then
        echo "[ERROR] Dependency sync [uv sync] failed."
        echo "Please check your pyproject.toml configuration."
        echo ""
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
fi

# 5. Launch Application (adaptive for Streamlit / Python GUI)
echo ""
echo "[INFO] Launching $ENTRY_POINT ..."
echo ""

if grep -qi "streamlit" pyproject.toml 2>/dev/null; then
    uv run streamlit run "$ENTRY_POINT" --server.headless false
else
    uv run python "$ENTRY_POINT"
fi

if [ $? -ne 0 ]; then
    echo ""
    echo "[WARNING] Application stopped or encountered an error."
fi

echo ""
read -p "Press [Enter] key to exit..."
