import re
import zlib

def extract_text_from_pdf_binary(file_path):
    print(f"Brute-force extracting from: {file_path}")
    try:
        with open(file_path, "rb") as f:
            data = f.read()

        # Find all FlateDecode streams
        stream_chunks = re.findall(b"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL)
        
        extracted_text = []
        for chunk in stream_chunks:
            try:
                # Try to decompress
                decompressed = zlib.decompress(chunk)
                
                # Find text inside BT ... ET blocks or just look for Tj/TJ operators
                # This is a very simplified Tj/TJ extractor
                # Tj: (text) Tj
                # TJ: [(text) 123 (text)] TJ
                t_matches = re.findall(b"\((.*?)\)\s?T[jJ]", decompressed)
                for tm in t_matches:
                    try:
                        extracted_text.append(tm.decode('utf-8', errors='ignore'))
                    except:
                        pass
            except:
                # Not a zlib stream or failed to decompress
                pass
        
        # Also check for uncompressed text in binary
        # (Very primitive)
        raw_text = re.findall(b"\((.*?)\)\s?T[jJ]", data)
        for rt in raw_text:
             try:
                extracted_text.append(rt.decode('utf-8', errors='ignore'))
             except:
                pass

        return " ".join(extracted_text)
    except Exception as e:
        print(f"Brute force failed: {e}")
        return ""

if __name__ == "__main__":
    text = extract_text_from_pdf_binary("upload_docs/TECHNICAL_REPORT_V8.pdf")
    print(f"Extracted {len(text)} characters.")
    print("Preview:")
    print(text[:1000])
