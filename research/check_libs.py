try:
    import pypdf
    print("pypdf installed")
except ImportError:
    print("pypdf NOT installed")

try:
    import fitz # PyMuPDF
    print("PyMuPDF installed")
except ImportError:
    print("PyMuPDF NOT installed")

try:
    import pdfplumber
    print("pdfplumber installed")
except ImportError:
    print("pdfplumber NOT installed")
