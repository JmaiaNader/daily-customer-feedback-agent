"""Manual smoke test for the local Ollama instance; no cloud key is required."""
import os
import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

try:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": "Reply with exactly: Local Ollama connection successful",
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    print("Local Ollama connection successful!")
    print("Model response:", response.json().get("response", ""))
except requests.exceptions.RequestException as error:
    print("Local Ollama request failed:", error)
    print("Check that Ollama is running and the model has been downloaded.")
