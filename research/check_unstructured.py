try:
    from langchain_community.document_loaders import UnstructuredFileLoader
    print("UnstructuredFileLoader available")
except ImportError:
    print("UnstructuredFileLoader NOT available")
