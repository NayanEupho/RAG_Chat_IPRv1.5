from docling.document_converter import DocumentConverter
import os

def test_simple(file_path):
    print(f"Testing simple docling for: {file_path}")
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        print("Convert status: Success")
        md = result.document.export_to_markdown()
        print(f"MD length: {len(md)}")
        print("MD Preview:")
        print(md[:500])
    except Exception as e:
        print(f"Simple docling failed: {e}")

if __name__ == "__main__":
    test_simple("upload_docs/TECHNICAL_REPORT_V8.pdf")
