# DSTAIR — Project Constitution

---

Living engineering standards for the DSTAIR institutional analysis platform.

**Application Name**: DSTAIR (Decision Support Tool to Analyze Institutional Reform)
**Purpose**: A web-based diagnostic tool for locating the propensity for corruption in a country's institutions and recommending state-of-the-art anti-corruption policies to address specific institutional pathologies.

---

> **Finalized Public Pages**: The landing page, about, how-it-works, resources, and FAQ pages are finalized and locked. Do not modify any template, style, or logic in these pages under any circumstances.

> **Data Directory**: The `data/` folder in the root directory contains seed data mandatory for application function. Do not modify any file in this directory.

---

## Programming Rules

- Backend: Python with Flask.
- Extensions: Flask ecosystem (Flask-Login, Flask-Migrate, Flask-WTF, Flask-Limiter).
- Entry Point: A **single `run.py`** is the only valid application entry point. It uses Waitress (production) or the Flask dev server (development via `--dev` flag). `wsgi.py` must not exist.
- If a code change affects other parts of the project, those related parts must be reviewed and updated accordingly.
- The `README.md` must be updated whenever a significant feature is added or changed.

---

## Core Architecture Standards

### Layered Architecture (Controller-Service-Model)

| Layer | Location | Responsibility |
|-------|----------|----------------|

| Controllers | `routes/` | Blueprint HTTP routing, input parsing, session handling. Routes must remain thin — no business logic. |
| Business Logic | `services/` | All core application logic, scoring orchestration, external API calls, threading. |
| Data Models | `models/` | SQLAlchemy models following Active Record pattern. All DB interaction lives inside model classes. No separate repository layer. |
| Infrastructure | `core/` & `utils/` | Shared error handlers, custom exceptions, decorators, encryption, sanitization, file uploads. |

> **Repository layer removed**: No repository files or imports may exist anywhere in the codebase. All DB queries live inside Model classes via `ActiveRecordMixin`.

### Styling & UI Architecture

- **Global Styles**: Site-wide, reusable styles belong in `static/css/styles.css`.
- **Page-Specific Styles**: CSS for a single page is defined in a `<style>` block in the `<head>` of that page's template.
  - **Exception**: Admin and AI pages use `admin.css` and `ai-user.css` respectively. These pages have no internal `<style>` blocks.
- **No Inline Styles**: `style="..."` attributes are strictly prohibited on all pages except the analysis workspace, where they are permitted only for dynamically computed values (e.g., chart widths, progress bar percentages).
- **Responsive Design**: Every component must function correctly on mobile. Mobile-first design is mandatory.
- **Modal Architecture**: All modals must use a standardized wrapper ensuring `max-h-[90vh]` height bounding and `overflow-y-auto` internal scrolling. Modal headers must be sticky.

### JavaScript Architecture

The frontend uses a two-tier JS strategy:

**Tier 1 — Alpine.js (inline, site-wide)**

Used for simple, self-contained UI states that do not require server context at initialization:

- Navigation dropdowns and mobile menu toggle.
- Modal open/close via boolean toggles.
- Form submission guards (preventing double-submits).
- Flash/toast message dismissal.

Declared inline via `x-data` on the relevant element. No Alpine.js component should perform AJAX or compute scores.

**Tier 2 — Analysis Workspace Engine (inline IIFE in `templates/user/analysis/index.html`)**

The analysis workspace requires direct access to server-rendered context values — specifically the analysis ID, CSRF token, and all endpoint URLs — at initialization time. For this reason, the workspace JavaScript engine is embedded as a self-contained IIFE (immediately invoked function expression) directly inside `index.html`, rather than in an external `.js` file.

This inline engine is responsible for:

- Initializing constants from Jinja-rendered values (`ANALYSIS_ID`, `CSRF_TOKEN`, endpoint URL templates).
- Debounced AJAX answer saves to the backend answer endpoint.
- Loading tab partial HTML via `fetch()` and injecting it into the content area.
- Client-side tab cache to avoid redundant network requests (invalidated on answer change).
- Wiring event listeners onto dynamically injected partial content after each tab load.
- Opening and populating the AI context modal and comments modal.

