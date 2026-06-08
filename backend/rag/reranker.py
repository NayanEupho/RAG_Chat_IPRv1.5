"""
Cross-Encoder Reranking Engine (FlashRank)
-----------------------------------------
Provides a second-stage retrieval refinement using FlashRank.
Increases precision by re-scoring vector search candidates using a more powerful model.
"""

import logging
import torch
import asyncio
from typing import List, Dict, Any
from flashrank import Ranker, RerankRequest

logger = logging.getLogger(__name__)

class Reranker:
    """
    Singleton Reranker service.
    Offloads CPU-intensive ranking tasks to a thread pool to avoid blocking the API.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Reranker, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        from backend.config import get_config
        cfg = get_config()
        self.model_name = cfg.reranker_model
        self.min_score = cfg.retrieval_min_score
        self.model_path = None
        
        try:
            is_gpu = torch.cuda.is_available()
            logger.info(f"Initializing FlashRank Reranker ({self.model_name}). GPU Available: {is_gpu}")
            self.ranker = Ranker(model_name=self.model_name)
        except Exception as e:
            logger.error(f"Failed to init FlashRank: {e}")
            self.ranker = None
        self._initialized = True

    def _sync_rerank(self, query: str, pass_docs: List[Dict], top_k: int) -> List[Dict[str, Any]]:
        rerank_request = RerankRequest(query=query, passages=pass_docs)
        results = self.ranker.rerank(rerank_request)
        
        query_words = set(w for w in query.lower().split() if len(w) > 2)
        query_word_count = len(query_words) if query_words else 1
        
        scored = []
        for res in results:
            text_lower = res["text"].lower()
            keyword_matches = sum(1 for word in query_words if word in text_lower)
            density_boost = (keyword_matches / query_word_count) * 0.15
            coverage_ratio = (keyword_matches / max(len(text_lower.split()), 1)) * 5.0
            
            final_score = res["score"] + density_boost + coverage_ratio
            
            if final_score >= self.min_score:
                scored.append({
                    "page_content": res["text"],
                    "metadata": res["meta"],
                    "score": final_score
                })
        
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:top_k]

    async def rank(self, query: str, docs: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.ranker or not docs:
            return docs[:top_k]
        try:
            pass_docs = [
                {"id": str(i), "text": d.get("page_content") or d.get("content", "") or "", "meta": d.get("metadata", {})}
                for i, d in enumerate(docs)
            ]
            loop = asyncio.get_running_loop()
            sorted_docs = await loop.run_in_executor(
                None, self._sync_rerank, query, pass_docs, top_k
            )
            return sorted_docs
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return docs[:top_k]
