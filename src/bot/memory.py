"""
Long-Term Memory module utilizing ChromaDB and SentenceTransformers.
Handles persistent vector storage and semantic search for RAG integration.
"""
import os
import sys
import time
import asyncio
import chromadb
from sentence_transformers import SentenceTransformer


class LongTermMemory:
    def __init__(self, persist_directory="chroma_db"):
        # Path resolution for PyInstaller
        if getattr(sys, 'frozen', False):
            # The database needs to persist permanently next to the actual .exe
            persist_base_dir = os.path.dirname(sys.executable)
        else:
            persist_base_dir = os.getcwd()

        # 1. Setup Persistent DB
        self.persist_directory = os.path.join(persist_base_dir, persist_directory)
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(name="conversation_history")

        # 2. Load Offline Embedding Model (Strictly Local)
        model_path = os.path.join(persist_base_dir, "models", "all-MiniLM-L6-v2")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Embedding model not found at {model_path}. Please run 'python main.py download --embedding'.")

        # Explicitly pass the local path to prevent any network calls
        self.embedding_model = SentenceTransformer(model_path, device='cpu')

    def _add_interaction_sync(self, channel_id: int, user_name: str, user_msg: str, assistant_reply: str):
        """Synchronous backend for generating embeddings and storing in ChromaDB."""
        text = f"[{user_name}]: {user_msg}\n[Assistant]: {assistant_reply}"
        doc_id = f"{channel_id}_{time.time()}"

        embedding = self.embedding_model.encode(text).tolist()

        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"channel_id": channel_id, "user": user_name}]
        )

    async def add_interaction(self, channel_id: int, user_name: str, user_msg: str, assistant_reply: str):
        """Asynchronous wrapper to prevent blocking the Discord event loop."""
        await asyncio.to_thread(self._add_interaction_sync, channel_id, user_name, user_msg, assistant_reply)

    def _search_context_sync(self, channel_id: int, query: str, n_results: int = 3) -> str:
        """Synchronous backend for vector search."""
        if self.collection.count() == 0:
            return ""

        query_embedding = self.embedding_model.encode(query).tolist()

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"channel_id": channel_id}
        )

        if not results['documents'] or not results['documents'][0]:
            return ""

        return "\n".join(results['documents'][0])

    async def search_context(self, channel_id: int, query: str, n_results: int = 3) -> str:
        """Asynchronous wrapper for searching persistent memory."""
        return await asyncio.to_thread(self._search_context_sync, channel_id, query, n_results)

    def _clear_memory_sync(self, channel_id: int = None):
        if channel_id:
            self.collection.delete(where={"channel_id": channel_id})
        else:
            self.client.delete_collection("conversation_history")
            self.collection = self.client.get_or_create_collection(name="conversation_history")

    async def clear_memory(self, channel_id: int = None):
        """Asynchronous wrapper for clearing vector memory."""
        await asyncio.to_thread(self._clear_memory_sync, channel_id)
