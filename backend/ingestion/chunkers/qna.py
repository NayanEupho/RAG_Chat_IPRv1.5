import os
from typing import Any, Dict, List

from backend.ingestion.chunkers.general import stable_doc_id
from backend.ingestion.qna_patterns import extract_qa_pairs


class QnAChunker:
    def __init__(self, max_chunk_size: int = 2000):
        self.max_chunk_size = max_chunk_size

    def chunk(self, markdown: str, file_path: str) -> List[Dict[str, Any]]:
        filename = os.path.basename(file_path)
        doc_id = stable_doc_id(file_path)
        pairs = extract_qa_pairs(markdown, filename)
        pairs.sort(key=lambda x: x.get("pair_index", 0))
        chunks: List[Dict[str, Any]] = []

        for pair in pairs:
            question = pair["question_text"].strip()
            answer = pair["answer_text"].strip()
            section = pair["section_path"]
            qa_id = pair["qa_pair_id"]
            full = f"Q: {question}\n\nA: {answer}"
            fragments = [answer]
            if len(full) > self.max_chunk_size:
                fragments = self._split_answer(answer, self.max_chunk_size - len(question) - 20)

            for frag_idx, fragment in enumerate(fragments):
                total = len(fragments)
                content = f"Q: {question}\n\nA: {fragment}" if frag_idx == 0 else f"Q: {question}\n\nA continued: {fragment}"
                text = f"[Doc: {filename} | Section: {section} | Q&A: {qa_id} | Part {frag_idx + 1}/{total}]\n{content}"
                chunks.append({
                    "text": text,
                    "metadata": {
                        "source": file_path,
                        "doc_id": doc_id,
                        "filename": filename,
                        "doc_type": "qna",
                        "chunk_index": len(chunks),
                        "section_path": section,
                        "qa_pair_id": qa_id,
                        "question_text": question[:200],
                        "is_atomic": total == 1,
                        "is_fragment": total > 1,
                        "fragment_index": frag_idx,
                        "total_fragments": total,
                        "chunk_kind": "qna" if total == 1 else "qna_fragment",
                        "has_table": "|" in answer,
                    }
                })
        return chunks

    def _split_answer(self, answer: str, max_size: int) -> List[str]:
        lines = answer.splitlines()
        fragments = []
        current = []
        current_len = 0
        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_size:
                fragments.append("\n".join(current).strip())
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len
        if current:
            fragments.append("\n".join(current).strip())
        return fragments or [answer]
