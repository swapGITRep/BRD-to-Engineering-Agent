#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Container entrypoint: build the RAG index on first boot (persisted on the
# mounted Azure Files share), then launch Streamlit.
# ─────────────────────────────────────────────────────────────────────────────
set -e

VECTORSTORE_DIR="${VECTORSTORE_DIR:-/app/vectorstore}"
CHECKPOINT_DB="${CHECKPOINT_DB:-/app/checkpoints/langgraph_states.db}"
PORT="${PORT:-8501}"

mkdir -p "$VECTORSTORE_DIR" "$(dirname "$CHECKPOINT_DB")" /app/output

if [ ! -f "$VECTORSTORE_DIR/manifest.json" ]; then
  echo "[entrypoint] Building RAG index into $VECTORSTORE_DIR ..."
  if ! python scripts/build_index.py; then
    echo "[entrypoint] WARNING: RAG index build failed (check OPENAI_API_KEY). Continuing; agents will fall back to un-grounded prompts."
  fi
else
  echo "[entrypoint] RAG index present — skipping build."
fi

exec streamlit run streamlit_app/app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --browser.gatherUsageStats false
