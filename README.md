# Multi-Message OpenAI Assistant Gateway (Flask)

Small Flask gateway around the **OpenAI Assistants API** that:

- Configures an Assistant for a specific company (name, sector, goal, knowledge, etc.).
- Accepts user messages and returns an **ordered list of short, human-like replies**.
- Forces the Assistant to always respond as:

{
  "messages": [
    "First short message…",
    "Second short message…"
  ]
}

The assistant:

- Speaks in **natural, human-like language** (prompt tuned for Russian/Italian).
- Can answer with **2–3 separate short messages** in one turn (multiple chat bubbles).
- Splits **explanations** and **questions** into different messages where it makes sense.

---

## 1. Architecture

- **Backend:** Flask (`threads` Blueprint mounted under `/v1/threads`).
- **LLM:** OpenAI Assistants API (`gpt-4o`).

Flow per request:

1. User message is appended to an OpenAI **Thread**.
2. A **Run** is created for the configured **Assistant**.
3. Assistant uses a JSON schema `response_format` → always outputs `{ "messages": [...] }`.
4. `/v1/threads/chat`:
   - Polls the Run until `status = completed`.
   - Reads the last assistant message for this Run.
   - Parses JSON and returns only `{"messages": [...]}` to the client.

The project is **sector-agnostic** (Banking, Fashion, Hospitality, etc.): behavior is configured via `/v1/threads/update`, not hardcoded.

---

## 2. Environment & Prerequisites

### Requirements

- Python **3.10+**
- `pip` (and optionally `virtualenv`)
- OpenAI API key with **Assistants API** access

### Environment variables

Set via `.env` or shell:

- `OPENAI_API_KEY` – your OpenAI API key
- `OPENAI_ASSISTANT_ID` – target Assistant ID (e.g. `asst_Ia7AK99oS3kQeAVnuLGJFRfp`)

Optional:

- `OPENAI_THREAD_ID` – reuse a specific thread across calls
- `FLASK_APP` – e.g. `app.py`
- `FLASK_ENV` – `development` or `production`
- `FLASK_RUN_PORT` – e.g. `5001`

---

## 3. Installation & Run

# 1) Clone the repository
git clone https://github.com/yerkebayev/aessefin-task.git
cd aessefin-task

# 2) Create and activate virtualenv
python -m venv .venv
source .venv/bin/activate           # Linux/macOS
# .venv\Scripts\activate          # Windows

# 3) Install dependencies
pip install -r requirements.txt

# 4) Run Flask
export FLASK_APP=app.py
export FLASK_RUN_PORT=5001
export OPENAI_API_KEY=sk-...
export OPENAI_ASSISTANT_ID=asst_...

flask run

Base URL: http://127.0.0.1:5001

---

## 4. Endpoint: Update Assistant

URL

POST /v1/threads/update

Updates the existing Assistant (`OPENAI_ASSISTANT_ID`) using:

- Template prompt `ASSISTANT_INSTRUCTIONS` (company name, sector, goal, escalation, knowledge, etc.).
- Strict JSON schema `response_format` so the Assistant always returns `{ "messages": [...] }`.

### Request body (JSON)

All fields optional (defaults applied if omitted):

{
  "company_name": "Aessefin",
  "sector": "settore bancario",
  "assistant_goal": "Aiutare i clienti dell’azienda a ottenere le informazioni necessarie e l’assistenza relativa ai servizi dell’azienda.",
  "escalation_phrase": "Verificherò la sua richiesta con un responsabile. Uno dei nostri specialisti la contatterà.",
  "knowledge": "Qui puoi inserire un testo che descrive l’azienda, i servizi, le limitazioni, le regole, ecc.",
  "assistant_name": "Aessandro"
}

The backend fills placeholders in `ASSISTANT_INSTRUCTIONS` and calls:

- `client.beta.assistants.update(...)` with:
  - `name = assistant_name`
  - `instructions =` rendered prompt
  - `model = "gpt-4o"`
  - `response_format =` JSON schema:

{
  "type": "json_schema",
  "json_schema": {
    "name": "multi_turn_reply",
    "schema": {
      "type": "object",
      "properties": {
        "messages": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Elenco di brevi messaggi, ognuno di 1–3 frasi."
        }
      },
      "required": ["messages"],
      "additionalProperties": false
    },
    "strict": true
  }
}

