import os
import time
import shutil
import logging
import threading
from dotenv import load_dotenv
load_dotenv()
from backend.ingestion.watcher import WatchdogService

# Configure logging to see output
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

def setup_test_docs():
    """Sets up a temporary upload_docs structure for testing."""
    test_dir = "test_upload_temp"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir)
    
    # Create some dummy text files
    for i in range(5):
        with open(os.path.join(test_dir, f"test_doc_{i}.txt"), "w") as f:
            f.write(f"This is test document number {i}. It contains some content for indexing.")
            
    return test_dir

def main():
    print("Starting Watcher Verification Test...")
    
    # 0. Clear debug MD folder for fresh results
    debug_dir = "generated_doc_md"
    if os.path.exists(debug_dir):
        print(f"Clearing {debug_dir}...")
        for f in os.listdir(debug_dir):
            if f.endswith(".md"):
                os.remove(os.path.join(debug_dir, f))

    # 1. Setup
    test_source_dir = setup_test_docs()
    watch_dir = "upload_docs"
    
    # 2. Start Watcher
    watcher = WatchdogService(watch_dir=watch_dir)
    watcher.start()
    
    print(f"Watcher started on {watch_dir}. Waiting 2 seconds before upload...")
    time.sleep(2)
    
    # 3. Simulate Multi-Doc Upload (Fast Copy)
    print("Simulating multi-doc upload (copying 3 files to upload_docs/General)...")
    dest_dir = os.path.join(watch_dir, "General")
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    for i in range(3):
        fname = f"test_doc_{i}.txt"
        src = os.path.join(test_source_dir, fname)
        dst = os.path.join(dest_dir, fname)
        print(f"Copying {fname}...")
        shutil.copy(src, dst)

    # 3b. Simulate MOVE (Rename) upload using os.rename
    print("Simulating MOVE upload (moving 2 files from temp to upload_docs/General using os.rename)...")
    for i in range(3, 5):
        fname = f"test_doc_{i}.txt"
        src = os.path.join(test_source_dir, fname)
        dst = os.path.join(dest_dir, f"renamed_test_doc_{i}.txt")
        print(f"Renaming {fname} to {os.path.basename(dst)}...")
        os.rename(src, dst)
        
    # 3c. Simulate same filename in different subfolders
    print("Simulating same filename in different subfolders...")
    qna_dir = os.path.join(watch_dir, "QnA")
    if not os.path.exists(qna_dir):
        os.makedirs(qna_dir)
    
    fname = "collision_test.txt"
    with open(os.path.join(dest_dir, fname), "w") as f:
        f.write("Content for General folder")
    with open(os.path.join(qna_dir, fname), "w") as f:
        f.write("Content for QnA folder")
        
    # 4. Wait and Observe
    print("Upload complete. Waiting 15 seconds for ingestion processing...")
    time.sleep(15)
    
    # 5. Check Results
    print("\nVerification Results:")
    import glob
    md_files = glob.glob(os.path.join(debug_dir, "*.md"))
    print(f"Generated MD files count: {len(md_files)}")
    for mf in md_files:
        print(f" - Found: {mf}")
        
    # 6. Cleanup
    print("\nStopping watcher...")
    watcher.stop()
    print("Test finished.")

if __name__ == "__main__":
    main()
