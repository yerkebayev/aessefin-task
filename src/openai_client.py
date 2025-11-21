import os
from openai import OpenAI


"""
    Create and return an OpenAI client.
    Reads the API key (and optional project ID) from environment variables.
"""

def build_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing. Add it to your .env file.")

    return OpenAI(api_key=api_key)
