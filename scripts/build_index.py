#!/usr/bin/env python
"""
scripts/build_index.py
─────────────────────────────────────────────────────────────────────────────
(Re)build the RAG vector index from knowledge_base/corpus/**.

    python scripts/build_index.py            # build if corpus changed
    python scripts/build_index.py --force    # rebuild unconditionally

Reads OPENAI_API_KEY + config/llm_config.yaml. Honors VECTORSTORE_DIR and
RAG_BACKEND environment variables.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from skills.rag_retriever import RagRetriever  # noqa: E402


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    llm_config_path = _ROOT / "config" / "llm_config.yaml"
    llm_config = yaml.safe_load(llm_config_path.read_text()) if llm_config_path.exists() else {}

    retriever = RagRetriever(llm_config=llm_config)
    force = "--force" in sys.argv
    count = retriever.build_index(force=force)
    print(f"✅ RAG index ready: {count} chunks at {retriever.persist_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
