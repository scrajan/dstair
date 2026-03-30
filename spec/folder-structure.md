# DSTAIR Folder Structure

This document provides a comprehensive, LLM-friendly reference of the project's directory structure, architectural pattern, and the responsibility of every file. It is the canonical source for understanding where logic lives and why.

---

## Architectural Pattern

The application follows a **Controller-Service-Model (Active Record)** architecture.

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Controllers | `routes/` | Thin HTTP routing. Parses requests, delegates to services, returns responses. No business logic. |
| Business Logic | `services/` | All core algorithms, scoring, external API calls, threading. |
| Data Models | `models/` | SQLAlchemy schema definitions + all DB interaction via Active Record. |
| Infrastructure | `core/` & `utils/` | Error handling, exceptions, decorators, encryption, sanitization, uploads. |

> The repository layer was fully removed. No repository files exist. All DB queries live inside Model classes via `ActiveRecordMixin`.

---

## Routing System

Routes are organized by role and grouped into Flask Blueprints with URL prefixes.

### Public Routes (no authentication required)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Landing page |
| GET | `/about` | About page |
| GET | `/how-it-works` | Methodology page |
| GET | `/resources` | Resources page |
| GET | `/faq` | FAQ page |
| GET | `/contact` | Access Request form page |
| POST | `/contact` | Submit Access Request form |
| GET | `/login` | Login page |
| POST | `/login` | Authenticate user |
| GET | `/logout` | Destroy session, redirect to login |
| GET | `/healthz` | Health check endpoint |

### Shared Authenticated Routes (all roles)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/onboarding/profile` | View profile page |
| POST | `/onboarding/profile` | Update name, email, profile image |

### Standard User Routes (role=user)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/regular_user/<username>/dashboard` | User dashboard (analyses list, stats) |
| GET | `/regular_user/<username>/tools` | Aggregated triggered tools library |
| GET | `/regular_user/<username>/analysis/<id>` | Analysis workspace shell (loads questionnaire tab by default) |
| GET | `/regular_user/<username>/analysis/<id>/tab/<tab_name>` | Render tab partial HTML (questionnaire, results, tools) |
| POST | `/analysis/create` | Create new analysis — returns JSON with id and redirect URL |
| POST | `/analysis/<id>/answer` | AJAX — save a single answer, returns triggered_tools list |
| POST | `/analysis/<id>/edit` | Update analysis title and notes — accepts JSON, returns JSON |
| POST | `/analysis/<id>/delete` | Delete analysis and cascade-delete its comments — returns JSON |
| GET | `/analysis/question/<qid>/ai-context` | AJAX — fetch AI score and comment for a question |
| POST | `/analysis/question/<qid>/comment` | Post a comment on a question |
| DELETE | `/analysis/question/<qid>/comment/<cid>/delete` | Delete a specific comment |

> **Note on legacy routes**: `/analysis/<id>` and `/analysis/<id>/tab/<tab_name>` remain registered as secondary routes for admin panel compatibility (the admin comments page links to analyses). They are not user-facing primary URLs.

### Admin Routes (role=admin)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/admin/dashboard` | Admin dashboard (stats overview) |
| GET | `/admin/users` | User management list |
| POST | `/admin/users/create` | Create a new normal user account |
| POST | `/admin/users/<id>/edit` | Edit user name and email |
| POST | `/admin/users/<id>/delete` | Permanently delete a user |
| POST | `/admin/users/<id>/blacklist` | Toggle user blacklist status |
| GET | `/admin/access-requests` | Access request review queue |
| POST | `/admin/access-requests/<id>/approve` | Approve request, create user account |
| POST | `/admin/access-requests/<id>/reject` | Reject request |
| POST | `/admin/access-requests/<id>/delete` | Delete request record |
| GET | `/admin/comments` | Global comment moderation feed |

