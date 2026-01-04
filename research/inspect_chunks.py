import chromadb
import os

def inspect_file(filename):
    persist_dir = "chroma_db"
    if not os.path.exists(persist_dir):
        print(f"Error: {persist_dir} not found.")
        return

    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_collection("rag_documents")
    
    print(f"Total count: {collection.count()}")
    
    # Query for the specific filename
    results = collection.get(
        where={"filename": filename},
        limit=20,
        include=['documents', 'metadatas']
    )
    
    if not results['documents']:
        print(f"No documents found for {filename}")
        return
        
    print(f"Found {len(results['documents'])} chunks for {filename}.\n")
    for i, doc in enumerate(results['documents']):
        print(f"--- Chunk {i} ---")
        print(f"Metadata: {results['metadatas'][i]}")
        print(f"Content Preview: {doc[:300]}...")
        print("-" * 20)

if __name__ == "__main__":
    inspect_file("TECHNICAL_REPORT_V8.pdf")
