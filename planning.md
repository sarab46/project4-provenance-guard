## Provenance Guard — Planning

### Architecture

Submission flow (high level):

- Client submits text -> `POST /submit` (Submission Endpoint)
- Request is received by Flask backend (`app.py`) which performs input validation and rate limiting
- Text is passed to two independent detection signals:
  1. Groq LLM classification (semantic/holistic signal)
  2. Stylometric heuristics (structural/statistical signal)
- Each signal returns a score in [0,1] where higher = more likely AI-generated
- A confidence-scoring component combines the signals (weighted average + calibrated uncertainty) to produce a final confidence value
- The transparency label text is selected based on thresholds (high-confidence AI, uncertain, high-confidence human) and returned to the caller
- The full decision, scores, signals used, and label text are persisted to an audit log (SQLite)
- Response returned to the client with structured attribution result, confidence, and label text

ASCII diagram (submission / appeal flows):

Submission flow:

```
Client -> POST /submit -> Flask app
                    Flask app -> Groq signal -> groq_score
                    Flask app -> Stylometry -> stylo_score
                    groq_score + stylo_score -> Scoring -> final_score
                    final_score -> Label selector -> label_text
                    Decision -> Audit log -> DB
                    Flask app -> Response (result, confidence, label)
```

Appeal flow:

```
Client -> POST /appeal -> Flask app -> validate -> write appeal to DB
                                       -> update audit.notes/status -> Response (under review)
```

Architecture narrative (2 sentences): The submission pipeline receives text, runs two independent signals (Groq LLM and stylometry), combines their scores into a calibrated confidence, and selects a human-readable label. Appeals are collected via an API, update the content's status to "under review", and are logged for human review.

Appeal flow (high level):

- Creator files an appeal via `POST /appeal` with `content_id` and `reason`
- Backend validates appeal, updates the content status to `under review`, and logs the appeal in the audit log alongside the original decision
- Response acknowledges receipt and returns updated status

### Components

- Flask API (`app.py`): request handling, routing
- Detection signals:
  - Groq LLM: ask model whether text reads as AI-generated vs human
  - Stylometry module: compute features (avg sentence length, sentence length variance, type-token ratio, punctuation density)
- Confidence scoring: aggregator that combines signals into final confidence and maps to label text
- Audit log: SQLite DB with structured records for decisions and appeals
- Rate limiting: `Flask-Limiter` configured on `POST /submit`

### Detection signals (chosen)

1) Groq LLM classification
- What it measures: semantic, topical, and stylistic patterns the LLM recognizes as either AI-written or human-written; captures discourse-level coherence and generic phrasing
- Why it helps: LLMs learn patterns common in AI-generated text and can often identify subtle cues
- Blind spots: models can be fooled by adversarial paraphrasing, fine-tuned human-like outputs, or when AI output is heavily edited by humans

2) Stylometric heuristics
- What it measures: structural statistical properties such as mean sentence length, variance in sentence length, type-token ratio (vocabulary diversity), punctuation density, and repetitiveness
- Why it helps: human writing tends to have higher variance and more idiosyncratic lexical choices; AI often produces more uniform outputs
- Blind spots: short texts have unreliable statistics; an experienced human writer may intentionally mimic AI, and AI can be tuned to match human statistics

These two are complementary: one is semantic and high-level, the other is low-level statistical.

### False positive scenario (human writer misclassified as AI)

- Scenario: a human publishes a short, polished excerpt that reads very uniformly (low lexical variance). Stylometry flags it as AI (high score) and Groq gives a moderate AI score.
- How the system handles it:
  - Final confidence will reflect combined signals (e.g., stylometry 0.92, groq 0.70 -> combined 0.82)
  - The label for 0.82 falls into "High-confidence AI" — user sees label and may be upset
  - Creator files appeal via `POST /appeal` with explanation and any provenance evidence
  - System updates status to `under review` and logs the appeal; a human reviewer can inspect and override if appropriate

Design choice to mitigate harm: thresholds bias slightly toward minimizing false positives (err on side of uncertain rather than high-confidence AI when signals conflict). 

### API surface

1) `POST /submit`
- Accepts JSON: `{ "content_id": "c1", "text": "...", "creator_id": "u1" }`
- Returns JSON: `{ "content_id": "c1", "result": "ai|human|uncertain", "confidence": 0.82, "label": "..." }`

2) `GET /log`
- Returns recent audit-log entries (JSON array) for inspection. Supports optional filters by `content_id`.

3) `POST /appeal`
- Accepts JSON: `{ "content_id": "c1", "creator_id": "u1", "reason": "I wrote this myself..." }`
- Returns acknowledgment and updated status: `{ "content_id": "c1", "status": "under review" }`

### Confidence scoring

