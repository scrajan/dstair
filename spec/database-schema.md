# DSTAIR Database Schema

The database uses SQLAlchemy ORM with a modular, domain-separated design. The development engine is SQLite (`instance/dstair.db`). Production may use PostgreSQL via the same SQLAlchemy interface with no code changes required.

> **Active Record Pattern**: All database interaction functions (get, save, delete, custom queries) live inside the Model class they belong to, via `ActiveRecordMixin`. No separate repository layer exists or should ever be created.

---

## Core Models (`models/core_models.py`)

Static, foundational data seeded once at startup. These records are never created or modified by application users at runtime.

---

### Country

Canonical list of approximately 200 sovereign states. Used as a foreign key reference for `AIAnalysis`. **Not used to drive any UI dropdown** — country dropdowns are static hardcoded HTML.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `code` | String, Unique | ISO code or display name, e.g. `"US"`, `"Afghanistan"` |
| `name` | String | Full display name, e.g. `"United States"` |
| `order` | Integer | Display order |

**Relationships**: Referenced by `AIAnalysis.country` (FK).

---

### Sphere

Represents one of the 9 institutional domains. Drives frontend tab ordering and all sphere-based display logic.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `name` | String | Internal uppercase identifier, e.g. `"CONSTITUTION"` |
| `label` | String | Human-readable display name, e.g. `"Constitution"` |
| `order` | Integer | Tab display order (1–9) |

**Relationships**: Owns `questions` and `tool_criteria` (cascade delete on both).

---

### Question

An individual evaluation criterion within a Sphere. Drives question display order, scale labels, type badges, importance weighting, and help tooltips.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `sphere_id` | Integer, FK → Sphere | |
| `order` | Integer | Display order within the sphere |
| `content` | Text | The question text shown to the user |
| `scale_min_label` | String | Label for rating = 1 (e.g. "Very Weak") |
| `scale_max_label` | String | Label for rating = 7 (e.g. "Very Strong") |
| `type` | String | One of: `META-RULE`, `RULE`, `EXOGENOUS` |
| `importance` | Integer | `1` (low), `2` (medium), `3` (high) — used as weight `aᵢⱼ` in scoring |
| `help_info` | Text | Full explanatory text shown in the "More Info" popup |

**Relationships**: Belongs to `Sphere`. Owns `comments`.

---

### Comment

User-authored qualitative note attached to a specific question. May or may not be linked to a specific analysis session.

| Field | Type | Notes |
|-------|------|-------|
| `id` | String (UUID), PK | Generated at creation |
| `question_id` | Integer, FK → Question | Required — a comment always belongs to a question |
| `analysis_id` | Integer, FK → Analysis | **Nullable** — supports legacy/standalone comments not tied to a specific analysis session |
| `user_display` | String | Author's username captured at time of writing |
| `text` | Text | Sanitized via `utils/sanitizer.py` before storage |
| `created_at` | DateTime | UTC |

**Relationships**: Belongs to `Question`. Optionally belongs to `Analysis` (nullable FK).

> When an `Analysis` is deleted, associated comments where `analysis_id` matches are cascade-deleted (FK `ondelete='CASCADE'` or equivalent). Comments with `analysis_id = NULL` are standalone and are never deleted by analysis deletion.

**Legacy comment support**: Comments submitted outside any analysis context (e.g., from a standalone question view) set `analysis_id = NULL`. These comments persist indefinitely and are displayed in the Comments popup for the question, alongside analysis-linked comments.

---

### Tool

An anti-corruption reform recommendation. There are exactly 28 tools in the system, seeded from `data/tools.json`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `title` | String | Short display title |
| `description` | Text | Brief one-paragraph summary |
| `content` | Text (HTML) | Full rich-text detail shown in the "More Info" popup |

**Relationships**: Owns `criteria` (list of `ToolCriteria` records).

---

### ToolCriteria

