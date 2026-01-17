import logging
import torch
import asyncio
from typing import List, Dict, Any
from flashrank import Ranker, RerankRequest

logger = logging.getLogger(__name__)

class Reranker:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Reranker, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.model_name = "ms-marco-TinyBERT-L-2-v2"  # Ultra-fast, decent accuracy
        self.model_path = None  # Downloads auto
        
        # NOTE: FlashRank internally handles ONNX Runtime providers.
        try:
            is_gpu = torch.cuda.is_available()
            logger.info(f"Initializing FlashRank Reranker. GPU Available: {is_gpu}")
            self.ranker = Ranker(model_name=self.model_name)
        except Exception as e:
            logger.error(f"Failed to init FlashRank: {e}")
            self.ranker = None

        self._initialized = True

    def _sync_rerank(self, query: str, pass_docs: List[Dict], top_k: int) -> List[Dict[str, Any]]:
        """
        Synchronous reranking logic - called from executor to avoid blocking event loop.
        """
        rerank_request = RerankRequest(query=query, passages=pass_docs)
        results = self.ranker.rerank(rerank_request)
        
        sorted_docs = []
        query_words = set(query.lower().split())

        for res in results[:top_k]:
            # HYBRID BOOST: Add a small boost for exact keyword matches
            text_lower = res["text"].lower()
            keyword_matches = sum(1 for word in query_words if word in text_lower)
            density_boost = (keyword_matches / len(query_words)) * 0.1 if query_words else 0
            
            final_score = res["score"] + density_boost

            sorted_docs.append({
               "page_content": res["text"],
               "metadata": res["meta"],
               "score": final_score
            })
        
        # Re-sort by final hybrid score
        sorted_docs.sort(key=lambda x: x['score'], reverse=True)
        return sorted_docs

    async def rank(self, query: str, docs: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Async reranker that offloads CPU-bound work to ThreadPoolExecutor.
        This prevents blocking the event loop during reranking operations.
        
        docs expected format: [{'page_content': 'text...', 'metadata': {...}}, ...]
        """
        if not self.ranker or not docs:
            return docs[:top_k]

        try:
            # FlashRank expects a specific format
            pass_docs = [
                {"id": str(i), "text": d.get("page_content") or d.get("content", "") or "", "meta": d.get("metadata", {})}
                for i, d in enumerate(docs)
            ]

            # Offload CPU-bound reranking to ThreadPoolExecutor
            loop = asyncio.get_running_loop()
            sorted_docs = await loop.run_in_executor(
                None,  # Uses default ThreadPoolExecutor
                self._sync_rerank,
                query,
                pass_docs,
                top_k
            )
            
            return sorted_docs
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return docs[:top_k]  # Fallback to original order
