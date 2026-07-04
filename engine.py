import os
import json
import logging
import requests
import hashlib
import time
import threading
import re
import numpy as np
from pathlib import Path
from functools import lru_cache
from PyPDF2 import PdfReader
from huggingface_hub import InferenceClient
from groq import Groq
from supabase import create_client, Client

# Configure logging
logger = logging.getLogger(__name__)

# Constants for safety
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_JSON_ITEMS = 500
MAX_KB_ENTRIES = 10000

# Global circuit breaker state
_groq_failure_count = 0
_groq_circuit_open_until = 0.0
FAILURE_THRESHOLD = 5
BACKOFF_SECONDS = 60

def calculate_bkt(current_p, correct):
    p_transit = float(os.environ.get('BKT_TRANSIT', 0.1))
    p_slip = float(os.environ.get('BKT_SLIP', 0.1))
    p_guess = float(os.environ.get('BKT_GUESS', 0.2))

    if correct:
        p_posterior = (current_p * (1 - p_slip)) / (current_p * (1 - p_slip) + (1 - current_p) * p_guess)
        explanation = f"Correct answer detected. Probability of mastery increased from {current_p:.2f} to {p_posterior:.2f} before transition."
    else:
        p_posterior = (current_p * p_slip) / (current_p * p_slip + (1 - current_p) * (1 - p_guess))
        explanation = f"Incorrect answer detected. Mastery lowered to {p_posterior:.2f}. Suggests potential slip or knowledge gap."

    new_p = p_posterior + (1 - p_posterior) * p_transit
    new_p = max(0.01, min(new_p, 0.99))

    reasoning = {
        "p_before": current_p,
        "p_after": new_p,
        "change": new_p - current_p,
        "message": explanation,
        "parameters": {"slip": p_slip, "guess": p_guess, "transit": p_transit}
    }

    return new_p, reasoning

def get_recommendation(knowledge_level):
    if knowledge_level < 0.5:
        return "Review basic concepts and adaptive notes.", "Your current knowledge level (pL) is below 0.5, requiring foundational reinforcement."
    elif knowledge_level < 0.85:
        return "Complete adaptive practice questions.", "You are in the zone of proximal development (0.5 < pL < 0.85). Practice will solidify your mental models."
    else:
        return "Submit practical evidence for mastery.", "High conceptual mastery detected (pL >= 0.85). Demonstrate competency through practical application."

