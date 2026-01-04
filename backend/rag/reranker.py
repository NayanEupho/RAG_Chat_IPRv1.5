import logging
import torch
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
        
        self.model_name = "ms-marco-TinyBERT-L-2-v2" # Ultra-fast, decent accuracy
        self.model_path = None # Downloads auto
        
        # NOTE: FlashRank internally handles ONNX Runtime providers.
        # We don't strictly need to check torch.cuda.is_available() for FlashRank's init 
        # but we can log what environment we are in.
        try:
            is_gpu = torch.cuda.is_available()
            logger.info(f"Initializing FlashRank Reranker. GPU Available: {is_gpu}")
            self.ranker = Ranker(model_name=self.model_name)
        except Exception as e:
            logger.error(f"Failed to init FlashRank: {e}")
            self.ranker = None

        self._initialized = True

    def rank(self, query: str, docs: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Reranks a list of documents based on the query.
        docs expected format: [{'content': 'text...', 'meta': {...}}, ...]
        """
        if not self.ranker or not docs:
            return docs[:top_k]

        try:
            # FlashRank expects a specific format
            pass_docs = [
                {"id": str(i), "text": d.get("page_content") or d.get("content", "") or "", "meta": d.get("metadata", {})}
                for i, d in enumerate(docs)
            ]

            rerank_request = RerankRequest(query=query, passages=pass_docs)
            results = self.ranker.rerank(rerank_request)
            
            # Map back to original format, sorted by score
            # results is list of dicts with 'id', 'score', 'text', 'meta'
            
            sorted_docs = []
            query_words = set(query.lower().split())

            for res in results[:top_k]:
                # HYBRID BOOST: Add a small boost for exact keyword matches
                # to ensure "Technical Report" chunks rank higher for "what is this report about"
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
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return docs[:top_k] # Fallback to original order