### AI User Routes (role=ai)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/ai/dashboard` | AI dashboard (stats and archive) |
| GET | `/ai/analysis` | Country evaluation trigger page |
| POST | `/ai/analysis/evaluate` | Trigger background AI evaluation |
| GET | `/ai/analysis/<id>` | View a completed AI analysis (scores + reasoning) |
| GET | `/ai/analysis/<id>/status` | Poll evaluation status |
| DELETE | `/ai/analysis/<id>/delete` | Delete an AI analysis record |
| GET | `/ai/api-keys` | API key manager page |
| POST | `/ai/api-keys/save` | Save a new encrypted API key |
| POST | `/ai/api-keys/<id>/toggle` | Toggle key active/inactive |
| DELETE | `/ai/api-keys/<id>/delete` | Delete an API key |
| POST | `/ai/api-keys/reorder` | Update key execution priority order |

---

## Directory Layout

---

### Root Level

#### `app.py`

Application factory. Wires together all extensions, registers all blueprints with their URL prefixes, attaches error handlers, sets security headers, and invokes database initialization. This is the sole assembly point for the entire application — nothing else initializes the Flask app.

---

#### `config.py`

Environment-aware configuration. Defines `DevelopmentConfig`, `ProductionConfig`, and `TestingConfig` by reading from `.env`. Exposes a runtime guard that prevents insecure defaults (e.g., weak `SECRET_KEY`) from running in production.

---

#### `extensions.py`

Instantiates all Flask extensions (`db`, `migrate`, `csrf`, `limiter`, `login_manager`) as module-level objects. This prevents circular imports by separating extension creation from the application factory.

---

#### `run.py`

The single, mandatory application entry point. Detects the environment and starts either Waitress (production) or the Flask development server (`--dev` flag or `FLASK_ENV=development`). No other entry point file (`wsgi.py`, etc.) should exist.

---

### `core/` — Core Application Infrastructure

#### `core/error_handlers.py`

Global HTTP error interceptor. Handles 400, 401, 403, 404, and 500 errors. Detects whether the request expects JSON (AJAX calls) and returns either a JSON payload or a rendered HTML error template. Changes here affect all routes globally.

#### `core/exceptions.py`

Defines custom exception classes: a base exception, a request payload validation exception, and a resource-not-found exception. Services raise these; routes catch them cleanly without exposing raw error strings.

---

### `models/` — Database Entity Definitions

> For complete field definitions, see `spec/database-schema.md`.

#### `models/base.py`

Defines `ActiveRecordMixin` — the shared base that gives all models Active Record methods for saving, updating, deleting, and querying. Every model class inherits from this alongside `db.Model`.

#### `models/core_models.py`

Houses the static, foundational models: `Country`, `Sphere`, `Question`, `Tool`, `ToolCriteria`, and `Comment`. These are seeded once from `data/` and are not modified at runtime. Sanitization of `Comment.text` is applied via SQLAlchemy event listeners that delegate to `utils/sanitizer.py` — no direct bleach calls inside this file.

#### `models/user_models.py`

Defines the `User` model. Handles RBAC roles (`user`, `admin`, `ai`), Flask-Login integration (`UserMixin`), the blacklist flag, and the profile completion flag. Uses descriptive column names to make intent explicit without requiring comments.

#### `models/analysis_models.py`

Defines the `Analysis` model. Stores `answers` (pre-populated skeleton JSON: all sphere names and question IDs present from creation, values are `-1` until answered, `1–7` once rated) and `triggered_tools` (list of integer tool IDs as JSON). No scores are stored. No `status` field. The `country` field is a plain string — not a foreign key to `Country`.

#### `models/ai_analysis_models.py`

Defines the `AIAnalysis` model. One record per country (enforced by DB unique constraint on `country`). Stores `ai_scores_for_all_questions` (flat dict of `{ question_id: score }` on the raw 1–7 scale), `ai_comments_for_all_questions` (flat dict of `{ question_id: reasoning }`), and `metadata_json`. Strictly decoupled from user `Analysis` records.

#### `models/api_key_models.py`

