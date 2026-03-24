import os
from pathlib import Path

_default_vault = Path.cwd()
VAULT_PATH = Path(os.environ.get("VAULT_PATH", str(_default_vault)))
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "vault_docs")
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
VECTOR_SIZE = 384
CHUNK_SIZE_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 50
SIMILARITY_THRESHOLD = 0.5
TOP_K = 5
