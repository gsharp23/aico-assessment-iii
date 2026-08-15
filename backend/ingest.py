"""
One-time ingest: text file -> chunks -> embeddings -> pgvector.

This is the "document loading, text splitting, embeddings, vector store" half of
the RAG pipeline. Run it once after the stack is up:

    docker compose exec api python ingest.py
"""

import logging
import os
import sys

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

import rag

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

CORPUS_PATH = os.environ.get("CORPUS_PATH", "corpus/el_paso_ordinances.txt")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))


def already_ingested(store) -> bool:
    """Cheap check so re-running the deploy workflow does not duplicate chunks."""
    try:
        return len(store.similarity_search("ordinance", k=1)) > 0
    except Exception:  # noqa: BLE001 - empty/missing collection means "not ingested"
        return False


def main() -> int:
    store = rag.get_vector_store()

    if already_ingested(store) and os.environ.get("FORCE_INGEST") != "1":
        log.info("collection %r already populated - skipping", rag.COLLECTION_NAME)
        return 0

    # 1. Load
    log.info("loading %s", CORPUS_PATH)
    docs = TextLoader(CORPUS_PATH, encoding="utf-8").load()

    # 2. Split - overlap keeps a rule from being cut in half between chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = i
    log.info("split into %d chunks", len(chunks))

    # 3. Embed + store. add_documents() embeds via Titan and writes the vectors.
    store.add_documents(chunks)
    log.info("ingest complete: %d chunks in collection %r", len(chunks), rag.COLLECTION_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