Defines the `APIKey` model. Stores Fernet-encrypted LLM provider keys scoped per AI user, with priority ordering and active/inactive toggle. Encryption and decryption are delegated to `utils/encryption`.

Supported provider values: `'groq'`, `'openai'`, `'claude'`, `'gemini'`, `'openrouter'`.

#### `models/access_request_models.py`

Defines the `AccessRequest` model. Tracks the full lifecycle of an onboarding request: `pending` → `approved` / `rejected`. Links to the created `User` record on approval.

#### `models/__init__.py`

Package initializer. Imports and re-exports all model classes so other modules can import from `models` directly (e.g., `from models import User, Analysis`).

---

### `services/` — Business Logic Layer

Services contain all non-trivial logic. Routes call services. Services call models. Services never render templates or handle HTTP directly.

#### `services/analysis_service.py`

Core logic for the questionnaire system. Responsibilities:

- Creating, updating metadata for, and deleting analyses.
- Building the pre-populated `answers` skeleton at analysis creation time by loading all `Sphere` and `Question` records — every sphere name and question ID is present as a key, all initialized to `-1`.
- Saving individual answers to the `answers` JSON with pessimistic locking (prevents race conditions on concurrent AJAX saves). An incoming answer overwrites the existing `-1` sentinel with the rated value `1–7`. The backend skips all `-1` values when evaluating `ToolCriteria` thresholds.
- Internally evaluating `ToolCriteria` thresholds using the raw 1–7 formula `A(j) = Σ(a×r) / (7×Σa)` and recalculating `triggered_tools` after each answer change. A criterion is satisfied when `A(j) >= threshold` OR the sphere is unanswered.
- Composing radar chart data: fetching other-user analyses for the same country, fetching AI baseline if available, and pre-serializing all series into plain dicts for JSON-safe template rendering.
- Fetching AI context (score + reasoning) for a specific question and country from the `AIAnalysis` record.
- Managing comments: creation (with ownership capture), deletion (with authorization check), and fetching.

#### `services/ai_service.py`

LLM evaluation engine. Responsibilities:

- Building structured prompts from `Sphere` and `Question` data.
- Dispatching concurrent requests across all 9 spheres to the selected provider.
- Implementing the provider fallback cascade: decrypt keys → try in order → abort with `status='error'` on total failure.
- Atomically persisting scores and comments to `AIAnalysis` on success.
- All provider-specific HTTP logic — endpoint URLs, authentication headers, request format, response parsing — is fully encapsulated here for all five providers (`groq`, `openai`, `claude`, `gemini`, `openrouter`). No provider details leak outside this service.

#### `services/user_service.py`

User account management. Responsibilities:

- Authentication: password verification, session initiation, role-based redirect decision.
- Profile updates: name, email, avatar path, profile completion flag — with sanitization delegated to `utils/sanitizer.py` and image handling delegated to `utils/uploads`.
- Creating users: both manual admin creation and approval-based provisioning (both set `role='user'` and `boolean_flag_indicating_if_user_profile_has_been_completed=False`).
- Blacklist toggling.
- Role escalation prevention: only `'user'` role can be assigned by admin operations. This is enforced at the service level.

#### `services/api_key_service.py`

API key lifecycle management. Responsibilities:

- Encrypting and saving new keys.
- Toggling active status.
- Reordering keys (bulk `order` field update for all keys belonging to the user).
- Deleting keys.

#### `services/access_request_service.py`

Onboarding pipeline. Responsibilities:

- Creating new access requests from public form submissions.
- Processing admin approvals: generates a secure random password, delegates account creation to the user service, updates the `AccessRequest` record with the new user's ID.
- Processing rejections (status update only) and deletions (permanent removal).

#### `services/__init__.py`

Package initializer.

---

### `utils/` — Shared Utilities

#### `utils/sanitizer.py`

The single source of truth for all `bleach`-based HTML/string sanitization. Applied at exactly two points in the application: comment text creation and user profile field updates. No other module imports `bleach` directly.

#### `utils/encryption.py`