class KnowledgeBase:
    def __init__(self, directory="knowledge_base", model_id="sentence-transformers/all-MiniLM-L6-v2"):
        base_dir = Path(__file__).parent.resolve()
        self.directory = (base_dir / directory).resolve()
        self.dynamic_kb_path = self.directory / "_dynamic.jsonl"
        self.processed_files_path = self.directory / "_processed_files.json"
        self.model_id = model_id
        self.chunks = []
        self.embeddings = None
        self.hf_client = None
        self.supabase: Client = None
        self._lock = threading.Lock()
        self._processed_files = {}

        # Initialize clients
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if supabase_url and supabase_key:
            try:
                self.supabase = create_client(supabase_url, supabase_key)
                logger.info("Supabase client initialized for Knowledge Base.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase: {e}")

        # Initialize Hugging Face client
        hf_token = os.environ.get('HF_TOKEN')
        if hf_token:
            self.hf_client = InferenceClient(token=hf_token)

        self.load_processed_files_metadata()
        self.load_and_process()

    def load_processed_files_metadata(self):
        if self.processed_files_path.exists():
            try:
                with open(self.processed_files_path, 'r') as f:
                    self._processed_files = json.load(f)
            except Exception as e:
                logger.error(f"Error loading processed files metadata: {e}")
                self._processed_files = {}

    def save_processed_files_metadata(self):
        try:
            with open(self.processed_files_path, 'w') as f:
                json.dump(self._processed_files, f)
        except Exception as e:
            logger.error(f"Error saving processed files metadata: {e}")

    def _get_file_hash(self, filepath):
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _strip_markdown(self, text):
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        return text.strip()

    def _recursive_split(self, text, chunk_size=500, overlap=100):
        if len(text) <= chunk_size:
            return [text.strip()]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                # Use regex to find sentence boundaries for better chunking
                # Looks for '.', '!', or '?' followed by a space or newline
                search_area = text[start + (chunk_size // 2):end]
                matches = list(re.finditer(r'[.!?](\s|\n|$)', search_area))
                if matches:
                    # Take the last match in the search area
                    break_point = start + (chunk_size // 2) + matches[-1].end()
                    end = break_point

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap
            if start >= len(text) - overlap:
                break
        return chunks

    def _extract_text(self, obj, depth=0):
        if depth > 10: # Safety against infinite recursion
            return ""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            # Prioritize certain fields but also look deeper if needed
            content_fields = {'content', 'text', 'body', 'description', 'title', 'summary'}
            extracted = []
            # First pass: check priority fields
            for k, v in obj.items():
                if k.lower() in content_fields:
                    extracted.append(self._extract_text(v, depth + 1))

            # Second pass: if nothing found, look at everything else
            if not extracted:
                for v in obj.values():
                    if isinstance(v, (dict, list, str)):
                        res = self._extract_text(v, depth + 1)
                        if res: extracted.append(res)
            return " ".join(filter(None, extracted))
        if isinstance(obj, list):
            return " ".join(filter(None, [self._extract_text(i, depth + 1) for i in obj[:MAX_JSON_ITEMS]]))
        return ""

    def process_file(self, filepath, metadata=None, summarize=False):
        filename = os.path.basename(filepath)
        if filename.startswith('_'): return False, 0

        file_hash = self._get_file_hash(filepath)
        if filename in self._processed_files and self._processed_files[filename] == file_hash:
            logger.info(f"Skipping {filename}, already processed.")
            return True, 0

        text = ""
        try:
            if filename.endswith('.txt') or filename.endswith('.md'):
                with open(filepath, 'r', encoding='utf-8') as f:
                    text = f.read()
                    if filename.endswith('.md'):
                        text = self._strip_markdown(text)
            elif filename.endswith('.json'):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    text = self._extract_text(data)
            elif filename.endswith('.pdf'):
                reader = PdfReader(filepath)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted: text += extracted + "\n"
        except Exception as e:
            logger.error(f"Error extracting text from {filename}: {e}")
            return False, 0

        if not text: return False, 0

        # AI Summarization for large files or if requested
        processed_size = len(text)
        if summarize or len(text) > 15000:
            text = AIEngine.compress_study_material(text)
            processed_size = len(text)

        new_chunks = self._recursive_split(text)
        if not new_chunks: return False, 0

        embeddings_list = []
        if self.hf_client:
            try:
                embeddings_list = self.hf_client.feature_extraction(new_chunks, model=self.model_id)
            except Exception as e:
                logger.error(f"Error generating embeddings for {filename}: {e}")

        with self._lock:
            start_idx = len(self.chunks)
            self.chunks.extend(new_chunks)
            if embeddings_list:
                new_emb_array = np.array(embeddings_list)
                if self.embeddings is None:
                    self.embeddings = new_emb_array
                else:
                    self.embeddings = np.vstack([self.embeddings, new_emb_array])

            # Sync to Supabase
            supabase_success = True
            if self.supabase and embeddings_list:
                try:
                    data_to_insert = [
                        {
                            'content': chunk,
                            'embedding': emb,
                            'metadata': {**(metadata or {}), 'source': filename, 'hash': file_hash}
                        }
                        for chunk, emb in zip(new_chunks, embeddings_list)
                    ]
                    self.supabase.table('kb_documents').upsert(data_to_insert).execute()
                except Exception as e:
                    logger.error(f"Supabase sync error for {filename}: {e}")
                    supabase_success = False

            if supabase_success or not self.supabase:
                self._processed_files[filename] = file_hash
                self.save_processed_files_metadata()

        return True, processed_size

    def load_and_process(self):
        if not self.directory.exists():
            self.directory.mkdir(parents=True, exist_ok=True)

        # 1. Sync from Supabase Storage if available
        if self.supabase:
            try:
                res = self.supabase.storage.from_("knowledge-base").list()
                for file_info in res:
                    fname = file_info['name']
                    if fname.startswith('.') or fname.startswith('_'): continue
                    local_path = self.directory / fname
                    if not local_path.exists():
                        logger.info(f"Downloading {fname} from Supabase Storage...")
                        with open(local_path, 'wb') as f:
                            data = self.supabase.storage.from_("knowledge-base").download(fname)
                            f.write(data)
            except Exception as e:
                logger.error(f"Supabase Storage sync error: {e}")

        # 2. Process all files in directory
        for filename in sorted(os.listdir(self.directory)):
            if filename.startswith('_'): continue
            filepath = self.directory / filename
            if filepath.is_file() and filepath.stat().st_size <= MAX_FILE_BYTES:
                self.process_file(str(filepath))

        # 3. Load dynamic KB entries
        if self.dynamic_kb_path.exists():
            try:
                with open(self.dynamic_kb_path, 'r') as f:
                    for line in f:
                        entry = json.loads(line)
                        if 'text' in entry:
                            # Direct add to in-memory chunks if not already there
                            if entry['text'] not in self.chunks:
                                self.add_knowledge(entry['text'], entry.get('metadata'))
            except Exception as e:
                logger.error(f"Error loading dynamic KB: {e}")

    @lru_cache(maxsize=512)
    def get_query_embedding(self, query):
        if not self.hf_client:
             return None
        return self.hf_client.feature_extraction(query, model=self.model_id)

    def search(self, query, top_k=3):
        query_embedding = self.get_query_embedding(query)
        if query_embedding is None:
            return []

        # Ensure query_embedding is a 1D array for Supabase/dot product
        if isinstance(query_embedding, list):
            if len(query_embedding) > 0 and isinstance(query_embedding[0], list):
                query_embedding = query_embedding[0]
            query_embedding = np.array(query_embedding)
        elif isinstance(query_embedding, np.ndarray) and query_embedding.ndim > 1:
            query_embedding = query_embedding.flatten()

        if self.supabase:
            try:
                # Using Supabase rpc for vector similarity search
                # Requires a 'match_kb_chunks' function in Supabase
                response = self.supabase.rpc(
                    'match_kb_chunks',
                    {
                        'query_embedding': query_embedding.tolist(),
                        'match_threshold': 0.3,
                        'match_count': top_k,
                    }
                ).execute()

                if response.data:
                    return [item['content'] for item in response.data]
            except Exception as e:
                logger.error(f"Supabase search error: {e}. Falling back to local.")

        with self._lock:
            if not self.chunks or self.embeddings is None:
                return []

        try:
            with self._lock:
                if self.embeddings is None: return []
                query_embedding_np = np.array(query_embedding)
                if query_embedding_np.ndim > 1:
                    query_embedding_np = query_embedding_np[0]

                expected_dim = self.embeddings.shape[-1]
                if query_embedding_np.shape[-1] != expected_dim:
                     return []

                # Cosine similarity
                dot_product = np.dot(self.embeddings, query_embedding_np)
                norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_embedding_np)
                norms[norms == 0] = 1e-9
                similarities = dot_product / norms
                top_indices = np.argsort(similarities)[::-1][:top_k]
                return [self.chunks[i] for i in top_indices]
        except Exception as e:
            logger.error(f"Local search error: {e}")
            return []

    def process_file(self, filepath, metadata=None):
        """Processes a single file and adds it to the KB."""
        filename = filepath.name
        try:
            file_text = ""
            if filename.endswith('.txt') or filename.endswith('.md'):
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_text = f.read()
                    if filename.endswith('.md'): file_text = self._strip_markdown(file_text)
            elif filename.endswith('.json'):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    file_text = self._extract_text(data)
            elif filename.endswith('.pdf'):
                reader = PdfReader(filepath)
                for page in reader.pages:
                    text = page.extract_text()
                    if text: file_text += text + "\n"

            if file_text:
                # Update processed logs
                current_hash = self._get_file_hash(filepath)
                with self._lock:
                    if not self.processed_files_path.exists():
                        processed_data = {}
                    else:
                        with open(self.processed_files_path, 'r') as f:
                            processed_data = json.load(f)

                    processed_data[filename] = {'hash': current_hash, 'timestamp': time.time()}
                    with open(self.processed_files_path, 'w') as f:
                        json.dump(processed_data, f)

                # Generate chunks and embeddings
                chunks = self._recursive_split(file_text)
                if chunks and self.hf_client:
                    embeddings_list = self.hf_client.feature_extraction(chunks, model=self.model_id)
                    new_embeddings = np.array(embeddings_list)

                    with self._lock:
                        self.chunks.extend(chunks)
                        if self.embeddings is None:
                            self.embeddings = new_embeddings
                        else:
                            self.embeddings = np.vstack([self.embeddings, new_embeddings])

                    if self.supabase:
                        data_to_insert = [
                            {'content': chunk, 'embedding': emb, 'metadata': metadata or {'source': filename}}
                            for chunk, emb in zip(chunks, embeddings_list)
                        ]
                        self.supabase.table('kb_documents').upsert(data_to_insert).execute()
                    return True
        except Exception as e:
            logger.error(f"Error processing uploaded file {filename}: {e}")
        return False

    def add_knowledge(self, text, metadata=None):
        text = text.strip()
        if not text or len(text) > 4000:
            return
        new_embedding = None
        if self.hf_client:
            try:
                new_embedding_raw = self.hf_client.feature_extraction([text], model=self.model_id)
                new_embedding = np.array(new_embedding_raw)
            except Exception as e:
                logger.error(f"Error generating embedding: {e}")
                # Don't return, still add text for local fallback

        if self.supabase and new_embedding is not None:
            try:
                embedding_list = new_embedding.tolist()
                if isinstance(embedding_list[0], list):
                    embedding_list = embedding_list[0]

                self.supabase.table('kb_documents').insert({
                    'content': text,
                    'metadata': metadata or {},
                    'embedding': embedding_list
                }).execute()
            except Exception as e:
                logger.error(f"Supabase insertion error: {e}")

        for chunk in new_chunks:
            new_embedding = None
            if self.hf_client:
                try:
                    new_embedding_raw = self.hf_client.feature_extraction([chunk], model=self.model_id)
                    new_embedding = np.array(new_embedding_raw)
                except Exception as e:
                    logger.error(f"Error generating embedding: {e}")
                    continue

            if self.supabase and new_embedding is not None:
                try:
                    embedding_list = new_embedding.tolist()
                    if isinstance(embedding_list[0], list):
                        embedding_list = embedding_list[0]

                    self.supabase.table('kb_documents').insert({
                        'content': chunk,
                        'metadata': metadata or {},
                        'embedding': embedding_list
                    }).execute()
                except Exception as e:
                    logger.error(f"Supabase insertion error: {e}")

            with self._lock:
                if len(self.chunks) >= MAX_KB_ENTRIES:
                    return
                self.chunks.append(chunk)
                if new_embedding is not None:
                    if self.embeddings is None:
                        self.embeddings = new_embedding
                    else:
                        self.embeddings = np.vstack([self.embeddings, new_embedding])

        # Persistence to dynamic file
        try:
            with open(self.dynamic_kb_path, 'a') as f:
                f.write(json.dumps({'text': text, 'metadata': metadata, 'timestamp': time.time()}) + '\n')
        except Exception as e:
            logger.error(f"Persistence error: {e}")

_kb_instance = None
def get_kb():
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance

class AIEngine:
    @staticmethod
    def compress_study_material(text):
        groq_api_key = os.environ.get('GROQ_API_KEY')
        if not groq_api_key:
            return text[:5000] # Fallback to truncation
        try:
            from groq import Groq
            client = Groq(api_key=groq_api_key)
            prompt = f"Summarize the following study material into a concise pedagogical summary of approximately 5KB (about 800-1000 words) that captures all key concepts and definitions for vector search: \n\n {text[:15000]}"
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-70b-8192",
                temperature=0.3,
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Compression error: {e}")
            return text[:5000]

    @staticmethod
    def evaluate_all_work(learner_id, conn):
        # Gather all student data
        mastery = conn.execute("SELECT mr.*, lo.outcome_name FROM mastery_records mr JOIN learning_outcomes lo ON mr.outcome_id = lo.outcome_id WHERE learner_id = ?", (learner_id,)).fetchall()
        evidence = conn.execute("SELECT * FROM practical_evidence WHERE learner_id = ?", (learner_id,)).fetchall()
        attempts = conn.execute("SELECT * FROM assessment_attempts WHERE learner_id = ? ORDER BY created_at DESC LIMIT 50", (learner_id,)).fetchall()

        data_summary = f"Mastery Records: {len(mastery)}, Evidence Submissions: {len(evidence)}, Recent Attempts: {len(attempts)}"

        groq_api_key = os.environ.get('GROQ_API_KEY')
        if not groq_api_key:
            return f"AI Evaluation currently unavailable. Summary: {data_summary}"

        try:
            from groq import Groq
            client = Groq(api_key=groq_api_key)
            prompt = f"Evaluate the following student work data and provide a holistic pedagogical assessment of their progress, strengths, and areas for improvement in Physics and ICT: \n\n {data_summary}"
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-8b-8192",
                temperature=0.5,
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            return f"Error generating evaluation: {e}"

    @staticmethod
    def analyze_knowledge_gaps(mastery_records):
        gaps = []
        for record in mastery_records:
            level = record.knowledge_level if record.knowledge_level is not None else 0.0
            if level < 0.5:
                gaps.append({
                    "lo_id": record.learning_outcome_id,
                    "name": record.learning_outcome.name,
                    "level": level,
                    "priority": "High",
                    "reason": "Knowledge level is significantly below the threshold for competency."
                })
        return gaps

    @staticmethod
    def log_interaction_to_training_api(user_input, user_id, context, response):
        training_url = os.environ.get('TRAINING_API_URL')
        if not training_url:
            return
        def _send():
            payload = {
                "query_hash": hashlib.sha256(user_input.encode()).hexdigest(),
                "query_len": len(user_input),
                "user_pseudo": hashlib.sha256(str(user_id).encode()).hexdigest(),
                "avg_mastery": context.get('avg_mastery', 0.0),
                "response_len": len(response),
                "timestamp": time.time()
            }
            try:
                requests.post(training_url, json=payload, timeout=5)
            except Exception as e:
                logger.error(f"Background log failed: {e}")
        threading.Thread(target=_send, daemon=True).start()

    @staticmethod
    def tutor_response(user_input, context):
        global _groq_failure_count, _groq_circuit_open_until
        groq_api_key = os.environ.get('GROQ_API_KEY')
        username = context.get('username', 'Student')
        user_id = context.get('user_id', 'unknown')
        avg_mastery = context.get('avg_mastery', 0.0)
        gaps = context.get('gaps', [])
        if time.time() < _groq_circuit_open_until:
             return "I'm currently undergoing maintenance. Please try again shortly."
        if not groq_api_key:
            return "I'm currently undergoing maintenance. Please try again shortly."
        kb = get_kb()
        relevant_context = kb.search(user_input)
        context_str = "\n".join(relevant_context)
        try:
            client = Groq(api_key=groq_api_key)
            system_prompt = f"You are the Learn2Master AI Assistant. Help {username} with Physics and ICT. CBC context: {context_str}"
            user_message = f"<query>{user_input}</query>"
            chat_completion = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                model="llama3-8b-8192",
                temperature=0.7,
            )
            response_text = chat_completion.choices[0].message.content
            _groq_failure_count = 0
            AIEngine.log_interaction_to_training_api(user_input, user_id, context, response_text)
            return response_text
        except Exception as e:
            _groq_failure_count += 1
            if _groq_failure_count >= FAILURE_THRESHOLD:
                _groq_circuit_open_until = time.time() + BACKOFF_SECONDS
            logger.error(f"Groq API Error: {e}")
            return "I'm having trouble connecting to my knowledge core. Let's try again in a moment."
