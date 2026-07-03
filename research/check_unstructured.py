import importlib.util


if importlib.util.find_spec("langchain_community.document_loaders"):
    print("UnstructuredFileLoader available")
else:
    print("UnstructuredFileLoader NOT available")
