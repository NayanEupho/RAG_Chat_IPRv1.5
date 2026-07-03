import importlib.util


if importlib.util.find_spec("pdfminer"):
    print("pdfminer installed")
else:
    print("pdfminer NOT installed")
