import importlib.util


def print_availability(module_name: str, label: str) -> None:
    status = "installed" if importlib.util.find_spec(module_name) else "NOT installed"
    print(f"{label} {status}")


print_availability("pypdf", "pypdf")
print_availability("fitz", "PyMuPDF")
print_availability("pdfplumber", "pdfplumber")
