from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import PdfFormatOption
from docling.datamodel.base_models import InputFormat
import os

def test_ocr(file_path):
    print(f"Testing OCR-only docling for: {file_path}")
    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True # Force OCR
        pipeline_options.do_table_structure = False # Disable tables
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        result = converter.convert(file_path)
        print("Convert status: Success")
        md = result.document.export_to_markdown()
        print(f"MD length: {len(md)}")
        print("MD Preview:")
        print(md[:500])
    except Exception as e:
        print(f"OCR docling failed: {e}")

if __name__ == "__main__":
    test_ocr("upload_docs/TECHNICAL_REPORT_V8.pdf")