Fernet-based symmetric encryption and decryption for API key storage. Derives the encryption key from the application's `SECRET_KEY`. Used by the API key model and decrypted only within the AI service layer at evaluation time.

#### `utils/uploads.py`

Validates and stores user-uploaded profile images. Enforces allowed file types (PNG, JPG, GIF, WEBP) and file size limits. Generates the canonical filename (`<username>-profile-photo.<ext>`), which causes automatic overwrite of the previous image on re-upload.

#### `utils/decorators.py`

View-level RBAC guards. Provides role-requirement decorators for admin and AI routes. Both evaluate the user's role field and redirect or abort unauthorized requests.

#### `utils/db_init.py`

Database initialization utility called at app startup. Creates tables if absent, runs lightweight schema migrations for new columns, and invokes the seeder on a fresh database.

#### `utils/db_seeder.py`

Parses seed data from the `data/` directory and populates: `Country`, `Sphere`, `Question`, `Tool`, `ToolCriteria`, and shell `AIAnalysis` records. Also seeds initial user accounts from `data/users.json`. Runs only on a fresh database — never on an existing one.

#### `utils/__init__.py`

Package initializer.

---

### `routes/` — Flask Blueprints (Controllers)

Routes are thin. They parse request parameters, call the appropriate service, and return a response (template render, redirect, or JSON). No business logic lives in routes.

#### `routes/public.py`

Blueprint prefix: (none — root).
Handles all unauthenticated public pages and the contact form submission. Contains the `/healthz` health check endpoint.

#### `routes/auth.py`

Blueprint prefix: (none — root).
Handles `GET|POST /login` and `GET /logout`. Delegates credential verification to the user service. On successful login, checks the profile completion flag and redirects to either `/onboarding/profile` or the role-appropriate dashboard.

#### `routes/onboarding.py`

Blueprint prefix: `/onboarding`.
Handles the shared profile page (`GET|POST /onboarding/profile`) accessible by all authenticated roles. On POST, delegates profile updates to the user service and image storage to the upload utility. On first-time profile submission, sets the profile completion flag and redirects to the role dashboard.

#### `routes/dashboard.py`

Blueprint prefix: (none — root).
Handles the standard user dashboard (`GET /regular_user/<username>/dashboard`) and the aggregated tools library (`GET /regular_user/<username>/tools`). Both routes validate that the `<username>` in the URL matches the authenticated user (403 if mismatched). Redirects admin and AI users to their respective dashboards if they land here.

#### `routes/analysis.py`

Blueprint prefix: (none — root).
The most traffic-heavy blueprint. Handles:

- Analysis creation (`POST /analysis/create`, returns JSON), editing (`POST /analysis/<id>/edit`), and deletion (`POST /analysis/<id>/delete`, returns JSON).
- The workspace shell view (`GET /regular_user/<username>/analysis/<id>`) and all tab partial rendering (`GET /regular_user/<username>/analysis/<id>/tab/<tab_name>`).
- Legacy workspace routes (`GET /analysis/<id>` and `GET /analysis/<id>/tab/<tab_name>`) are registered as secondary routes for admin panel link compatibility only.
- The AJAX answer-save endpoint (`POST /analysis/<id>/answer`) — the most frequently called route in the app.
- Comment creation and deletion (with authorization enforcement).
- AI context retrieval for question popups.

#### `routes/admin.py`

Blueprint prefix: `/admin`.
Gated by the admin role decorator. Handles all admin operations: dashboard metrics, user management (create, edit, delete, blacklist), access request review (approve, reject, delete), and comment moderation. The AI service layer is never imported here.

#### `routes/ai_dashboard.py`

Blueprint prefix: `/ai`.
Gated by the AI role decorator. Handles: AI dashboard, evaluation triggering (spawns a background `ThreadPoolExecutor` task), status polling, AI analysis view, and API key management (save, toggle, reorder, delete).

#### `routes/__init__.py`

Package initializer.

---

### `templates/` — Jinja2 HTML Templates

#### `templates/base.html`

