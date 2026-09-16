#!/usr/bin/env bash
# ============================================================
# run.sh — Quick start for IK BRD Dev Agent
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "📋 IK BRD Dev Agent"
echo "════════════════════════════════════════"

# ── Locate Python 3.12 ───────────────────────────────────────
# This project targets Python 3.12 (deps have reliable wheels there).
# Override with:  PYTHON=/path/to/python3.12 ./run.sh
REQUIRED_MAJOR=3
REQUIRED_MINOR=12

find_python() {
    if [ -n "$PYTHON" ] && command -v "$PYTHON" &>/dev/null; then
        echo "$PYTHON"; return
    fi
    for cand in python3.12 python3 python; do
        if command -v "$cand" &>/dev/null; then
            local v
            v=$("$cand" -c 'import sys; print("%d %d" % sys.version_info[:2])' 2>/dev/null) || continue
            # accept exactly 3.12
            if [ "$v" = "$REQUIRED_MAJOR $REQUIRED_MINOR" ]; then
                echo "$cand"; return
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} not found."
    echo "   Install it:   brew install python@3.12"
    echo "   Or point at an existing one:   PYTHON=/path/to/python3.12 ./run.sh"
    exit 1
fi
echo "✅ Using $("$PYTHON_BIN" --version) ($PYTHON_BIN)"

# ── Virtual environment ───────────────────────────────────────
# Recreate the venv if it was built with a different Python version.
VENV_PY="venv/bin/python"
if [ -d "venv" ] && [ -x "$VENV_PY" ]; then
    VENV_VER=$("$VENV_PY" -c 'import sys; print("%d %d" % sys.version_info[:2])' 2>/dev/null || echo "")
    if [ "$VENV_VER" != "$REQUIRED_MAJOR $REQUIRED_MINOR" ]; then
        echo "🔧 Existing venv is Python ${VENV_VER// /.}; rebuilding on ${REQUIRED_MAJOR}.${REQUIRED_MINOR}..."
        rm -rf venv
    fi
fi

if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment (Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR})..."
    "$PYTHON_BIN" -m venv venv
fi

echo "🔧 Activating virtual environment..."
source venv/bin/activate

# ── Set PYTHONPATH so all imports resolve from project root ──
export PYTHONPATH="$PROJECT_DIR"

# ── Install dependencies ──────────────────────────────────────
echo "📦 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Real title/description/OG tags in Streamlit's static HTML (st.set_page_config
# only sets these client-side) — same patch the Docker image applies at build time.
python scripts/patch_streamlit_index.py

# ── Environment check ─────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
fi

# Load .env
set -a; source .env; set +a

# Validate OPENAI_API_KEY
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-your-openai-key-here" ]; then
    echo ""
    echo "❌ OPENAI_API_KEY is not set."
    echo "   Edit .env and add your key:"
    echo "   OPENAI_API_KEY=sk-..."
    echo ""
    exit 1
fi
echo "✅ OPENAI_API_KEY detected"

# ── Create output dirs ────────────────────────────────────────
mkdir -p output/parsed output/deliverables output/reports

# ── Build RAG index if missing ───────────────────────────────
if [ ! -f "${VECTORSTORE_DIR:-./vectorstore}/manifest.json" ] && [ -f scripts/build_index.py ]; then
    echo "🔧 Building RAG index..."
    PYTHONPATH="$PROJECT_DIR" python scripts/build_index.py
fi

# ── Mode selection ────────────────────────────────────────────
MODE="${1:-ui}"

if [ "$MODE" = "ui" ]; then
    echo ""
    echo "🚀 Launching Streamlit UI..."
    echo "   URL: http://localhost:8501"
    echo "════════════════════════════════════════"
    echo ""
    PYTHONPATH="$PROJECT_DIR" streamlit run "$PROJECT_DIR/streamlit_app/app.py"

elif [ "$MODE" = "cli" ]; then
    BRD_FILE="${2:-data/sample_brds/payments_reconciliation_brd.md}"
    THREAD_ID="${3:-}"
    echo ""
    echo "🤖 Running BRD pipeline for: $BRD_FILE"
    [ -n "$THREAD_ID" ] && echo "   Resuming thread: $THREAD_ID"
    echo "════════════════════════════════════════"
    PYTHONPATH="$PROJECT_DIR" python -m orchestration.langgraph_workflow "$BRD_FILE" "$THREAD_ID"

elif [ "$MODE" = "test" ]; then
    echo ""
    echo "🧪 Running unit tests..."
    echo "════════════════════════════════════════"
    pytest tests/ -v --tb=short

else
    echo "Usage:"
    echo "  ./run.sh                 — Launch Streamlit UI (default)"
    echo "  ./run.sh ui              — Launch Streamlit UI"
    echo "  ./run.sh cli [brd_file]  — Run the BRD pipeline from CLI"
    echo "  ./run.sh test            — Run unit tests"
fi
