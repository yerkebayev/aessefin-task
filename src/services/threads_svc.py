from typing import Optional, Dict, Any, List, Tuple
from src.utils.prompt import (
    ASSISTANT_INSTRUCTIONS,
    EXTRA_INSTRUCTIONS_IT
)

def _parse_media(payload: dict) -> List[Tuple[str, str]]:
    files = payload.get("files") or []
    out: List[Tuple[str, str]] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        url = (f.get("url") or "").strip()
        media_type = (f.get("mediaType") or f.get("type") or "").strip().lower()
        if url and media_type in {"image", "audio", "video", "document"}:
            out.append((url, media_type))
    return out


def post_message2(
    client,
    thread_id: str,
    role: str,
    content_text: Optional[str],
    url_media: List[Tuple[str, str]],
) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []

    for url, media_type in url_media:
        content.append({"type": media_type, "url": url})

    text = (content_text or "").strip()
    if text:
        content.append({"type": "text", "text": text})

    if not content:
        raise ValueError("Provide 'content' or 'files' with {url, mediaType}.")

    msg = client.beta.threads.messages.create(
        thread_id=thread_id,
        role=role or "user",
        content=content,
    )
    return msg.model_dump() if hasattr(msg, "model_dump") else msg


def create_thread(client) -> Dict[str, Any]:
    th = client.beta.threads.create()
    return th.model_dump() if hasattr(th, "model_dump") else th


def list_messages(
    client,
    thread_id: str,
    after: Optional[str],
    limit: int,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    kwargs = {
        "thread_id": thread_id,
        "after": after,
        "limit": limit,
    }
    if run_id:
        kwargs["run_id"] = run_id

    res = client.beta.threads.messages.list(**kwargs)
    return res.model_dump() if hasattr(res, "model_dump") else res


def run_assistant(
    client,
    thread_id: str,
    assistant_id: str,
    client_info: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "tool_choice": "auto",
    }

    parts = [EXTRA_INSTRUCTIONS_IT]

    if client_info:
        parts.append("Informazioni sul cliente: " + client_info.strip())

    payload["additional_instructions"] = "\n\n".join(
        p.strip() for p in parts if p and p.strip()
    )

    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "multi_turn_reply",
            "schema": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Elenco di brevi messaggi (1–3 frasi ciascuno) "
                            "nell’ordine in cui devono essere inviati al cliente."
                        ),
                    }
                },
                "required": ["messages"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

    run = client.beta.threads.runs.create(**payload)
    return run.model_dump() if hasattr(run, "model_dump") else run


def retrieve_run(client, thread_id: str, run_id: str) -> Dict[str, Any]:
    run = client.beta.threads.runs.retrieve(
        thread_id=thread_id,
        run_id=run_id
    )
    return run.model_dump() if hasattr(run, "model_dump") else run
