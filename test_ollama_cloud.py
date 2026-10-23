import getpass
import requests


api_key = "53683d5610f1437a84988bdcfcfaa4df.2MpaGsj6nBMSMdoDA2tQEyHc"

url = "https://ollama.com/api/chat"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

payload = {
    "model": "gemma4:31b",
    "messages": [
        {
            "role": "user",
            "content": "Reply with exactly: Ollama Cloud connection successful",
        }
    ],
    "stream": False,
}

try:
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()

    result = response.json()
    print("\nAPI connection successful!")
    print("Model response:", result["message"]["content"])

except requests.exceptions.RequestException as error:
    print("\nAPI request failed:", error)
    if getattr(error, "response", None) is not None:
        print("HTTP status:", error.response.status_code)
        print("Details:", error.response.text[:1000])