"""
LLM client for structured extraction using Groq API.

Wraps the Groq OpenAI-compatible API with retry logic,
rate limiting, and native JSON mode output.

Model: meta-llama/llama-4-scout-17b-16e-instruct
  - 30 RPM, 1K RPD, 30K TPM
  - 128K+ context (MoE architecture)
  - Native JSON mode (response_format)
"""
import time
import json
from groq import Groq

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


class GroqClient:
    """
    Drop-in replacement: now backed by Groq's OpenAI-compatible API.
    """

    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or config.GROQ_API_KEY
        self.model_name = model_name or config.EXTRACTION_MODEL
        self.max_retries = config.MAX_RETRIES

        if not self.api_key or self.api_key == "your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY not set. Get a free key at "
                "https://console.groq.com and set it in .env"
            )

        self.client = Groq(api_key=self.api_key)

    def extract(self, prompt: str, retry_count: int = 0) -> dict:
        """
        Send an extraction prompt to Groq and parse the JSON response.
        Uses native JSON mode — no markdown wrapping to strip.
        Implements retry with exponential backoff for rate limits.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},   # Native JSON mode
                temperature=0.1,
                timeout=120,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from Groq")

            result = json.loads(content)
            return result

        except json.JSONDecodeError as e:
            if retry_count < self.max_retries:
                wait = 2 ** retry_count
                print(f"  JSON parse error, retrying in {wait}s... ({e})")
                time.sleep(wait)
                return self.extract(prompt, retry_count + 1)
            raise ValueError(f"Failed to parse JSON after {self.max_retries} retries: {e}")

        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                if retry_count < self.max_retries:
                    wait = 2 ** (retry_count + 2)
                    print(f"  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    return self.extract(prompt, retry_count + 1)
            if retry_count < self.max_retries:
                wait = 2 ** retry_count
                print(f"  Error: {e}, retrying in {wait}s...")
                time.sleep(wait)
                return self.extract(prompt, retry_count + 1)
            raise