- Each signal returns a score s_i in [0,1] where 1 = definitely AI. We compute a weighted average:

- final_score = w_groq * s_groq + w_stylo * s_stylo

- Default weights: `w_groq = 0.6`, `w_stylo = 0.4` (semantic signal slightly higher priority)
- Thresholds mapping to labels:
  - final_score >= 0.90 -> High-confidence AI
  - final_score <= 0.10 -> High-confidence human
  - otherwise -> Uncertain attribution

- To reduce false positives, we will shift towards showing "uncertain" when signals conflict: if |s_groq - s_stylo| >= 0.25 and final_score is between 0.60 and 0.90, we downgrade to "uncertain" to prompt appeal instead of a hard AI label.

### Uncertainty representation

- Interpretation: a confidence score is the estimated probability the content is AI-generated. Example: `0.6` means the system believes there's a 60% chance the content is AI-generated; label and UX will communicate this as "uncertain" rather than a hard call.  
- Calibration: raw signal outputs are in [0,1]; weighted average produces `final_score` which is used directly as the confidence. We add the conflict rule to avoid overconfident labels when signals disagree.

### Transparency label design (exact text)

- High-confidence AI:
  "High-confidence AI-generated: This content is very likely generated by AI (confidence: 90%+). If you are the creator and believe this is incorrect, you may file an appeal."
- High-confidence human:
  "High-confidence human-written: This content appears to be written by a human (confidence: 90%+). If you are the creator and believe this is incorrect, you may file an appeal."
- Uncertain:
  "Uncertain attribution: The system is uncertain whether this content was written by a human or generated by AI (confidence: 50%–90%). Creator appeals are available."

### Rate limiting

- Rationale: creators rarely submit more than a few drafts per day. Limit combats automated floods.
- Default chosen limits:
  - `POST /submit`: 60 requests per hour per IP and 30 requests per hour per creator_id
  - These numbers balance legitimate usage (roughly 1 per minute peak) while limiting mass abuse.

### Audit log schema (example)

- Table `audit` columns: `id`, `timestamp`, `content_id`, `creator_id`, `result`, `confidence`, `signals_json`, `label_text`, `notes`
- Table `appeals` columns: `id`, `timestamp`, `content_id`, `creator_id`, `reason`, `status`, `linked_audit_id`

### Next steps (implementation plan)

1. Scaffold Flask app and requirements
2. Implement stylometric heuristics and unit tests
3. Implement Groq integration (or mock if key missing)
4. Implement confidence scoring + label selection
5. Implement audit log and appeals API
6. Add rate limiting and sample audit entries
7. Write README usage and run instructions

### Appeals workflow (detailed)

- Who can submit: the `creator_id` associated with the content (system validates match) or a platform moderator on behalf of a creator.  
- Required information: `content_id`, `creator_id`, `reason` (free text), optional `evidence_url`.  
- On receipt: create an `appeals` row with `status = "under review"`, link to the most recent `audit` row for `content_id`, append a short note to the audit `notes` field, and return `{ status: "under review", appeal_id }`.  

### Anticipated edge cases (specific)

1. Very short text (1-2 sentences or <20 tokens): stylometry metrics are unreliable and may yield misleading high AI scores. System response: treat such submissions conservatively — bias toward `uncertain` unless Groq strongly indicates AI.  
2. Poetry with deliberate repetition and simple vocabulary: stylometry may flag low TTR and low variance, causing false AI scores. System response: markdown/text-type detection could be added later; for now, treat poems with caution and prefer `uncertain`.

### AI Tool Plan

- M3 (submission endpoint + first signal):
  - Provide to AI tool: `## Architecture`, `### Detection signals` (Groq description), ASCII diagram, and API spec for `POST /submit`.
  - Ask it to generate: a Flask app skeleton with `POST /submit` route and a Groq wrapper function (or stub) that returns a score in [0,1].
  - Verification: run the Flask app locally and call `POST /submit` with sample texts; confirm the Groq stub returns deterministic scores and the endpoint responds with JSON.

- M4 (second signal + confidence scoring):
  - Provide to AI tool: `### Detection signals` (stylometry description), `### Uncertainty representation`, and ASCII diagram.
  - Ask it to generate: `stylometry.py` with functions returning a [0,1] score and scoring logic that combines signals into `final_score` with thresholds and conflict rule.
  - Verification: run unit tests on `stylometry.compute_stylometry_score` with clear human vs AI-like samples and verify final scores map to different labels.

- M5 (production layer):
  - Provide to AI tool: `### Transparency label design`, `### Appeals workflow`, and ASCII diagram.
  - Ask it to generate: label selection logic, `POST /appeal` endpoint, SQLite schema and persistence, and `/log` endpoint.
  - Verification: submit samples to reach all three labels and submit an appeal; confirm DB rows and status changes.