So the assistant must answer with:

{
  "messages": [
    "Prima frase...",
    "Seconda frase..."
  ]
}

### Example curl

curl -X POST "http://127.0.0.1:5001/v1/threads/update"   -H "Content-Type: application/json"   -d '{
    "company_name": "Boutique Milano",
    "sector": "fashion retail",
    "assistant_goal": "Aiutare i clienti a scegliere prodotti, gestire ordini e risolvere dubbi.",
    "escalation_phrase": "Coinvolgerò un collega del servizio clienti per darle una risposta precisa.",
    "knowledge": "Boutique Milano vende abbigliamento premium, non gestisce resi oltre 30 giorni...",
    "assistant_name": "Sara"
  }'

---

## 5. Endpoint: Chat

URL

POST /v1/threads/chat

### Request body (JSON)

Minimal:

{
  "content": "Hi"
}

Fields:

- `content` – user message (required if no files)
- `thread_id` – optional; new Thread is created when missing
- `role` – usually "user"
- `client_info` – optional context forwarded as `additional_instructions`
  (e.g. "Cliente VIP, parla italiano.")

Example:

curl -X POST "http://127.0.0.1:5001/v1/threads/chat"   -H "Content-Type: application/json"   -d '{
    "content": "Potresti spiegarmi brevemente come lavorate e cosa potete fare per me?",
    "client_info": "Cliente nuovo, interessato a servizi banking."
  }'

### Response

Always:

{
  "messages": [
    "Prima risposta breve dell’assistente…",
    "Secondo messaggio, ad esempio una domanda di chiarimento…"
  ]
}

Internal steps:

1. `post_message2` → send user message to Thread.
2. `run_assistant` → start Run with same JSON schema `response_format`.
3. Poll until `status = "completed"`.
4. `list_messages` → get messages for this Run.
5. Take last assistant message, parse JSON body, and return the `messages[]` array.
   Fallback: if parsing fails → return a single string as `messages[0]`.

---

## 6. Multi-Message, Human-Like Replies

With prompt + JSON schema:

- The Assistant often splits one turn into 2–3 short messages:
  - 1st message: explanation / clarification (no "?").
  - 2nd (and maybe 3rd): a single clear question or next step.
- Each message:
  - 1–3 sentences,
  - warm, professional, slightly emotional/empathetic when appropriate,
  - adapted to the configured `sector` and `knowledge` (company description).

Frontend:

- Renders each element of `messages[]` as a separate chat bubble.
- Does not need to know anything about Runs, Threads, or schema.

---

## 7. Inspecting the Assistant via OpenAI

curl https://api.openai.com/v1/assistants/$OPENAI_ASSISTANT_ID   -H "Authorization: Bearer $OPENAI_API_KEY"

You will see:

- `name` – from `assistant_name` passed to `/update`
- `instructions` – rendered system prompt
- `response_format` – `multi_turn_reply` JSON schema

---

## 8. Typical Flow per Client / Company

1. Configure Assistant with `/v1/threads/update`:
   - `company_name` = "Hotel Aurora"
   - `sector` = "hospitality"
   - `knowledge` = booking rules, rooms, check-in, etc.

2. Chat with `/v1/threads/chat`:

   {
     "content": "Buongiorno, come funziona il check-in e quali sono gli orari?"
   }

3. Example reply:

   {
     "messages": [
       "Buongiorno, le spiego come funziona il check-in in Hotel Aurora: l’orario standard è dalle 14:00, mentre il check-out è entro le 11:00.",
       "Per aiutarla meglio, potrebbe dirmi in quali date vorrebbe soggiornare?"
     ]
   }

4. Iterate:
   - Refine `knowledge`, `assistant_goal`, `escalation_phrase` via `/update`.
   - Re-test using `/chat`.

---

## 9. Notes / TODO

- Add authentication (API key / JWT) to `/v1/threads/*`.
- Add logging & tracing for conversation debugging.
- Add file/media support (`files` with `{url, mediaType}`) in `/chat`.

For multi-tenant use (bank, fashion brand, hotel chain, etc.):

- Deploy once.
- Call `/v1/threads/update` per tenant with:
  - name, sector, goal, knowledge block, escalation phrase, assistant name.
- The Assistant adapts to each company without backend code changes.