The root layout template. Inherited by all authenticated user pages. Provides: CSS setup, Alpine.js initialization with global toast state, flash message rendering, and shared inline scripts for form submission guards and modal key handling.

#### `templates/landing.html`

Standalone marketing homepage. Inherits nothing from `base.html`. Contains its own full `<style>` block. Loads Three.js and GSAP via CDN for homepage animations.

#### `templates/includes/`

Shared partials included across authenticated pages.

- `nav.html` — Navigation bar with Alpine.js-driven mobile menu, user dropdown, and active-link highlighting. Renders role-appropriate navigation links. All roles use `url_for('onboarding.profile')` for the profile link. Logout is a plain `<a>` to `GET /logout`.
- `footer.html` — Site-wide footer.
- `partials/country_options.html` — Static hardcoded `<option>` elements for all ~200 countries. Used in both the analysis creation form and the AI evaluation trigger form. This is the sole source of country dropdown data — the `Country` DB table does not drive any UI dropdown.

#### `templates/public/`

Pages accessible without authentication.

- `login.html` — Login form with Alpine.js double-submit guard.
- `contact.html` — Access Request form. Posts to the public contact route.
- `about.html`, `how_it_works.html`, `faq.html` — Static educational content. Do not modify.
- `404.html`, `500.html` — Error pages rendered by `core/error_handlers.py`.

#### `templates/admin/`

Pages for `role='admin'`. These pages use `admin.css` and have no internal `<style>` blocks.

- `dashboard.html` — Aggregate metrics (user counts, pending requests, recent signups).
- `users.html` — User roster with client-side search filtering, inline edit modal, and create modal. Edit form action uses the pattern `/admin/users/<id>/edit`.
- `access_requests.html` — Request queue with async approve/reject/delete. On approval, credentials are injected into the DOM from the JSON response.
- `comments.html` — Global comment feed with async delete. Links to the originating analysis workspace for comments with a non-null `analysis_id`. Guards against null `analysis_id` before generating the link.

#### `templates/ai/`

Pages for `role='ai'`. These pages use `ai-user.css` and have no internal `<style>` blocks.

- `dashboard.html` — AI stats and analysis archive with delete and view actions.
- `analysis.html` — Country evaluation trigger. Polls the status endpoint after triggering. Redirects to the analysis view on `status='completed'`.
- `analysis_view.html` — Displays a completed AI analysis: all AI-assigned scores and reasoning text, organized by sphere.
- `api_keys.html` — API key manager with drag-to-reorder (SortableJS or equivalent), toggle, and delete. All key management actions use dynamic URL construction (not `url_for` with static key ID) since key IDs are runtime values.

#### `templates/shared/`

Templates accessible by more than one role.

- `profile.html` — Profile edit page for all authenticated roles (`user`, `admin`, `ai`). Accessible via `GET /onboarding/profile`. Form POSTs to `url_for('onboarding.profile')`. Back navigation link is role-aware: admin → admin dashboard, ai → AI dashboard, user → user dashboard.

#### `templates/user/`

Pages for `role='user'`.

- `dashboard.html` — User dashboard. Includes analysis create/edit/delete modals. All CRUD actions submit JSON and handle JSON responses. Displays activity stats and analysis archive.
- `dashboard_tools.html` — Aggregated triggered tools library across all of the user's analyses.

##### `templates/user/analysis/`

The core analysis workspace. The most complex section of the frontend.

- `index.html` — The analysis workspace shell. Does **not** render tab content directly. Contains:
  - The tab navigation bar.
  - An empty content area where tab partials are injected.
  - An inline IIFE JavaScript engine (see below).
  - Inline modal markup for the AI context popup and comments popup.

**Analysis Workspace Inline Engine** (embedded in `index.html`):

The workspace JavaScript engine is an IIFE embedded directly in `index.html` rather than an external `.js` file. This design decision is intentional: the engine requires direct access to Jinja-rendered context values (`ANALYSIS_ID`, `CSRF_TOKEN`, endpoint URL templates) at initialization time.

