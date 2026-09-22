# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# BRD Dev Agent — container image (Streamlit UI + LangGraph pipeline)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8501 \
    VECTORSTORE_DIR=/app/vectorstore \
    CHECKPOINT_DB=/app/checkpoints/langgraph_states.db

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Patch Streamlit's static index.html with real title/description/OG tags —
# st.set_page_config() only sets these client-side, invisible to link-preview
# bots that fetch the raw HTML without running JS. See the script for why.
RUN python scripts/patch_streamlit_index.py

RUN chmod +x scripts/entrypoint.sh \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/vectorstore /app/checkpoints /app/output \
    && chown -R app:app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/_stcore/health" || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
