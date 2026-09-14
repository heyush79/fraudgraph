"""Similar-case retrieval over closed reports (LLD §6.2).

Chroma with its default embedding function, which is all-MiniLM-L6-v2 served through
onnxruntime. That is the model the design names, without pulling torch and two gigabytes of
wheels into the image.

Only closed cases go in. A case that is still open has no outcome to learn from, and
indexing it would let the agent cite its own earlier guess as precedent.
"""
from __future__ import annotations

import logging
from typing import Any

from .settings import Settings

log = logging.getLogger(__name__)


class SimilarCaseMemory:
    def __init__(self, settings: Settings) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection, metadata={"hnsw:space": "cosine"}
        )

    def index(self, case_id: str, summary: str, metadata: dict[str, Any]) -> None:
        """Upsert one closed case. Metadata values must be scalars for Chroma."""
        flat = {k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool)) and v is not None}
        self._collection.upsert(ids=[case_id], documents=[summary], metadatas=[flat or {"caseId": case_id}])

    def search(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        if self.count() == 0:
            return []
        res = self._collection.query(query_texts=[text], n_results=min(k, self.count()))
        out: list[dict[str, Any]] = []
        for i, doc in enumerate(res.get("documents", [[]])[0]):
            meta = (res.get("metadatas") or [[]])[0][i] or {}
            distance = (res.get("distances") or [[]])[0][i]
            out.append({
                "caseId": (res.get("ids") or [[]])[0][i],
                "summary": doc,
                "similarity": round(1.0 - float(distance), 3) if distance is not None else None,
                **{k2: v for k2, v in meta.items() if k2 != "caseId"},
            })
        return out

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception:  # noqa: BLE001
            return 0


class NullMemory:
    """Used when Chroma cannot start. find_similar_cases then reports an error, which the
    verify node treats as uncitable, rather than silently returning nothing."""

    def index(self, case_id: str, summary: str, metadata: dict[str, Any]) -> None:
        pass

    def search(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        raise RuntimeError("similar-case memory is unavailable")

    def count(self) -> int:
        return 0


def build_memory(settings: Settings):
    try:
        return SimilarCaseMemory(settings)
    except Exception as e:  # noqa: BLE001
        log.warning("Chroma unavailable, similar-case retrieval disabled: %s", e)
        return NullMemory()
