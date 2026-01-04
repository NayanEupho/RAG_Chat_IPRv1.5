from docling.document_converter import DocumentConverter
import os
import json

def test_json(file_path):
    print(f"Testing JSON export for: {file_path}")
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        print("Convert status: Success")
        js_data = result.document.export_to_dict()
        print(f"JSON data size: {len(json.dumps(js_data))}")
    except Exception as e:
        print(f"JSON export failed: {e}")

if __name__ == "__main__":
    test_json("upload_docs/TECHNICAL_REPORT_V8.pdf")
