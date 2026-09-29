"""Retrieval-augmented generation (RAG) knowledge base for the BUMBLEBLE assistant.

Put Markdown / text files in ``backend/knowledge/`` (or upload them from the
dashboard). They are split into heading-sized chunks and indexed two ways:

* BM25 keyword search - always available, no network, no API key;
* dense embeddings (Gemini ``gemini-embedding-001``) when GEMINI_API_KEY is set,
  cached on disk so each chunk is embedded only once.

``KnowledgeBase.search(query)`` returns the best chunks by a hybrid score; the
assistant passes them to the model and cites them as sources.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("nowcast.rag")

KB_DIR = Path(__file__).resolve().parents[1] / "knowledge"
EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")
_WORD = re.compile(r"[a-z0-9ऀ-ॿ]+")
_STOP = set("a an the and or of to in on at for is are was were be by with as it this that from what which how when "
            "do does can will i me my we our you your there their any about into near".split())


@dataclass
class Chunk:
    id: str
    doc: str
    title: str
    text: str


def _tokens(s: str) -> list[str]:
    return [w for w in _WORD.findall(s.lower()) if w not in _STOP and len(w) > 1]


def _chunk_markdown(doc: str, text: str, max_chars: int = 1200) -> list[Chunk]:
    """Split on headings, then pack paragraphs up to ``max_chars``."""
    out, title, buf = [], Path(doc).stem.replace("_", " "), []
    doc_title = title

    def flush():
        body = "\n".join(buf).strip()
        if body:
            for k in range(0, len(body), max_chars):
                part = body[k:k + max_chars]
                cid = hashlib.sha1(f"{doc}|{title}|{part}".encode()).hexdigest()[:16]
                out.append(Chunk(cid, doc, title, part))
        buf.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            title = m.group(2).strip() if len(m.group(1)) > 1 else m.group(2).strip()
            if len(m.group(1)) == 1:
                doc_title = title
            else:
                title = f"{doc_title} — {title}"
        else:
            buf.append(line)
    flush()
    return out


class KnowledgeBase:
    def __init__(self, folder: Path = KB_DIR, embedder=None):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder  # callable(list[str]) -> np.ndarray, or None
        self.chunks: list[Chunk] = []
        self._sig = None
        self._lock = threading.Lock()
        self._vec_cache_path = self.folder / ".embeddings.json"
        self._vec_cache: dict[str, list[float]] = {}
        if self._vec_cache_path.exists():
            try:
                self._vec_cache = json.loads(self._vec_cache_path.read_text())
            except Exception:
                self._vec_cache = {}

    # ------------------------------------------------------------ indexing
    def _signature(self):
        return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in self._files()))

    def _files(self):
        return [p for p in self.folder.iterdir() if p.suffix.lower() in (".md", ".txt") and not p.name.startswith(".")]

    def refresh(self) -> None:
        """Re-index if files were added or changed (cheap mtime check)."""
        sig = self._signature()
        if sig == self._sig:
            return
        with self._lock:
            chunks = []
            for p in sorted(self._files()):
                try:
                    chunks += _chunk_markdown(p.name, p.read_text(encoding="utf-8", errors="ignore"))
                except Exception as exc:
                    log.warning("cannot read %s: %s", p, exc)
            self.chunks = chunks
            toks = [_tokens(c.title + " " + c.text) for c in chunks]
            self._tf = [dict((w, t.count(w)) for w in set(t)) for t in toks]
            self._len = np.array([len(t) for t in toks], float)
            df: dict[str, int] = {}
            for t in self._tf:
                for w in t:
                    df[w] = df.get(w, 0) + 1
            n = max(len(chunks), 1)
            self._idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
            self._avg = float(self._len.mean()) if len(chunks) else 1.0
            self._vecs = None
            self._sig = sig
            log.info("knowledge base: %d chunks from %d files", len(chunks), len(self._files()))
        self._embed_missing()

    def _embed_missing(self) -> None:
        if self.embedder is None or not self.chunks:
            return
        missing = [c for c in self.chunks if c.id not in self._vec_cache]
        try:
            for k in range(0, len(missing), 50):
                batch = missing[k:k + 50]
                vecs = self.embedder([f"{c.title}\n{c.text}" for c in batch])
                for c, v in zip(batch, vecs):
                    self._vec_cache[c.id] = [round(float(x), 5) for x in v]
            if missing:
                keep = {c.id for c in self.chunks}
                self._vec_cache = {k: v for k, v in self._vec_cache.items() if k in keep}
                self._vec_cache_path.write_text(json.dumps(self._vec_cache))
            m = np.array([self._vec_cache[c.id] for c in self.chunks], np.float32)
            self._vecs = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        except Exception as exc:  # embeddings are an enhancement, never a requirement
            log.warning("embedding failed, using keyword search only: %s", exc)
            self._vecs = None

    # ------------------------------------------------------------ search
    def _bm25(self, q: list[str], k1: float = 1.4, b: float = 0.75) -> np.ndarray:
        s = np.zeros(len(self.chunks))
        for i, tf in enumerate(self._tf):
            for w in q:
                f = tf.get(w)
                if f:
                    s[i] += self._idf.get(w, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * self._len[i] / self._avg))
        return s

    def search(self, query: str, k: int = 4, min_score: float = 0.15) -> list[dict]:
        self.refresh()
        if not self.chunks:
            return []
        bm = self._bm25(_tokens(query))
        score = bm / bm.max() if bm.max() > 0 else bm
        if self._vecs is not None:
            try:
                qv = np.asarray(self.embedder([query])[0], np.float32)
                qv /= max(np.linalg.norm(qv), 1e-9)
                cos = self._vecs @ qv
                dense = np.clip((cos - 0.5) / 0.4, 0, 1)  # map typical cosine range to 0..1
                score = 0.45 * score + 0.55 * dense
            except Exception as exc:
                log.warning("query embedding failed: %s", exc)
        order = np.argsort(-score)[:k]
        return [{"doc": self.chunks[i].doc, "title": self.chunks[i].title, "text": self.chunks[i].text,
                 "score": round(float(score[i]), 3)} for i in order if score[i] >= min_score]

    def docs(self) -> list[dict]:
        self.refresh()
        counts: dict[str, int] = {}
        for c in self.chunks:
            counts[c.doc] = counts.get(c.doc, 0) + 1
        return [{"name": p.name, "chunks": counts.get(p.name, 0), "bytes": p.stat().st_size} for p in sorted(self._files())]

    def add_document(self, name: str, text: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem)[:60] or "document"
        path = self.folder / f"{safe}{'.md' if not name.lower().endswith('.txt') else '.txt'}"
        path.write_text(text, encoding="utf-8")
        self._sig = None
        self.refresh()
        return path.name

    def delete_document(self, name: str) -> bool:
        path = self.folder / Path(name).name
        if path.exists() and path.suffix.lower() in (".md", ".txt"):
            path.unlink()
            self._sig = None
            return True
        return False
