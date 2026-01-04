from langchain_community.document_loaders import UnstructuredFileLoader
import os

def test_unstructured(file_path):
    print(f"Testing UnstructuredFileLoader for: {file_path}")
    if not os.path.exists(file_path):
        print("File not found.")
        return
        
    try:
        loader = UnstructuredFileLoader(file_path)
        docs = loader.load()
        if docs:
            text = "\n\n".join([doc.page_content for doc in docs])
            print(f"Extraction successful. Text length: {len(text)}")
            print("Text Preview:")
            print(text[:500])
        else:
            print("No documents loaded.")
    except Exception as e:
        print(f"Unstructured extraction failed: {e}")

if __name__ == "__main__":
    test_unstructured("upload_docs/TECHNICAL_REPORT_V8.pdf")
