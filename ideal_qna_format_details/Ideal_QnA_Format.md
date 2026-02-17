# The Gold Standard: Ideal Q&A Format for RAG

To achieve the highest possible accuracy and the lowest latency, your Q&A documents should follow a specific structural "DNA." This guide outlines the best practices for creating Q&A files that our ingestion engine and LLM can process perfectly.

## 1. Trigger Markers (Deterministic Extraction)

Our system uses high-precision regex to "slice" your document. Using these specific labels ensures that every Question and Answer is extracted as a unique, searchable unit.

### Recommended Labels (Standard)
```markdown
Q: What is the company's remote work policy?
A: We follow a 3-2 hybrid model, with 3 days in the office and 2 days remote.
```

### Premium Labels (Markdown Bold)
Using bolding is the **most robust** method, as it survives PDF conversion better than plain text.
```markdown
**Q:** How do I reset my portal password?
**A:** Navigate to the login page and click "Forgot Password." Follow the link sent to your email.
```

### Formal Labels
```markdown
Question: Who is the point of contact for IT issues?
Answer: Please contact the Global Helpdesk at extension 5555.
```

## 2. Hierarchical Structure (Contextual Pathing)

The system captures the position of Q&A pairs within the document hierarchy. This "Section Path" is used for high-precision citations and helps the LLM distinguish between similar topics.

**Structure Example:**
```markdown
# Human Resources
## Employee Benefits
### Health Insurance

**Q: Are dental cleanings covered?**
**A:** Yes, two cleanings per year are covered at 100% for all staff.
```
*Resulting Section Path: `Human Resources > Employee Benefits > Health Insurance`*

## 3. The "Atomic Chunk" Rule

Our system chunks data at **2,000 characters**. 

- **Target**: Keep individual Q&A pairs under 1,800 characters.
- **Why?**: When a Q&A pair fits in a single chunk, it is stored as an **Atomic Item**. This means the LLM receives the full context in one piece, zeroing out the risk of "fragmented reasoning."
- **Tables**: If an answer includes a table, ensure the entire block fits within this limit to keep the table rows together.

## 4. Layout & Format Best Practices

| Best Practice | why it matters |
| :--- | :--- |
| **Markdown (.md)** | The perfect format. No conversion overhead; 100% accurate extraction. |
| **Digital PDF** | Fast processing. Scanned PDFs (Images) require OCR, which is slower and can "misread" markers (e.g., turning `Q:` into `O:`). |
| **Single Column** | Multi-column layouts can lead to "interleaved text" where Answer B is read before Question A. |
| **No Table-of-Contents** | Avoid large internal TOCs; the system builds its own semantic map from your headers. |

## 5. What to Avoid (Anti-Patterns)

*   ❌ **Vague Start**: Don't just start a paragraph without a `Q:` or `Question:` marker. The system might treat it as a general document, losing the atomic Q&A benefits.
*   ❌ **Nested Questions**: Avoid putting a second question inside the answer block of the first one.
*   ❌ **Images of Text**: If a Q&A is part of an image, the LLM will never see it unless the original PDF was processed with high-quality OCR.

---

### **Test File Template**
You can use the following template as a starting point for your Q&A documents:

```markdown
# [Project Name] Documentation
## FAQ - General Information

**Q: [Short, concise question]?**
**A:** [Detailed, structured answer. Use bullet points if needed.]

* Item 1
* Item 2
```
