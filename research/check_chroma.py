from backend.rag.store import get_vector_store
store = get_vector_store()
print(f"Total documents: {store.count()}")
print(f"File list: {store.get_all_files()}")
