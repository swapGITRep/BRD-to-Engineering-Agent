"""
skills/rag_retriever.py
─────────────────────────────────────────────────────────────────────────────
Capability 2 — Knowledge Augmentation (RAG).

Indexes knowledge_base/corpus/** and serves grounding context to every agent.

Backends (RAG_BACKEND env, default "memory"):
  - "memory" : embeddings + chunks persisted as JSON; cosine search with numpy.
               Zero external services. Fine for a corpus of dozens of docs.
  - "chroma" : chromadb PersistentClient (opt-in, for larger corpora).

`embed_fn` may be injected (tests) — a callable list[str] -> list[list[float]].
Otherwise skills.llm_factory.get_embeddings is used lazily.

Also exposes `load_persona(name)` for agent persona markdown.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT        = Path(__file__).parent.parent
CORPUS_DIR   = _ROOT / "knowledge_base" / "corpus"
PERSONA_DIR  = _ROOT / "knowledge_base" / "personas"

# corpus subfolder → doc_type tag
_DOC_TYPES = {
    "past_brds":     "past_brd",
    "templates":     "template",
    "patterns":      "pattern",
    "org_standards": "org_standard",
}

# Per-agent doc_type score multipliers (applied to cosine similarity).
AGENT_DOC_WEIGHTS: Dict[str, Dict[str, float]] = {
    "engineering_plan": {"template": 1.35, "past_brd": 1.25, "pattern": 1.05, "org_standard": 1.0},
    "schedule":         {"pattern": 1.35, "past_brd": 1.25, "template": 1.0, "org_standard": 0.95},
    "architecture":     {"pattern": 1.3, "org_standard": 1.25, "template": 1.05, "past_brd": 1.0},
    "poc_plan":         {"template": 1.25, "pattern": 1.15, "past_brd": 1.05, "org_standard": 1.0},
    "tech_stack":       {"org_standard": 1.4, "past_brd": 1.15, "pattern": 1.05, "template": 0.95},
    "critic":           {"template": 1.2, "org_standard": 1.15, "pattern": 1.0, "past_brd": 1.0},
}

Chunk = Dict[str, Any]   # {id, text, doc, doc_type, ord}


# ─────────────────────────────────────────────────────────────────────────────
# Persona loading
# ─────────────────────────────────────────────────────────────────────────────
def load_persona(name: str, persona_dir: Optional[Path] = None) -> str:
    """Return the persona markdown for an agent, or '' if absent."""
    path = (persona_dir or PERSONA_DIR) / f"{name}.md"
    if not path.exists():
        logger.warning("No persona file for '%s' (%s)", name, path)
        return ""
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Chunking (pure)
# ─────────────────────────────────────────────────────────────────────────────
def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_text(text: str, chunk_tokens: int, overlap_tokens: int) -> List[str]:
    """Greedy paragraph-packing chunker with character-approximated token budgets."""
    max_chars = chunk_tokens * 4
    overlap_chars = overlap_tokens * 4
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf.strip())
            tail = buf[-overlap_chars:] if overlap_chars else ""
            buf = (tail + "\n\n" + para).strip()
        else:
            buf = (buf + "\n\n" + para).strip() if buf else para
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def chunk_corpus(corpus_dir: Path, chunk_tokens: int = 800, overlap_tokens: int = 100) -> List[Chunk]:
    """Walk the corpus and return id-tagged chunks with doc_type metadata."""
    out: List[Chunk] = []
    for sub, doc_type in _DOC_TYPES.items():
        folder = corpus_dir / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            pieces = chunk_text(path.read_text(encoding="utf-8"), chunk_tokens, overlap_tokens)
            for i, piece in enumerate(pieces):
                out.append({
                    "id": f"{path.name}#{i}",
                    "text": piece,
                    "doc": path.name,
                    "doc_type": doc_type,
                    "ord": i,
                })
    return out


def corpus_hash(corpus_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(corpus_dir.rglob("*.md")):
        h.update(path.relative_to(corpus_dir).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Retriever
# ─────────────────────────────────────────────────────────────────────────────
class RagRetriever:
    def __init__(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        corpus_dir: Optional[Path] = None,
        persist_dir: Optional[Path] = None,
        backend: Optional[str] = None,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    ):
        self.llm_config = llm_config or {}
        self.corpus_dir = Path(corpus_dir) if corpus_dir else CORPUS_DIR
        self.persist_dir = Path(persist_dir or os.environ.get("VECTORSTORE_DIR", _ROOT / "vectorstore"))
        self.backend = backend or os.environ.get("RAG_BACKEND", "memory")
        self._embed_fn = embed_fn

        rag_cfg = self.llm_config.get("rag", {})
        self.chunk_tokens = rag_cfg.get("chunk_tokens", 800)
        self.overlap_tokens = rag_cfg.get("chunk_overlap", 100)
        self.default_k = rag_cfg.get("top_k", 6)

        self._chunks: List[Chunk] = []
        self._vectors = None   # numpy array once loaded

    # ── embeddings ───────────────────────────────────────────────────────
    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._embed_fn is not None:
            return self._embed_fn(texts)
        from skills.llm_factory import get_embeddings
        return get_embeddings(self.llm_config).embed_documents(texts)

    # ── build ────────────────────────────────────────────────────────────
    def build_index(self, force: bool = False) -> int:
        """(Re)build the index. Returns the chunk count. Idempotent on corpus hash."""
        chash = corpus_hash(self.corpus_dir)
        manifest_path = self.persist_dir / "manifest.json"
        if not force and manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text())
                if existing.get("corpus_hash") == chash:
                    logger.info("RAG index up to date (%s chunks)", existing.get("chunk_count"))
                    return int(existing.get("chunk_count", 0))
            except Exception:  # noqa: BLE001
                pass

        chunks = chunk_corpus(self.corpus_dir, self.chunk_tokens, self.overlap_tokens)
        if not chunks:
            raise RuntimeError(f"No corpus documents found under {self.corpus_dir}")
        vectors = self._embed([c["text"] for c in chunks])

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        if self.backend == "chroma":
            self._write_chroma(chunks, vectors)
        else:
            (self.persist_dir / "index.json").write_text(
                json.dumps({"chunks": chunks, "vectors": vectors}), encoding="utf-8"
            )

        manifest_path.write_text(json.dumps({
            "corpus_hash": chash,
            "chunk_count": len(chunks),
            "backend": self.backend,
            "dim": len(vectors[0]) if vectors else 0,
        }, indent=2), encoding="utf-8")
        logger.info("Built RAG index: %d chunks (%s backend)", len(chunks), self.backend)
        return len(chunks)

    def _write_chroma(self, chunks: List[Chunk], vectors: List[List[float]]) -> None:  # pragma: no cover
        import chromadb
        client = chromadb.PersistentClient(path=str(self.persist_dir / "chroma"))
        try:
            client.delete_collection("corpus")
        except Exception:  # noqa: BLE001
            pass
        col = client.create_collection("corpus")
        col.add(
            ids=[c["id"] for c in chunks],
            embeddings=vectors,
            documents=[c["text"] for c in chunks],
            metadatas=[{"doc": c["doc"], "doc_type": c["doc_type"], "ord": c["ord"]} for c in chunks],
        )

    # ── load ─────────────────────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        if self._chunks:
            return
        import numpy as np
        if self.backend == "chroma":  # pragma: no cover
            import chromadb
            client = chromadb.PersistentClient(path=str(self.persist_dir / "chroma"))
            col = client.get_collection("corpus")
            got = col.get(include=["embeddings", "documents", "metadatas"])
            self._chunks = [
                {"id": i, "text": d, "doc": m["doc"], "doc_type": m["doc_type"], "ord": m["ord"]}
                for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])
            ]
            self._vectors = np.array(got["embeddings"], dtype="float32")
            return
        index_path = self.persist_dir / "index.json"
        if not index_path.exists():
            raise RuntimeError(f"RAG index not built. Run scripts/build_index.py ({index_path} missing).")
        data = json.loads(index_path.read_text())
        self._chunks = data["chunks"]
        self._vectors = np.array(data["vectors"], dtype="float32")

    # ── retrieve ─────────────────────────────────────────────────────────
    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        doc_type: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Chunk]:
        import numpy as np
        self._ensure_loaded()
        k = k or self.default_k

        qv = np.array(self._embed([query])[0], dtype="float32")
        mat = self._vectors
        sims = mat @ qv / (
            (np.linalg.norm(mat, axis=1) * np.linalg.norm(qv)) + 1e-9
        )

        scored = []
        for chunk, sim in zip(self._chunks, sims):
            if doc_type and chunk["doc_type"] != doc_type:
                continue
            mult = (weights or {}).get(chunk["doc_type"], 1.0)
            scored.append((float(sim) * mult, chunk))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [dict(c, score=round(s, 4)) for s, c in scored[:k]]

    def retrieve_for_agent(
        self,
        agent_name: str,
        brd_summary: str,
        requirements: Optional[List[Dict[str, Any]]] = None,
        k: Optional[int] = None,
    ) -> str:
        """Compose an agent-specific query, retrieve with doc_type weighting, format."""
        req_text = ""
        if requirements:
            req_text = " ".join(r.get("text", "") for r in requirements[:40])
        query = f"{agent_name.replace('_', ' ')} guidance for: {brd_summary}\n{req_text}".strip()
        weights = AGENT_DOC_WEIGHTS.get(agent_name, {})
        chunks = self.retrieve(query, k=k, weights=weights)
        return self.format_context(chunks)

    @staticmethod
    def format_context(chunks: List[Chunk]) -> str:
        if not chunks:
            return "(no knowledge-base context retrieved)"
        blocks = [f"[KB:{c['doc']}#{c['ord']}]\n{c['text']}" for c in chunks]
        return "\n\n".join(blocks)

    def resolve_citations(self, refs: List[str]) -> Dict[str, str]:
        """Map citation refs ('KB:doc.md#3' or '[KB:doc.md#3]') → chunk text ('' if unknown)."""
        self._ensure_loaded()
        index = {f"{c['doc']}#{c['ord']}": c["text"] for c in self._chunks}
        out: Dict[str, str] = {}
        for ref in refs:
            key = ref.strip().lstrip("[").rstrip("]")
            if key.startswith("KB:"):
                key = key[3:]
            out[ref] = index.get(key, "")
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Process-wide singleton (agents share one loaded index)
# ─────────────────────────────────────────────────────────────────────────────
_SINGLETON: Optional[RagRetriever] = None


def get_retriever(llm_config: Optional[Dict[str, Any]] = None) -> RagRetriever:
    """Return the shared RagRetriever, building the index on first use."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = RagRetriever(llm_config=llm_config or {})
        _SINGLETON.build_index()
    return _SINGLETON


def reset_retriever() -> None:
    """Test hook — drop the singleton."""
    global _SINGLETON
    _SINGLETON = None
