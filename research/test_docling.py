from docling.document_converter import DocumentConverter
import sys
import os

def test_extraction(file_path):
    print(f"Testing extraction for: {file_path}")
    if not os.path.exists(file_path):
        print("File not found.")
        return
        
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        md = result.document.export_to_markdown()
        print(f"Extraction successful. MD length: {len(md)}")
        print("MD Preview:")
        print(md[:500])
    except Exception as e:
        print(f"Extraction failed: {e}")

if __name__ == "__main__":
    test_extraction("upload_docs/TECHNICAL_REPORT_V8.pdf")
