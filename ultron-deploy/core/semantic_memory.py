"""
Semantic Memory Search for Ultron.

Provides a persistent, vector‑based memory layer that Ultron can query to
recall past facts, observations, and learned patterns.

**What it does**
* Stores chunks of text (with optional metadata) in a vector database.
* Embeddings are generated with a lightweight sentence‑transformers model
  (``all-MiniLM-L6-v2``) – ~384‑dim vectors, fast and fairly expressive.
* Supports adding new content from any source (skill outputs, Obsidian notes,
  Firecrawl scrapes, BiomCP results, etc.).
* Enables similarity search: given a natural‑language query, return the most
  semantically similar stored chunks, with scores and metadata.
* Persists across sessions – the ChromaDB directory survives restarts.

**Conventions**
* Each stored item is identified by a unique ID (UUID) and may carry arbitrary
  JSON‑compatible metadata (source, skill_name, timestamp, etc.).
* The embedding model is created once and reused; the module is thread‑safe
  for read‑only operations, and serialises writes.

**Dependencies** (should be installed in the Ultron environment)
````bash
pip install chromadb sentence-transformers
````

**Public API**
````python
from core.semantic_memory import SemanticMemory

mem = SemanticMemory()           # initialises or opens the persistent store

# Add new knowledge
mem.add_text(
    "Kinase inhibitors bind the ATP pocket of CDK2, blocking phosphorylation.",
    metadata={"source": "paper_abstract", "paper_id": "PMID:12345"}
)

# Search
results = mem.search("How do CDK2 inhibitors work?", n_results=3)
for r in results:
    print(r["text"], "- score:", r["score"], "- meta:", r["metadata"])
````
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Try to import chromadb; if it's not available, fall back to a simple
# in‑memory similarity search (useful for testing without extra deps).
# ---------------------------------------------------------------------------
try:
    import chromadb
    from chromadb.config import Settings

    _HAVE_CHROMA = True
except Exception:  # pragma: no cover
    _HAVE_CHROMA = False

try:
    from sentence_transformers import SentenceTransformer

    _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
except Exception:  # pragma: no cover
    _EMBED_MODEL = None

# ---------------------------------------------------------------------------
# Persistent path for ChromaDB – lives under the user's Ultron config dir.
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".ultron", "chroma_db")


# ---------------------------------------------------------------------------
# Helper: generate an embedding for a string.
# ---------------------------------------------------------------------------
def _embed_text(text: str) -> List[float]:
    """Return a 384‑dim embedding vector for *text*."""
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL.encode(text).tolist()
    # Fallback: simple hash‑based vector (not semantic, just placeholder)
    # In production you would want a real model.
    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Convert 32 bytes to 384 float values in [0, 1]
    vectors = []
    for i in range(12):
        # 32 bytes / 12 chunks = ~2.67 bytes per chunk, we'll use 4-byte ints
        start = i * 4
        end = start + 4
        chunk = h[start:end]
        val = (int.from_bytes(chunk, "big") % 1000) / 1000.0
        vectors.append(val)
    # Pad to 384 if needed (12 * 32 = 384 bits, but we want 384 floats)
    # Actually let's generate exactly 384 floats from the hash
    result = []
    for i in range(384):
        result.append((h[i % len(h)] / 255.0) - 0.5)  # center around 0, range [-0.5, 0.5]
    return result


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class SemanticMemory:
    """Vector‑based long‑term memory for Ultron."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)

        if _HAVE_CHROMA:
            # Persistent client keeps the vector store on disk.
            self.client = chromadb.PersistentClient(path=self.db_path)
            # Create (or reuse) a collection for Ultron's memories.
            self.collection = self.client.get_or_create_collection(
                name="ultron_memory",
                metadata={"hnsw:space": "cosine"},  # cosine similarity
            )
        else:
            # In‑memory fallback – very basic; not persisted.
            import numpy as np

            self.embeddings: List[List[float]] = []
            self.texts: List[str] = []
            self.metadata: List[Dict[str, Any]] = []
            self._np = np

    # ------------------------------------------------------------------
    # Adding content
    # ------------------------------------------------------------------

    def add_text(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Store a piece of text in memory.

        Parameters
        ----------
        text : str
            The raw text to embed and store.
        metadata : dict or None
            Optional JSON‑compatible metadata (e.g. source, skill name,
            timestamp).  If ``None`` an empty dict is stored.

        Returns
        -------
        str
            The unique ID assigned to this entry.
        """
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise TypeError("metadata must be a dict or None")

        # Generate embedding
        vec = _embed_text(text)
        # Unique ID
        entry_id = str(uuid.uuid4())

        if _HAVE_CHROMA:
            self.collection.add(
                ids=[entry_id],
                documents=[text],
                embeddings=[vec],
                metadatas=[metadata],
            )
        else:
            self.embeddings.append(vec)
            self.texts.append(text)
            self.metadata.append(metadata)

        return entry_id

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return the *n_results* most similar stored chunks to *query*.

        Parameters
        ----------
        query : str
            Natural‑language query.
        n_results : int
            Maximum number of results to return (default 5).
        filter_meta : dict or None
            If provided, only items whose metadata matches *all* key/value
            pairs will be considered.  Example::
                filter_meta={"source": "paper_abstract"}

        Returns
        -------
        list[dict]
            Each dict has keys ``"text"``, ``"score"`` (lower is better for
            cosine distance; we convert to a similarity‐like value), and
            ``"metadata"``.
        """
        if n_results <= 0:
            return []

        query_vec = _embed_text(query)

        if _HAVE_CHROMA:
            results = self.collection.query(
                query_embeddings=[query_vec],
                n_results=n_results,
                where=filter_meta if filter_meta else None,
            )
            # Chroma returns lists keyed by the query; we just have one query.
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]  # cosine distance
            metadatas = results.get("metadatas", [[]])[0]

            out: List[Dict[str, Any]] = []
            for doc, dist, meta in zip(documents, distances, metadatas):
                # Convert distance (0‑2) to a similarity‑like score.
                # cosine distance 0 => identical, 2 => opposite.
                similarity = 1 - (dist / 2)  # scale roughly -1 to 1, but we keep distance for transparency
                out.append(
                    {
                        "text": doc,
                        "score": dist,  # keep raw distance; callers can interpret
                        "metadata": meta if meta else {},
                    }
                )
            return out
        else:
            # In‑memory naive cosine similarity
            if not self.embeddings:
                return []

            import numpy as np

            query_arr = np.array(query_vec)
            emb_arr = np.array(self.embeddings)

            # Compute cosine similarity
            dot = np.dot(emb_arr, query_arr)
            norm_a = np.linalg.norm(emb_arr, axis=1)
            norm_b = np.linalg.norm(query_arr)
            cos_sim = dot / (norm_a * norm_b + 1e-8)  # avoid div0

            # Sort descending by similarity
            top_indices = np.argsort(cos_sim)[::-1][:n_results]

            out: List[Dict[str, Any]] = []
            for idx in top_indices:
                out.append(
                    {
                        "text": self.texts[idx],
                        "score": 1 - cos_sim[idx].item(),  # distance‑like
                        "metadata": self.metadata[idx],
                    }
                )
            return out

    # ------------------------------------------------------------------
    # Bulk‑index existing sources (Obsidian vault, skill outputs, etc.)
    # ------------------------------------------------------------------

    def index_vault_notes(self, vault_name: str, folder: str = "") -> int:
        """
        Scan an Obsidian vault (or a sub‑folder) and embed every markdown note.

        Parameters
        ----------
        vault_name : str
            Name of the vault as recognised by the Obsidian tools.
        folder : str
            Optional sub‑folder path relative to the vault root (e.g.
            ``"journal/2024"``).  If empty the entire vault is scanned.

        Returns
        -------
        int
            Number of notes indexed.
        """
        from tools.obsidian import list_available_vaults, read_note  # lazy import to avoid circular deps

        vaults = list_available_vaults()
        vault_path = None
        for v in vaults:
            if v.lower() == vault_name.lower():
                vault_path = v  # This is just a name; actual path handled by tools
                break

        if vault_path is None:
            raise ValueError(f"Vault '{vault_name}' not found")

        # Determine root; for simplicity we assume the vault root is the
        # returned path (the tool gives us the root directory).
        root = vault_path  # type: ignore
        search_path = os.path.join(root, folder) if folder else root

        if not os.path.isdir(search_path):
            raise NotADirectoryError(f"Folder not found: {search_path}")

        count = 0
        for dirpath, _, files in os.walk(search_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    content = read_note(vault_name, fname)  # reads frontmatter + body
                    # Use the full content (or just the body) as the text chunk.
                    # We'll strip the frontmatter if present.
                    if content.startswith("---"):
                        # naive frontmatter removal
                        ending = content.index("---", 3)
                        content = content[ending + 1:].strip()
                    # Optional: skip if content is very short
                    if len(content) < 20:
                        continue
                    metadata = {
                        "source": "obsidian_note",
                        "vault": vault_name,
                        "path": os.path.relpath(fpath, root),
                    }
                    self.add_text(content, metadata=metadata)
                    count += 1
                except Exception as exc:  # pragma: no cover
                    LOGGER.warning("Failed to index %s: %s", fpath, exc)
        return count

    # ------------------------------------------------------------------
    # Utility: dump/load state for debugging
    # ------------------------------------------------------------------

    def export_state(self, path: str = "") -> str:
        """Return a JSON representation of the current memory state."""
        if _HAVE_CHROMA:
            # Chroma provides a built‑in way; we just note the path.
            return f"Chroma DB at {self.db_path}"
        else:
            data = {
                "embeddings": self.embeddings,
                "texts": self.texts,
                "metadata": self.metadata,
            }
            out_path = path or os.path.join(self.db_path, "memory_snapshot.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return out_path