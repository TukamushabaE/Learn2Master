
import os
import json
import logging
from engine import KnowledgeBase, get_kb
from pathlib import Path

from unittest.mock import MagicMock

# Mock environment if needed
os.environ['HF_TOKEN'] = os.environ.get('HF_TOKEN', 'mock_token')

logging.basicConfig(level=logging.INFO)

def test_kb_logic():
    from engine import KnowledgeBase
    kb_dir = Path("test_kb")
    kb_dir.mkdir(exist_ok=True)

    # Create a dummy file
    test_file = kb_dir / "test.txt"
    test_file.write_text("Physics is the study of matter and energy. ICT is Information and Communication Technology.")

    print(f"--- Initializing KB in {kb_dir} ---")
    # Patch KnowledgeBase to use a mock hf_client
    original_init = KnowledgeBase.__init__
    def mocked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.hf_client = MagicMock()
        # Mock feature_extraction to return dummy embeddings
        self.hf_client.feature_extraction.side_effect = lambda chunks, model: [[0.1]*384 for _ in chunks]

    # Temporarily override __init__ for the test if needed, or just set it after
    kb = KnowledgeBase(directory="test_kb")
    kb.hf_client = MagicMock()
    kb.hf_client.feature_extraction.side_effect = lambda chunks, model: [[0.1]*384 for _ in (chunks if isinstance(chunks, list) else [chunks])]

    # Re-trigger load to use the mock
    kb.load_and_process()

    print(f"Chunks loaded: {len(kb.chunks)}")
    processed_files_path = kb_dir / "_processed_files.json"

    if processed_files_path.exists():
        with open(processed_files_path, 'r') as f:
            processed = json.load(f)
            print(f"Processed files log: {processed}")
            assert "test.txt" in processed
    else:
        print("Error: _processed_files.json not created")

    # Test Search (Local Fallback if no embeddings)
    print("Testing search (expecting local search if embeddings are None)...")
    results = kb.search("What is Physics?")
    print(f"Search results: {results}")

    # Clean up
    # test_file.unlink()
    # processed_files_path.unlink()
    # kb_dir.rmdir()

if __name__ == "__main__":
    test_kb_logic()
