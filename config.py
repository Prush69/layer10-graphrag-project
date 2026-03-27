"""
Configuration for the Layer10 Grounded Long-Term Memory system.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# --- Paths ---
BASE_DIR = Path(__file__).parent

# Load environment variables from .env file
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    # Fallback to standard search if .env isn't in BASE_DIR
    load_dotenv()
RAW_DATA_DIR = BASE_DIR / "corpus" / "raw"
DATA_DIR = BASE_DIR / "data"
GRAPH_PATH = DATA_DIR / "graph.json"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.faiss"
CONTEXT_PACKS_DIR = DATA_DIR / "context_packs"
EXTRACTION_DIR = DATA_DIR / "extractions"

# Ensure directories exist
for d in [RAW_DATA_DIR, DATA_DIR, CONTEXT_PACKS_DIR, EXTRACTION_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Neo4j Constants (Primary Datastore if running)
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "layer10db")
if GROQ_API_KEY:
    print("[OK] Groq API Key loaded")
if GITHUB_TOKEN:
    print("[OK] GitHub Token loaded")

# --- Corpus Config ---
GITHUB_REPO = "facebook/react"
MAX_ISSUES = 15       # Number of issues to download for test
ISSUES_PER_PAGE = 30   # GitHub API page size

# --- Extraction Config ---
EXTRACTION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # Groq: 30K TPM, MoE 128K ctx
CONFIDENCE_THRESHOLD = 0.4   # Minimum confidence to keep a claim
MAX_RETRIES = 3
EXTRACTION_BATCH_SIZE = 3    # Issues per LLM batch (~5K-7K tokens per prompt)
GROQ_RATE_LIMIT_DELAY = 13.0 # Wait 13s between batches to stay under 30K TPM limit

# --- Embedding Config ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.85  # For deduplication

# --- Storage Backend Config ---
VECTOR_DIM = 384 # Matches all-MiniLM-L6-v2

# --- Server Config ---
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False