Score computation for display is performed by the partial templates themselves (using Jinja-rendered data for the results tab, and inline scripts in partials for real-time updates in the questionnaire tab). The workspace engine does not own a global answer state — it is stateless between tab loads.

**Tier 3 — Chart.js**

Loaded via CDN only on pages that render charts. Chart initialization scripts are embedded inline in the `results.html` partial, which is injected into the workspace on tab load.

> No external analysis JavaScript file exists. Inline scripts are the sole mechanism for analysis workspace behavior. This decision is intentional and must not be reversed — external JS files cannot easily access Jinja-rendered URL and ID context without additional complexity.

### Sanitization Policy

All user-generated string sanitization via `bleach` must go through `utils/sanitizer.py`. No direct `bleach` calls are permitted anywhere else.

Sanitization is applied at **exactly two entry points**:

1. **Comment text** — sanitized at the moment of creation before being stored.
2. **User profile fields** (name, display name) — sanitized at the point of profile update.

Do not sanitize IDs, country codes, numeric ratings, boolean flags, or any field that is not free-form user-authored text.

---

## 1. Domain Mechanics & Mathematical Model

### Definition & Objectives

DSTAIR provides a platform for analyzing the legitimacy of a country's institutional framework across nine governance spheres. It assists analysts in generating legitimacy scores, visualizing institutional weaknesses, and recommending from a suite of 28 state-of-the-art anti-corruption tools.

Corruption is defined as the use of public resources for private gain — a betrayal of the public trust. Legitimacy is a combined measure of the effectiveness of the rules comprising each sphere, the quality of rules the sphere generates, and uncontrollable exogenous factors.

### The Nine Spheres

DSTAIR separates government and society into nine institutional spheres:

| Sphere | Description |
|--------|-------------|
| **Constitution** | Basic laws and principles of the state; institutions that create, maintain, and modify it. |
| **Legislature** | Elected body creating laws; reflects citizenry and quality of legislation. |
| **Executive** | Carries out laws; diplomatic representation, armed forces, public administration management. |
| **Public Administration** | Non-political public employees delivering services (police, hospitals, tax, etc.). |
| **Courts** | Rules for justice delivery; impartiality of judges and fairness of application. |
| **Political Parties** | Campaign financing, influence over the political system, and commitment to fair competition. |
| **Civil Society** | Non-governmental organizations communicating citizen demands between elections. |
| **Economy** | Rules for production and distribution of goods and services. |
| **Media** | Publicly and privately owned outlets providing accurate, reliable information. |

A sphere may be omitted entirely by leaving all its answers at `-1` (unanswered/N/A) — this does not break system functionality.

### Question Types

Each question has a preset importance level and belongs to one of three types:

| Type | Description | Importance Levels |
|------|-------------|-------------------|
| **Metarules** | Quality of institutions that create the sphere | low=1, medium=2, high=3 |
| **Rules of Operation** | Strength of the organizing institutions themselves | low=1, medium=2, high=3 |
| **Exogenous Factors** | Power of outside forces to disrupt or strengthen spheres | low=1, medium=2, high=3 |

### Scoring Formula

**UI Scale**: Users rate each question using **7 radio inputs** (values 1 through 7). Questions start with a stored value of `-1` (unanswered/N/A). A `-1` value is excluded entirely from all calculations — it contributes nothing to the numerator or denominator of any formula. Only values `1–7` participate in scoring.

**No remapping**: Ratings are used on the raw 1–7 scale. There is no 1–10 mapping.

### Mathematical Model

**Score display is computed exclusively on the frontend in JavaScript.** The backend computes scores internally only for `ToolCriteria` evaluation and never stores or returns them.

For each sphere `j`, the legitimacy score `A(j)` is:

