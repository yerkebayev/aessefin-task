from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Iterable

from flask import Blueprint, request, jsonify

from src.utils.errors import api_error
from src.openai_client import build_openai_client
from src.services.threads_svc import (
    create_thread,
    list_messages,
    run_assistant,
    retrieve_run,
    post_message2,
)

bp = Blueprint("threads", __name__)

# ---------------------------------------------------------------------------
# Helpers for multi-assistant support (one API key, multiple assistants)
# ---------------------------------------------------------------------------

def _load_assistant_ids() -> Dict[str, str]:
    """
    Loads mapping of assistant_name -> assistant_id from environment variables.

    Supports two formats:

    1) Via JSON:
       OPENAI_ASSISTANTS_JSON='{"sales": "asst_...", "banking": "asst_..."}'

    2) Via dedicated env vars:
       OPENAI_ASSISTANT_ID_SALES=asst_...
       OPENAI_ASSISTANT_ID_BANKING=asst_...

       In that case, assistant names in URL:
       /chat/sales, /chat/banking

    Additionally, if OPENAI_ASSISTANT_ID is set,
    it will be available under the name "default" (/chat/default).
    """
    mapping: Dict[str, str] = {}

    # --- Option 1: JSON in OPENAI_ASSISTANTS_JSON ---
    raw_json = os.getenv("OPENAI_ASSISTANTS_JSON")
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict):
                for name, value in data.items():
                    if isinstance(value, str):
                        mapping[name.lower()] = value
                    elif isinstance(value, dict):
                        asst_id = value.get("assistant_id")
                        if isinstance(asst_id, str):
                            mapping[name.lower()] = asst_id
        except Exception:
            # If JSON is malformed, ignore silently
            pass

    # --- Option 2: individual environment variables OPENAI_ASSISTANT_ID_<NAME> ---
    prefix = "OPENAI_ASSISTANT_ID_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Example: OPENAI_ASSISTANT_ID_SALES -> "sales"
            name = key[len(prefix):].lower()
            if value:
                mapping[name] = value

    # --- Default assistant (optional) ---
    default_id = os.getenv("OPENAI_ASSISTANT_ID")
    if default_id:
        mapping.setdefault("default", default_id)

    return mapping


ASSISTANT_IDS: Dict[str, str] = _load_assistant_ids()


def _get_assistant_id(assistant_name: str) -> Optional[str]:
    """
    Returns assistant_id by assistant name from URL.
    Case-insensitive (sales / SALES / Sales).
    """
    if not assistant_name:
        return None
    return ASSISTANT_IDS.get(assistant_name.lower())


def _extract_last_assistant_text(messages: Iterable[Any]) -> Optional[str]:
    """
    From list_messages result, extract the last assistant text message
    as a single string.
    """
    if isinstance(messages, dict) and "data" in messages:
        iterable = messages["data"]
    else:
        iterable = messages

    last_assistant_text: Optional[str] = None

    for m in reversed(list(iterable)):
        if isinstance(m, dict):
            role_m = m.get("role")
            content = m.get("content")
        else:
            role_m = getattr(m, "role", None)
            content = getattr(m, "content", None)

        if role_m != "assistant":
            continue

        if isinstance(content, str):
            last_assistant_text = content
            break
        elif isinstance(content, list) and content:
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_obj = block.get("text") or {}
                    v = text_obj.get("value")
                    if v:
                        parts.append(v)
            if parts:
                last_assistant_text = "\n\n".join(parts)
                break

    return last_assistant_text


def _maybe_parse_messages_json(last_assistant_text: str) -> str:
    """
    If the assistant response is JSON with a "messages" list (as strings),
    convert it into one multiline string. Otherwise, just strip and return.
    """
    if not last_assistant_text:
        return ""

    last_assistant_text = last_assistant_text.strip()
    if not last_assistant_text:
        return ""

    message_text: Optional[str] = None

    try:
        parsed = json.loads(last_assistant_text)
        if isinstance(parsed, dict) and isinstance(parsed.get("messages"), list):
            parts = [
                item.strip()
                for item in parsed["messages"]
                if isinstance(item, str) and item.strip()
            ]
            if parts:
                message_text = "\n\n".join(parts)
    except Exception:
        # Not JSON or wrong structure – ignore and fall back
        pass

    if not message_text:
        message_text = last_assistant_text

    return message_text


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@bp.post("/chat/<assistant_name>")
def chat_once(assistant_name: str):
    """
    Single-turn chat endpoint.

    - assistant_name comes from URL, e.g. "sales", "banking"
    - For that name, we find assistant_id from env (OPENAI_ASSISTANT_ID_<NAME> or JSON)
    - Uses a single OpenAI API key (from env, via build_openai_client)
    """
    # 1. Resolve assistant_id by name
    assistant_id = _get_assistant_id(assistant_name)
    if not assistant_id:
        return api_error(f"Unknown assistant '{assistant_name}'.", 404)

    # 2. Build OpenAI client (uses a single API key from env)
    try:
        client = build_openai_client()
    except Exception as e:
        return api_error(f"Failed to build OpenAI client: {e}", 500)

    # 3. Parse incoming JSON
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    thread_id = data.get("thread_id")
    role = data.get("role", "user")
    content_text = data.get("content", "")
    # Later: support data.get("files", [])
    url_media: List[Dict[str, Any]] = []

    if not content_text and not url_media:
        return api_error("Provide 'content' or 'files' with {url, mediaType}.", 400)

    try:
        # 4. If there is no thread_id – create a new thread
        if not thread_id:
            thread = create_thread(client)
            if isinstance(thread, dict):
                thread_id = thread.get("id")
            else:
                thread_id = getattr(thread, "id", None)

        if not thread_id:
            return api_error("Could not obtain thread_id.", 500)

        # 5. Post user message into the thread
        post_message2(
            client=client,
            thread_id=thread_id,
            role=role,
            content_text=content_text,
            url_media=url_media,
        )

        # 6. Run assistant
        run_obj = run_assistant(
            client=client,
            thread_id=thread_id,
            assistant_id=assistant_id,
        )

        if isinstance(run_obj, dict):
            run_id = run_obj.get("id")
        else:
            run_id = getattr(run_obj, "id", None)

        if not run_id:
            return api_error("Could not obtain run_id.", 500)

        # 7. Wait for run completion (polling)
        max_wait_seconds = 30
        wait_step = 0.5
        waited = 0.0
        last_run = run_obj
        status: Optional[str] = None

        while waited < max_wait_seconds:
            if isinstance(last_run, dict):
                status = last_run.get("status")
            else:
                status = getattr(last_run, "status", None)

            if status in ("completed", "failed", "cancelled", "expired"):
                break

            time.sleep(wait_step)
            waited += wait_step
            last_run = retrieve_run(client, thread_id, run_id)

        if status != "completed":
            return api_error(
                f"Run not completed (status={status}, waited={waited:.1f}s).",
                504,
            )

        # 8. Read last assistant message
        msgs = list_messages(
            client=client,
            thread_id=thread_id,
            after=None,
            limit=10,
            run_id=run_id,
        )

        last_assistant_text = _extract_last_assistant_text(msgs)

        if not last_assistant_text:
            return jsonify(
                {
                    "assistant": assistant_name,
                    "thread_id": thread_id,
                    "message": "",
                }
            ), 200

        # 9. Convert to single return string
        message_text = _maybe_parse_messages_json(last_assistant_text)

        return jsonify(
            {
                "assistant": assistant_name,
                "thread_id": thread_id,
                "message": message_text,
            }
        ), 200

    except Exception as e:
        return api_error(str(e), 400)