The inline engine is responsible for:

- Initializing constants from server-rendered Jinja values.
- Loading tab partial HTML via `fetch()` and injecting it into the content area.
- Maintaining a client-side tab cache (keyed by tab name). Cache entries for `results` and `tools` tabs are invalidated after every successful answer save.
- Wiring event listeners onto dynamically injected partial content after each tab load (answer radio inputs, AI context buttons, comment buttons, tool info buttons).
- Sending debounced AJAX POST requests to the answer endpoint and processing the `triggered_tools` response.
- Opening and populating the AI context modal and comments modal via their respective AJAX endpoints.

The engine does **not** own a persistent answer state between tab loads. Score computation for display is handled by partial-specific logic embedded in each partial's own inline script.

##### `templates/user/analysis/partials/`

Tab content partials. Each is a self-contained HTML fragment (no `<html>` or `<body>` tags) rendered server-side and injected into the workspace shell on tab switch.

- `questionnaire.html` — Renders all 9 sphere sections with question cards. Each card includes the 7-radio rating input, More Info button, Comments button, and AI Context button. Contains an inline script that pre-populates the live score display from the Jinja-rendered `answers_dict` on injection. Radio inputs are pre-selected only when the stored value is `1–7`; a value of `-1` means unanswered and no radio is selected.

- `results.html` — Renders summary cards, a sphere breakdown section, and a radar chart canvas. Contains an inline script that: reads the pre-serialized `radar_series` (list of plain dicts passed from the route), computes sphere scores using the λ formula, builds Chart.js datasets, renders the radar chart, and populates the aggregate index display. The `radar_series` data is pre-serialized in the route to plain dicts — ORM objects are not passed to this partial.

- `tools.html` — Renders all 28 tools. Triggered tools (IDs in `Analysis.triggered_tools`) receive a highlight style class. Un-triggered tools receive a muted style class. Each tool card has a More Info button.

---

### `static/` — Static Assets

#### `static/css/`

- `styles.css` — Global site-wide utility classes and shared component styles. Used by all pages.
- `admin.css` — All styles for the admin panel. Admin templates have no internal `<style>` blocks.
- `ai-user.css` — All styles for the AI user panel. AI templates have no internal `<style>` blocks.

#### `static/js/`

No application JavaScript files exist here. All analysis workspace JavaScript is embedded inline in `templates/user/analysis/index.html`. All other page interactivity is handled by Alpine.js declared inline on elements.

#### `static/assets/`

Image and media assets organized by page area: `/homeImages`, `/aboutPage`, `/contactPage`, `/resources-page`, `/how-it-works`, `/general`.

#### `static/uploads/`

- `profiles/` — Local disk storage for user-uploaded profile pictures. Files follow the naming convention `<username>-profile-photo.<ext>`. New uploads overwrite the old file automatically — no metadata tracking.

---

### `data/` — Seed Data (Read-Only)

JSON files that bootstrap the application database on first run. Do not modify any file in this directory.

| File | Contents |
|------|----------|
| `countries.json` | ~200 sovereign countries with codes and display names |
| `spheres.json` | 9 sphere definitions with names, labels, and ordering |
| `questionnaire.json` | All questions across all spheres with type, importance, scale labels, help info |
| `criteria.json` | `ToolCriteria` threshold definitions linking tools to spheres |
| `tools.json` | All 28 anti-corruption tools with titles, descriptions, and HTML content |
| `users.json` | Default seed user accounts (admin + optional sample users) |

---

### `spec/` — Technical Specifications (This Directory)

Living documentation for the project. Update these files when the application design changes.

| File | Contents |
|------|----------|
| `constitution.md` | Core rules, architecture standards, domain mechanics, role definitions, invariant rules |
| `database-schema.md` | Complete field-level database schema for all models |
| `folder-structure.md` | This file — directory layout, routing system, and file responsibilities |
| `workflow.md` | All user workflows and system processes with step-by-step detail |