```
A(j) = Σᵢ(aᵢⱼ × rᵢⱼ) / (7 × Σᵢ aᵢⱼ)
```

Where the sum is over answered questions only (sentinel `-1` excluded).

**Variable definitions**:

| Symbol | Meaning |
|--------|---------|
| `rᵢⱼ` | Raw 1–7 rating for question `i` in sphere `j` |
| `aᵢⱼ` | Importance weight for question `i` in sphere `j` (1=LOW, 2=MEDIUM, 3=HIGH) |
| `7` | λ_max — maximum possible rating, used as normalizing constant. Ensures `A(j)` is bounded 0–1. |
| `i` | Index over answered questions within a sphere |
| `j` | Index over spheres (9 total) |

**Aggregate index**: mean of `A(j)` across all spheres that have at least one answered question.

> The full formula includes a cross-sphere interaction term `S_j` and attenuation factor `α`. Currently `α = 0`, so the formula reduces to `A(j) = Σ(a×r) / (7×Σa)`. The architecture supports enabling cross-sphere effects in future versions.

### Tool Triggers

28 anti-corruption tools each have `ToolCriteria` records defining a minimum score threshold per sphere. A tool triggers when **all** of its criteria conditions are satisfied simultaneously (AND logic).

**Condition for each sphere criterion**:
```
satisfied = (A(j) >= min_score_threshold) OR (A(j) == -1)
```

- `A(j) >= threshold`: sphere score meets or exceeds the threshold → condition satisfied
- `A(j) == -1`: sphere has no answered questions → condition automatically satisfied

A tool triggers only when every criterion condition is satisfied.

Tool triggering is recalculated by the **backend** `AnalysisService` on every answer save. It evaluates all `ToolCriteria` using the raw 1–7 formula and returns only the resulting list of triggered tool IDs. The frontend uses this list to style triggered tools distinctly.

---

## 2. The Public (Unauthenticated) Experience

**Role**: General internet visitors and potential institutional clients.
**Permissions**: Read public content, submit access requests. Cannot view analyses, tools, or any authenticated user data.

### Pages

| Page | Route | Description |
|------|-------|-------------|
| Landing | `/` | Marketing homepage. |
| About | `/about` | Platform overview. |
| How It Works | `/how-it-works` | Methodology explanation. |
| Resources | `/resources` | Reference materials. |
| FAQ | `/faq` | Frequently asked questions. |
| Contact / Access Request | `/contact` | Access Request Form. Submission queues a `pending` `AccessRequest` record. Does NOT create a user account. |
| Login | `/login` | Authentication gateway. Blacklisted users receive a generic "contact administrator" message. |

---

## 3. The Normal User Experience

**Role**: Standard analyst (researchers, policymakers).
**Permissions**: Create and view personal analyses, compare with other users for the same country, view triggered tools, post and view comments.
**Restrictions**: Cannot view `ToolCriteria` thresholds or backend trigger logic.

### Pages & Workflows

#### Profile Page (`/onboarding/profile`)

Accessible to all authenticated roles (user, admin, AI user). See §10 (Shared Profile) for the multi-role design.

- Updatable fields: Full name, email, profile image (PNG, JPG, GIF, WEBP).
- Images stored at `static/uploads/profiles/<username>-profile-photo.<ext>`. New uploads overwrite the old file automatically.
- **Cannot change**: username, password.

#### User Dashboard (`/regular_user/<username>/dashboard`)

- Create new analyses (assign title + country).
- View activity statistics: total analyses, unique countries, triggered tools count.
- Browse an archive of all past analyses with Edit and Delete actions.
- Browse aggregated triggered tools across all analyses at `/regular_user/<username>/tools`.

#### Analysis Workspace (`/regular_user/<username>/analysis/<id>`)

A 3-tab interface. All tab content is loaded dynamically via AJAX — the workspace shell (`index.html`) never renders tab content directly. Scores are computed in the browser on every render.

---

**Tab 1 — Questionnaire** (`/regular_user/<username>/analysis/<id>/tab/questionnaire`)

