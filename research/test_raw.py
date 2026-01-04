from docling.document_converter import DocumentConverter
import os

def test_raw_iteration(file_path):
    print(f"Testing raw iteration for: {file_path}")
    if not os.path.exists(file_path):
        print("File not found.")
        return
        
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document
        
        print(f"Document object: {type(doc)}")
        
        count = 0
        texts = []
        for item, _ in doc.iterate_items():
            count += 1
            if hasattr(item, 'text') and item.text:
                texts.append(item.text)
            
            if count > 100: # Don't flood the log
                break
        
        print(f"Iterated {count} items.")
        print(f"Found text in {len(texts)} items.")
        if texts:
            print("Text sample:")
            print("\n".join(texts[:10]))
        else:
            print("No text found in items.")
            
    except Exception as e:
        print(f"Raw iteration failed: {e}")

if __name__ == "__main__":
    test_raw_iteration("upload_docs/TECHNICAL_REPORT_V8.pdf")
