import os
import json
import logging
import hashlib
import time
import threading
import re
from pathlib import Path
from functools import lru_cache

try:
    import requests
except ImportError:
    requests = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from huggingface_hub import InferenceClient
except ImportError:
    InferenceClient = None

try:
    from groq import Groq
except ImportError:
    Groq = None

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
        self.model_id = model_id
        self.chunks = []
        self.embeddings = None
        self.hf_client = None
        self._lock = threading.Lock()

        hf_token = os.environ.get('HF_TOKEN')
        if hf_token and InferenceClient:
            self.hf_client = InferenceClient(token=hf_token)

        self.load_and_process()

    def _strip_markdown(self, text):
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        return text.strip()

    def _extract_text(self, obj):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return " ".join(self._extract_text(v) for k, v in obj.items() if k in ('content', 'text', 'body', 'description', 'title'))
        if isinstance(obj, list):
            return " ".join(self._extract_text(i) for i in obj[:MAX_JSON_ITEMS])
        return ""

    def load_and_process(self):
        with self._lock:
            # Clear existing state for full reload
            self.chunks = []
            self.embeddings = None

            if not self.directory.exists():
                self.directory.mkdir(parents=True, exist_ok=True)

            all_text = ""
            for filename in sorted(os.listdir(self.directory)):
                if filename.startswith('_'): continue
                filepath = self.directory / filename
                try:
                    if filepath.stat().st_size > MAX_FILE_BYTES:
                        continue

                    if filename.endswith('.txt') or filename.endswith('.md'):
                        with open(filepath, 'r', encoding='utf-8') as f:
                            text = f.read()
                            if filename.endswith('.md'):
                                text = self._strip_markdown(text)
                            all_text += text + "\n"
                    elif filename.endswith('.json'):
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            all_text += self._extract_text(data) + "\n"
                    elif filename.endswith('.pdf') and PdfReader:
                        reader = PdfReader(filepath)
                        for page in reader.pages:
                            text = page.extract_text()
                            if text:
                                all_text += text + "\n"
                except Exception as e:
                    logger.error(f"Error reading source {filename}: {e}")

            if all_text:
                sentences = all_text.replace('\n', ' ').split('. ')
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < 500:
                        current_chunk += sentence + ". "
                    else:
                        self.chunks.append(current_chunk.strip())
                        current_chunk = sentence + ". "
                if current_chunk:
                    self.chunks.append(current_chunk.strip())

            # Load dynamic
            if self.dynamic_kb_path.exists():
                try:
                    with open(self.dynamic_kb_path, 'r') as f:
                        for line in f:
                            entry = json.loads(line)
                            if 'text' in entry:
                                self.chunks.append(entry['text'])
                except Exception as e:
                    logger.error(f"Error loading dynamic KB: {e}")

            if self.chunks and self.hf_client and np:
                try:
                    embeddings = self.hf_client.feature_extraction(self.chunks, model=self.model_id)
                    self.embeddings = np.array(embeddings)
                    logger.info(f"Initialized KB with {len(self.chunks)} chunks.")
                except Exception as e:
                    logger.error(f"Error generating KB embeddings: {e}")

    @lru_cache(maxsize=512)
    def get_query_embedding(self, query):
        if not self.hf_client:
             return None
        return self.hf_client.feature_extraction(query, model=self.model_id)

    def search(self, query, top_k=3):
        with self._lock:
            if not self.chunks or self.embeddings is None or not self.hf_client:
                return []

        try:
            if not np:
                return []
            query_embedding = np.array(self.get_query_embedding(query))
            if len(query_embedding.shape) > 1:
                query_embedding = query_embedding[0]

            with self._lock:
                if self.embeddings is None: return []
                expected_dim = self.embeddings.shape[-1]
                if query_embedding.shape[-1] != expected_dim:
                     return []
                if self.embeddings.ndim == 1:
                     self.embeddings = self.embeddings.reshape(1, -1)
                dot_product = np.dot(self.embeddings, query_embedding)
                norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_embedding)
                norms[norms == 0] = 1e-9
                similarities = dot_product / norms
                top_indices = np.argsort(similarities)[::-1][:top_k]
                return [self.chunks[i] for i in top_indices]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def add_knowledge(self, text):
        text = text.strip()
        if not text or len(text) > 4000:
            return
        new_embedding = None
        if self.hf_client and np:
            try:
                new_embedding = np.array(self.hf_client.feature_extraction([text], model=self.model_id))
            except Exception as e:
                logger.error(f"Error generating embedding: {e}")
                return
        with self._lock:
            if len(self.chunks) >= MAX_KB_ENTRIES:
                return
            self.chunks.append(text)
            if new_embedding is not None:
                if self.embeddings is None:
                    self.embeddings = new_embedding
                else:
                    self.embeddings = np.vstack([self.embeddings, new_embedding])
            try:
                with open(self.dynamic_kb_path, 'a') as f:
                    f.write(json.dumps({'text': text, 'timestamp': time.time()}) + '\n')
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
        if not training_url or not requests:
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
        if not groq_api_key or not Groq:
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