- 9 sphere sections, each containing 12–15 questions.
- Each question offers 7 radio inputs (1–7). The stored default is `-1` (unanswered/N/A) — no radio is pre-selected on initial render.
- Every answer click triggers an immediate AJAX POST to `/analysis/<id>/answer`.
- A live score panel updates in real-time for all spheres after each answer, using the frontend scoring engine.

Each question card has three action buttons. Hovering any button shows a tooltip.

| Button | Action |
|--------|--------|
| **More Info** | Opens popup showing `Question.help_info`. |
| **Comments** | Opens popup showing all human-authored comments for this question. AI comments are strictly excluded. |
| **AI Context** | Opens popup showing the AI-assigned score and reasoning for this question for the current country. If no completed `AIAnalysis` exists for this country, displays: "AI analysis is currently not available for this country." |

---

**Tab 2 — Results** (`/regular_user/<username>/analysis/<id>/tab/results`)

- Summary cards: country, aggregate legitimacy index, questions answered, number of comparison series.
- **Spider / Radar Chart**: Multi-series comparison.

Spider chart composition (deterministic, in order):

| Series | Position | Condition |
|--------|----------|-----------|
| Current analysis | Always index 0 | Always included |
| AI baseline | Index 1 | If a `completed` `AIAnalysis` exists for the country |
| Other users' analyses | Indices 2–5 | Up to 4 most recently updated `Analysis` records where `country` matches AND `user_id ≠ current user`, ordered by `updated_at` DESC |

**Maximum series**: 6 (current + AI baseline + 4 others). Gracefully degrades to fewer when unavailable. Minimum: 1 series (current analysis only).

Each series is rendered on the radar chart with a distinct color. A legend below the chart identifies each series by title.

- **Sphere breakdown**: Progress bars showing answered/total questions per sphere.

---

**Tab 3 — Tools** (`/regular_user/<username>/analysis/<id>/tab/tools`)

- Displays all 28 anti-corruption tools.
- **Triggered tools** (IDs present in `Analysis.triggered_tools`) are rendered in a distinct highlight color.
- **Un-triggered tools** are rendered in a neutral/muted style.
- **More Info** button on each tool opens a popup with the tool's full `content` (HTML).

---

## 4. The AI User Experience

**Role**: Automated analysis agent using LLMs to evaluate countries.
**Permissions**: Manage API keys, trigger AI evaluations, view and delete own AI analyses.
**Constraints**: Only ONE analysis record per country. Triggering a new evaluation for an existing country overwrites the previous record entirely.

### Supported LLM Providers

The backend supports all five providers through a common abstraction layer. Provider-specific logic (endpoint, authentication format, request structure, response parsing) is fully encapsulated within the AI service layer. No provider-specific code leaks to routes or other services.

| Provider | Key Identifier |
|----------|---------------|
| Groq | `groq` |
| OpenAI | `openai` |
| Anthropic (Claude) | `claude` |
| Google (Gemini) | `gemini` |
| OpenRouter | `openrouter` |