Defines the triggering threshold for a specific Tool in a specific Sphere. A tool may have multiple criteria records — one per relevant sphere.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `tool_id` | Integer, FK → Tool | |
| `sphere_id` | Integer, FK → Sphere | |
| `min_score_threshold` | Float | Minimum score threshold (0.0–1.0). Condition satisfied when `A(j) >= this value` OR `A(j) == -1` (unanswered). |

**Trigger logic**: A tool triggers only when ALL of its `ToolCriteria` conditions are satisfied simultaneously (AND logic). For each criterion: condition is satisfied when the sphere score `A(j) >= min_score_threshold` OR the sphere is unanswered (`A(j) == -1`). This evaluation is performed by the backend on every answer save. The result is stored as a list of tool IDs in `Analysis.triggered_tools` — no many-to-many join table is used.

---

## User Models (`models/user_models.py`)

### User

Central authentication and RBAC entity. Integrates with Flask-Login via `UserMixin`.

| Field | Type | Notes |
|-------|------|-------|
| `unique_database_identifier_integer` | Integer, PK | Used as Flask-Login user ID (returned by `get_id()`) |
| `user_account_unique_username_string` | String, Unique | Immutable after creation |
| `user_account_full_name_string` | String | Editable via profile page |
| `user_account_authentication_email_address_string` | String, Unique | Editable via profile page |
| `user_account_hashed_password_string` | String | Werkzeug-hashed; never stored in plaintext |
| `user_account_authorization_role_identifier_string` | String | One of: `'user'`, `'admin'`, `'ai'`. Default: `'user'` |
| `file_path_string_for_user_profile_avatar_image` | String | Relative path within `static/uploads/profiles/`. Nullable. |
| `boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted` | Boolean | `True` = active. `False` = blacklisted (cannot log in). Default: `True`. |
| `boolean_flag_indicating_if_user_profile_has_been_completed` | Boolean | `False` on account creation. Set to `True` after the user completes their profile via `/onboarding/profile` for the first time. Drives the first-login redirect. Default: `False`. |

**Valid roles**:

| Role Value | Description |
|------------|-------------|
| `'user'` | Standard analyst |
| `'admin'` | Single platform administrator |
| `'ai'` | AI evaluator agent |

**Constraints**:

- Only one `'admin'` account may exist in the system at any time.
- AI-role accounts are invisible to and unmodifiable by the admin.
- `get_id()` returns `unique_database_identifier_integer` cast to string (Flask-Login requirement).
- `is_active` property maps to `boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted`.

---

## Analysis Models (`models/analysis_models.py`)

### Analysis

Tracks a single analyst's evaluation session for a specific country. Stores raw answers and triggered tool IDs only.

> **No `status` field**: Analysis sessions are permanently editable. There is no `in_progress` / `completed` / `draft` lifecycle state.
> **No scores stored**: Scores (`T_j`, `I_j`) are never persisted. They are computed exclusively by the frontend JavaScript engine on every render, using the stored `answers` JSON.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `user_id` | Integer, FK → User | The owning analyst |
| `title` | String | User-defined display name for the analysis session |
| `country` | String | Country code string (e.g. `'US'`). Stored as a plain string — **not a FK**. The `Country` table is not involved here. |
| `notes` | Text | Optional freeform analyst notes. Nullable. (This is a note made by the analyst of the analysis) |
| `answers` | JSON | Pre-populated skeleton built at creation time. Structure: `{ "SPHERE_NAME": { "question_id": rating_value, ... }, ... }`. Every sphere and every question ID from the database is present as a key from the moment the analysis is created. Default value for all questions is `-1`, meaning unanswered/N/A. When a user selects a rating, the value is updated to `1–7`. `-1` is the single sentinel for both "not yet answered" and "explicitly N/A" — no distinction is made. The frontend and backend both skip `-1` values in all calculations. Rating values `1–7` are the raw UI values — the frontend and backend both apply the 1–10 mapping independently when computing scores or evaluating criteria. |
| `last_sync_timestamp` | BigInteger | Epoch milliseconds of the last successful AJAX answer save. Used by the backend to detect and reject stale out-of-order responses. |
| `triggered_tools` | JSON | List of triggered tool IDs: `[1, 5, 12, ...]`. Recalculated by the backend on every answer save. This is the single source of truth for which tools are active. |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC — auto-updated on every save |

