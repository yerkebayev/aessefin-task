from __future__ import annotations
import os
import time
import json
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

@bp.post("/chat")
def chat_once():
    try:
        client = build_openai_client()
    except Exception as e:
        return api_error(str(e), 500)

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
    if not assistant_id:
        return api_error("'assistant_id' is required.", 400)

    thread_id = data.get("thread_id")
    role = data.get("role", "user")
    content_text = data.get("content", "")
    url_media = []  # later: data.get("files", [])

    if not content_text and not url_media:
        return api_error("Provide 'content' or 'files' with {url, mediaType}.", 400)

    try:
        # If there is no thread_id – create a new thread
        if not thread_id:
            thread = create_thread(client)
            if isinstance(thread, dict):
                thread_id = thread.get("id")
            else:
                thread_id = getattr(thread, "id", None)

        if not thread_id:
            return api_error("Could not obtain thread_id.", 500)

        # Post user message into the thread
        post_message2(
            client=client,
            thread_id=thread_id,
            role=role,
            content_text=content_text,
            url_media=url_media,
        )

        # Run assistant
        run_obj = run_assistant(
            client,
            thread_id,
            assistant_id,
        )

        if isinstance(run_obj, dict):
            run_id = run_obj.get("id")
        else:
            run_id = getattr(run_obj, "id", None)

        if not run_id:
            return api_error("Could not obtain run_id.", 500)

        # Wait for run completion (polling)
        max_wait_seconds = 30
        wait_step = 0.5
        waited = 0.0
        last_run = run_obj
        status = None

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

        # Read last assistant message
        msgs = list_messages(client, thread_id, after=None, limit=10, run_id=run_id)

        if isinstance(msgs, dict) and "data" in msgs:
            iterable = msgs["data"]
        else:
            iterable = msgs

        last_assistant_text = None

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
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_obj = block.get("text") or {}
                        v = text_obj.get("value")
                        if v:
                            parts.append(v)
                if parts:
                    last_assistant_text = "\n\n".join(parts)
                    break

        if not last_assistant_text:
            return jsonify({
                "thread_id": thread_id,
                "message": "",
            }), 200

        # Convert to a single message string
        message_text = None
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
            pass

        if not message_text:
            message_text = last_assistant_text.strip()

        return jsonify({
            "thread_id": thread_id,
            "message": message_text,
        }), 200

    except Exception as e:
        return api_error(str(e), 400)