All five providers must be implemented in the AI service. Provider selection is config-driven (user's API key order and active status). The system must be able to switch providers at runtime based on key availability without any code changes.

### Pages & Workflows

#### AI Dashboard (`/ai/dashboard`)
- Statistics: total evaluations, completed, in-progress.
- Archive of all country analyses with Delete and View actions.

#### AI Analysis Trigger (`/ai/analysis`)
- Select a country from the static dropdown.
- Click "Generate AI Analysis" to trigger evaluation.
- The UI polls `/ai/analysis/<id>/status` for completion.
- Navigation to results is only allowed after `status='completed'`.
- On `status='error'`, a failure message is shown. No partial data is saved.

#### AI Analysis View (`/ai/analysis/<id>`)
- Displays the completed AI analysis: all scores and AI-generated reasoning per question.
- Organized by sphere. Accessible only when `status='completed'`.

#### API Key Manager (`/ai/api-keys`)
- Add keys by selecting a provider and entering a key string.
- Drag to reorder execution priority. Topmost active key is tried first.
- Toggle individual keys active/inactive.
- Delete keys.
- **Fallback logic**: Keys are tried in order. If one fails, the next active key is tried. If all fail, the evaluation aborts and `status='error'` is set.

---

## 5. The Admin Experience

**Role**: Platform administrator with full access control and moderation.
**Constraint**: Only ONE admin account exists in the system. Creating a second admin is architecturally prevented — no code path may allow it.
**Permissions**: Full read/write on normal user (`role='user'`) accounts, access requests, and comments.
**Hard Restriction**: Zero access to AI-user accounts, their API keys, or any AI evaluation data. The AI service layer must never be imported in any admin route or admin-related service.

### Pages & Workflows

#### Admin Dashboard (`/admin/dashboard`)
- High-level metrics: total users by role, pending access request count, recent signups.

#### Access Requests (`/admin/access-requests`)
- Queue of all access requests with status filter.
- **Approve**: Creates a new `role='user'` account with a secure random password. Credentials are displayed in the Admin UI. Admin manually shares them. No email is sent.
- **Reject**: Sets `status='rejected'`. No account is created.
- **Delete**: Permanently removes the `AccessRequest` record.

#### User Management (`/admin/users`)
- Full list of `role='user'` accounts (AI users are never shown).
- **Create**: Provision a new user account manually.
- **Edit**: Update full name and email.
- **Blacklist / Unblacklist**: Toggle account active status.
- **Delete**: Permanently remove a user account. Admin cannot delete their own account.
- Role assignment is fixed at `'user'` for all admin-created accounts. Admin cannot assign `'admin'` or `'ai'` roles.

#### Comment Moderation (`/admin/comments`)
- Global feed of all user-authored comments across all questions and analyses.
- Admin can delete any comment regardless of author.

---

## 6. Design System & Aesthetics

**Core Identity**: "Authoritative, International, and Analytical."

The application must feel like a high-tier policy instrument — on par with tools used by the UN, World Bank, or leading research institutes. It must inspire trust, neutrality, and academic credibility.

- **Zero tolerance** for: misaligned elements, inconsistent spacing, clipping text, poor contrast ratios.
- All layouts must be pristine and pixel-perfect across all screen sizes — especially mobile.
- No playful, startup-style, or consumer-grade UI patterns.
- Every UI component must be designed for flawless mobile rendering.

---

## 7. Invariant Rules

The following rules are absolute. They must never be violated under any circumstances.

| # | Rule |
|---|------|
| 1 | **Single admin**: Exactly one admin account exists. Any code path that could create a second admin is prohibited. |
| 2 | **AI isolation**: Admins have zero visibility into or control over AI-user accounts or evaluations. The AI service layer must never be imported in admin-scoped code. |
| 3 | **Frontend-only score display**: Scores are computed and displayed exclusively by the frontend JavaScript. The backend answer endpoint returns only `triggered_tools`. It never returns or stores scores. |
| 4 | **No Analysis status**: The `Analysis` model has no `status` field. All analyses are permanently editable. |
| 5 | **Static country dropdown**: Country dropdowns are static hardcoded HTML (`templates/includes/partials/country_options.html`). The `Country` DB table exists only for `AIAnalysis` FK indexing. |
| 6 | **Single entry point**: `run.py` is the only valid application entry point. |
| 7 | **Centralized sanitization**: `bleach` is used only via `utils/sanitizer.py`, applied only at comment creation and profile field updates. |
| 8 | **No repository layer**: All DB queries live inside Model classes. No repository files or imports exist. |
| 9 | **Provider abstraction**: All LLM provider-specific logic is fully encapsulated in the AI service layer. No provider details (endpoint URLs, auth formats, response schemas) leak to routes or other services. |
| 10 | **Inline analysis engine**: The analysis workspace JavaScript engine is embedded inline in `templates/user/analysis/index.html`. No external `.js` file handles analysis workspace behavior. |