**Relationships**: Belongs to `User`. Owns `comments` (via `Comment.analysis_id`).

> **No many-to-many join table**: The `triggered_tools` JSON field is the sole mechanism for tracking active tools on an analysis. No `analysis_tools` join table exists or is needed.

---

## AI Analysis Models (`models/ai_analysis_models.py`)

### AIAnalysis

Stores AI-generated evaluations for sovereign countries. Exactly one record per country is enforced at the database level via a `Unique` constraint on `country`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `country` | String, Unique, FK → Country.code | One record per country. FK enforced. |
| `status` | String | `'not_started'`, `'in_progress'`, `'completed'`, `'error'` |
| `ai_scores_for_all_questions` | JSON | Structure: `{ "question_id": score_value }`. Scores are on the raw 1–7 scale (matching the UI). Null until evaluation completes. |
| `ai_comments_for_all_questions` | JSON | Structure: `{ "question_id": "reasoning text" }`. AI-generated rationale per question. Null until evaluation completes. |
| `metadata_json` | JSON | Generation metadata: provider used, model version, generation timestamp, number of retries, etc. |
| `created_at` | DateTime | UTC — when the record was first created |
| `updated_at` | DateTime | UTC — updated when evaluation completes or fails |

**Relationships**: References `Country` via FK on `country` code. Decoupled from `User` and `Analysis` models — AI evaluations are global, not user-scoped.

**Overwrite behavior**: When a new evaluation is triggered for an existing country, the existing record is updated in-place — `status` resets to `'in_progress'`, `ai_scores_for_all_questions` and `ai_comments_for_all_questions` are cleared to null, and new results replace them upon completion.

**Status lifecycle**:

```
not_started → in_progress → completed
                          ↘ error
```

Records seeded from `data/countries.json` start with `status='not_started'` and null score/comment fields.

---

## API Key Models (`models/api_key_models.py`)

### APIKey

Stores encrypted LLM provider API keys for AI-role users. Implements the BYOK (Bring Your Own Key) architecture.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `user_id` | Integer, FK → User | The AI-role user who owns this key |
| `provider` | String | One of: `'groq'`, `'openai'`, `'claude'`, `'gemini'`, `'openrouter'` |
| `api_key` | String | Fernet-encrypted at rest. Decrypted only at evaluation time within the AI service layer. |
| `is_active` | Boolean | `False` = key is skipped during provider cascade |
| `order` | Integer | Execution priority. Lower value = tried first. |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

**Provider cascade logic**: During evaluation, keys are sorted by `order` ascending, filtered to `is_active=True`. The AI service tries each in sequence. On first success, execution proceeds. If all fail, the evaluation aborts and `status='error'` is set.

---

## Access Request Models (`models/access_request_models.py`)

### AccessRequest

Manages the onboarding pipeline for prospective users awaiting administrator approval.

| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer, PK | |
| `name` | String | Applicant's submitted name |
| `email` | String | Applicant's submitted email |
| `organization` | String | Applicant's submitted organization |
| `message` | Text | Optional message to the administrator |
| `status` | String | `'pending'`, `'approved'`, `'rejected'` |
| `created_at` | DateTime | UTC — when the form was submitted |
| `reviewed_at` | DateTime | UTC — when admin acted on the request. Nullable. |
| `created_user_id` | Integer, FK → User | Nullable — populated only when approved, references the newly created user account |

**Status transitions**:

```
pending → approved  (creates a User account, sets created_user_id)
pending → rejected  (no account created)
any     → deleted   (record permanently removed)
```
