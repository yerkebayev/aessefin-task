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
from src.utils.prompt import (
    ASSISTANT_INSTRUCTIONS,
    EXTRA_INSTRUCTIONS_IT,
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

    thread_id = data.get("thread_id") or os.getenv("OPENAI_THREAD_ID")
    role = data.get("role", "user")
    content_text = data.get("content", "")
    url_media = []  

    if not content_text and not url_media:
        return api_error("Provide 'content' or 'files' with {url, mediaType}.", 400)

    try:
        if not thread_id:
            thread = create_thread(client)
            if isinstance(thread, dict):
                thread_id = thread.get("id")
            else:
                thread_id = getattr(thread, "id", None)

        if not thread_id:
            return api_error("Could not obtain thread_id.", 500)

        post_message2(
            client=client,
            thread_id=thread_id,
            role=role,
            content_text=content_text,
            url_media=url_media,
        )

        run_obj = run_assistant(
            client,
            thread_id,
            assistant_id,
            client_info=data.get("client_info"),
        )

        if isinstance(run_obj, dict):
            run_id = run_obj.get("id")
        else:
            run_id = getattr(run_obj, "id", None)

        if not run_id:
            return api_error("Could not obtain run_id.", 500)

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
            return jsonify({"messages": []}), 200

        messages_list: list[str] = []
        try:
            parsed = json.loads(last_assistant_text)
            if isinstance(parsed, dict) and isinstance(parsed.get("messages"), list):
                for item in parsed["messages"]:
                    if isinstance(item, str) and item.strip():
                        messages_list.append(item.strip())
            else:
                messages_list = [last_assistant_text.strip()]
        except Exception:
            messages_list = [last_assistant_text.strip()]

        return jsonify({
            "messages": messages_list,
        }), 200

    except Exception as e:
        return api_error(str(e), 400)


@bp.post("/update")
def update_ai():
    try:
        client = build_openai_client()
    except Exception as e:
        return api_error(str(e), 500)

    assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
    if not assistant_id:
        return api_error("'assistant_id' is required.", 400)

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    company_name = (data.get("company_name") or "Aessefin").strip()
    sector = (data.get("sector") or "settore bancario").strip()

    assistant_goal = (data.get("assistant_goal") or
                      "Aiutare i clienti dell’azienda a ottenere le informazioni necessarie e l’assistenza relativa ai servizi dell’azienda.").strip()

    escalation_phrase = (data.get("escalation_phrase") or
                         "Verificherò la sua richiesta con un responsabile. Uno dei nostri specialisti la contatterà.").strip()

    knowledge_text = (data.get("knowledge") or "").strip()
    if knowledge_text:
        knowledge_block = knowledge_text
    else:
        knowledge_block = (
            "Il blocco di conoscenze dell’azienda non è ancora compilato. Rispondi solo sulla base dei principi "
            "generali di questo prompt e fai domande di chiarimento se le informazioni non sono sufficienti."
        )

    assistant_display_name = (data.get("assistant_name") or "Aessandro").strip()

    instructions = ASSISTANT_INSTRUCTIONS.format(
        company_name=company_name,
        sector=sector,
        assistant_goal=assistant_goal,
        escalation_phrase=escalation_phrase,
        knowledge_block=knowledge_block,
    )

    try:
        updated = client.beta.assistants.update(
            assistant_id=assistant_id,
            name=assistant_display_name,
            instructions=instructions,
            model="gpt-4o",
            metadata={
                "project": "aessefin-demo",
                "env": "dev",
                "company_name": company_name,
                "sector": sector,
            },
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "multi_turn_reply",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "messages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Elenco di brevi messaggi, ognuno di 1–3 frasi."
                            }
                        },
                        "required": ["messages"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )

        data_out = updated.model_dump() if hasattr(updated, "model_dump") else updated
        print("Updated:", data_out.get("id"), data_out.get("name"))

        return jsonify(data_out), 200

    except Exception as e:
        return api_error(str(e), 400)

    try:
        client = build_openai_client()
    except Exception as e:
        return api_error(str(e), 500)

    assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
    if not assistant_id:
        return api_error("'assistant_id' is required.", 400)

    try:
        updated = client.beta.assistants.update(
            assistant_id=assistant_id,
            name="Aessandro",
            instructions=ASSISTANT_INSTRUCTIONS,
            model="gpt-4o",
            metadata={
                "project": "aessefin-demo",
                "env": "dev",
            },
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "multi_turn_reply",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "messages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Elenco di brevi messaggi, ognuno di 1–3 frasi."
                            }
                        },
                        "required": ["messages"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )

        data = updated.model_dump() if hasattr(updated, "model_dump") else updated
        print("Updated:", data.get("id"), data.get("name"))

        return jsonify(data), 200

    except Exception as e:
        return api_error(str(e), 400)