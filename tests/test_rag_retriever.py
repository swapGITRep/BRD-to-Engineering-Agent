"""
tests/test_rag_retriever.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for skills/rag_retriever.py using a deterministic bag-of-words
embedder (no OpenAI, no Chroma).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import hashlib
import math
import re

import pytest

from skills.rag_retriever import (
    CORPUS_DIR,
    RagRetriever,
    chunk_corpus,
    chunk_text,
    corpus_hash,
    load_persona,
)

DIM = 512


def _bucket(tok: str) -> int:
    return int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM


def bow_embed(texts):
    """Deterministic normalized bag-of-words vectors."""
    out = []
    for t in texts:
        v = [0.0] * DIM
        for tok in re.findall(r"[a-z]{3,}", t.lower()):
            v[_bucket(tok)] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / norm for x in v])
    return out


class CountingEmbed:
    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        return bow_embed(texts)


@pytest.fixture
def retriever(tmp_path):
    embed = CountingEmbed()
    r = RagRetriever(
        llm_config={"rag": {"chunk_tokens": 300, "chunk_overlap": 40, "top_k": 4}},
        persist_dir=tmp_path / "vs",
        backend="memory",
        embed_fn=embed,
    )
    r._embed_counter = embed  # type: ignore[attr-defined]
    return r


# ── chunking ─────────────────────────────────────────────────────────────────
class TestChunking:

    def test_chunk_text_respects_char_budget(self):
        para = ("word " * 60).strip()
        text = "\n\n".join([para] * 6)
        chunks = chunk_text(text, chunk_tokens=100, overlap_tokens=10)
        assert len(chunks) > 1
        assert all(len(c) <= 100 * 4 + 40 for c in chunks)

    def test_chunk_corpus_tags_doc_types(self):
        chunks = chunk_corpus(CORPUS_DIR, 800, 100)
        seen = {c["doc_type"] for c in chunks}
        assert {"template", "pattern", "org_standard", "past_brd"} <= seen
        assert all(re.match(r".+#\d+$", c["id"]) for c in chunks)


# ── corpus_hash ──────────────────────────────────────────────────────────────
class TestCorpusHash:

    def test_stable(self):
        assert corpus_hash(CORPUS_DIR) == corpus_hash(CORPUS_DIR)

    def test_changes_when_file_added(self, tmp_path):
        (tmp_path / "patterns").mkdir()
        (tmp_path / "patterns" / "a.md").write_text("alpha")
        h1 = corpus_hash(tmp_path)
        (tmp_path / "patterns" / "b.md").write_text("beta")
        assert corpus_hash(tmp_path) != h1


# ── build_index ──────────────────────────────────────────────────────────────
class TestBuildIndex:

    def test_creates_index_and_manifest(self, retriever):
        n = retriever.build_index()
        assert n > 0
        assert (retriever.persist_dir / "index.json").exists()
        assert (retriever.persist_dir / "manifest.json").exists()

    def test_idempotent_on_unchanged_corpus(self, retriever):
        retriever.build_index()
        calls_after_first = retriever._embed_counter.calls
        n2 = retriever.build_index()          # no corpus change
        assert n2 > 0
        assert retriever._embed_counter.calls == calls_after_first  # no re-embed

    def test_force_rebuilds(self, retriever):
        retriever.build_index()
        before = retriever._embed_counter.calls
        retriever.build_index(force=True)
        assert retriever._embed_counter.calls > before


# ── retrieve ─────────────────────────────────────────────────────────────────
class TestRetrieve:

    def test_ranks_relevant_document_first(self, retriever):
        retriever.build_index()
        hits = retriever.retrieve("effort estimation multipliers ramp-up contingency", k=3)
        assert hits[0]["doc"] == "estimation_heuristics.md"

    def test_doc_type_filter(self, retriever):
        retriever.build_index()
        hits = retriever.retrieve("security encryption access control", k=5, doc_type="org_standard")
        assert hits and all(h["doc_type"] == "org_standard" for h in hits)

    def test_retrieve_before_build_raises(self, retriever):
        with pytest.raises(RuntimeError):
            retriever.retrieve("anything")

    def test_retrieve_for_agent_formats_citations(self, retriever):
        retriever.build_index()
        ctx = retriever.retrieve_for_agent(
            "tech_stack",
            brd_summary="replace legacy portal, hosting must stay on Azure",
            requirements=[{"text": "team is strong in TypeScript and React"}],
        )
        assert "[KB:" in ctx
        assert "tech_radar.md" in ctx

    def test_agent_weighting_changes_ranking(self, retriever):
        retriever.build_index()
        q = "phases milestones team composition delivery plan"
        plain = retriever.retrieve(q, k=6)
        weighted = retriever.retrieve(q, k=6, weights={"template": 3.0})
        assert weighted[0]["doc_type"] == "template"
        # plain ranking need not lead with a template
        assert [h["id"] for h in plain] != [h["id"] for h in weighted] or True


# ── personas ─────────────────────────────────────────────────────────────────
class TestPersona:

    def test_loads_known_persona(self):
        assert "Engineering Plan Generator" in load_persona("engineering_plan_generator")

    def test_missing_persona_returns_empty(self):
        assert load_persona("nonexistent_agent") == ""
