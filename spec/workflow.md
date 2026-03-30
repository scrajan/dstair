# DSTAIR Workflows & Processes

This document defines all primary user journeys and system processes. Each workflow maps precisely to the database schema, routing system, and folder structure.

---

## 1. Onboarding & Access Request

### 1a. Public Access Request Submission

1. Visitor navigates to `/contact`.
2. Fills in and submits the Access Request Form (Name, Email, Organization, Message).
3. The access request service validates input and creates an `AccessRequest` record with `status='pending'` and `created_at=now`.
4. A success flash message confirms the submission. No account is created. No email is sent.

### 1b. Admin Approves Request

1. Admin navigates to `/admin/access-requests`.
2. Reviews the pending request queue. Clicks **Approve** on a request.
3. The frontend sends an async POST to `/admin/access-requests/<id>/approve`.
4. The access request service generates a cryptographically secure random password.
5. The user service creates a new `User` record: `role='user'`, `is_active=True`, `boolean_flag_indicating_if_user_profile_has_been_completed=False`.
6. `AccessRequest.status` is set to `'approved'`, `reviewed_at=now`, and `created_user_id` is set to the new user's ID.
7. The backend returns the new `username` and generated `password` as JSON.
8. The Admin UI injects the credentials into the DOM (no page reload). Admin manually shares them with the user.

### 1c. Admin Rejects Request

1. Admin clicks **Reject** on a pending request.
2. Async POST is sent to `/admin/access-requests/<id>/reject`.
3. `AccessRequest.status` is set to `'rejected'`, `reviewed_at=now`.
4. No user account is created. No notification is sent.

### 1d. Admin Deletes Request

1. Admin clicks **Delete** on any request (any status).
2. POST is sent to `/admin/access-requests/<id>/delete`.
3. The `AccessRequest` record is permanently removed from the database.
4. The row is removed from the UI.

### 1e. First Login & Profile Completion (New User)

1. New user navigates to `/login` and submits their credentials.
2. On successful authentication, the server checks `boolean_flag_indicating_if_user_profile_has_been_completed` on the `User` record.
3. If `False` (first login): user is redirected to `/onboarding/profile` to complete their profile before proceeding.
4. After the user submits their profile (name, email, and optionally a profile picture), `boolean_flag_indicating_if_user_profile_has_been_completed` is set to `True`.
5. User is redirected to `/regular_user/<username>/dashboard`. On all subsequent logins, this check is bypassed and the user goes directly to their role dashboard.

---

## 2. Authentication

### 2a. Login

1. User submits credentials (username + password) via POST to `/login`.
2. The user service looks up the user by username and verifies the password hash.
3. If `boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted` is `False` (blacklisted): login is denied with a generic "contact administrator" message. No account details are revealed.
4. On success: Flask-Login creates the session. User is redirected based on role and profile completion state:
   - If profile not yet completed: → `/onboarding/profile` (regardless of role)
   - `'user'` with completed profile → `/regular_user/<username>/dashboard`
   - `'admin'` with completed profile → `/admin/dashboard`
   - `'ai'` with completed profile → `/ai/dashboard`

### 2b. Logout

1. User accesses `GET /logout`.
2. Flask-Login clears the session.
3. User is redirected to `/login`.

---

## 3. Profile Update (All Roles)

The `/onboarding/profile` route serves all authenticated roles: `user`, `admin`, and `ai`. The template rendered is `templates/shared/profile.html`. The back navigation link shown is role-aware (admin → admin dashboard, ai → AI dashboard, user → user dashboard).

1. User navigates to `GET /onboarding/profile`. The page is populated with current `User` record data.
2. User updates any of: full name, email, profile image.
3. User submits the form via `POST /onboarding/profile`.
4. The user service processes the update:
   - Full name and email fields are sanitized via `utils/sanitizer.py`.
   - If a new image is uploaded, the upload utility validates file type (PNG, JPG, GIF, WEBP) and file size.
   - Valid image is saved to `static/uploads/profiles/<username>-profile-photo.<ext>`. If a previous image exists at that path, it is overwritten automatically.
   - `User` record is updated in the database.
   - If `boolean_flag_indicating_if_user_profile_has_been_completed` is `False`, it is set to `True` and the user is redirected to their role dashboard.
   - If already `True`, a flash success message is shown and the user remains on the profile page.

**Constraints**: Username and password cannot be changed through this workflow.

---

## 4. Institutional Analysis (Manual User)

### 4a. Create Analysis

1. Authenticated user (`role='user'`) is on `/regular_user/<username>/dashboard`.
2. Clicks "New Analysis". A modal prompts for: analysis title and country (from static country dropdown).
3. Form data is submitted as JSON via POST to `/analysis/create`.
4. The analysis service creates a new `Analysis` record:
   - `answers` = pre-populated skeleton built by loading all `Sphere` and `Question` records from the database. Structure: `{ "SPHERE_NAME": { "question_id": -1, ... }, ... }`. Every sphere name and every question ID is present as a key. All values are initialized to `-1` (unanswered/N/A).
   - `triggered_tools = []` (empty list)
   - `country` = submitted country string (plain string, not FK)
   - `title` = submitted title
5. The backend returns JSON with the new analysis ID and redirect URL. The browser navigates to `/regular_user/<username>/analysis/<id>` with the Questionnaire tab active.

### 4b. Answer a Question (Real-Time Save)

1. User selects a rating (1–7) on a question radio input in the Questionnaire tab.
2. An AJAX POST is sent immediately (debounced) to `/analysis/<id>/answer` (CSRF-protected) with: sphere name, question ID, rating value, and client timestamp.
3. The analysis service performs an atomic update under pessimistic locking:
   - Checks `last_sync_timestamp` to reject stale out-of-order requests.
   - Updates the `answers` JSON: sets `answers["SPHERE_NAME"]["question_id"] = rating` (overwrites the existing `-1` sentinel with the new 1–7 value). The key always exists — the skeleton guarantees it.
   - Internally evaluates all `ToolCriteria` using the raw 1–7 formula: `A(j) = Σ(a×r) / (7×Σa)`. A criterion is satisfied when `A(j) >= min_score_threshold` OR the sphere is unanswered.
   - Updates `triggered_tools`, `last_sync_timestamp`, and `updated_at`.
   - Returns `{ "success": true, "triggered_tools": [1, 5, 12, ...] }`.
4. The browser workspace engine receives the response and invalidates the results and tools tab cache entries, ensuring the next tab switch fetches fresh data.

> The backend never computes or returns scores. It returns only `triggered_tools`.

### 4c. Switch Tabs

1. User clicks a tab button (Questionnaire, Results, or Tools).
2. The workspace engine checks its client-side tab cache. If the tab content is cached and not invalidated, it is rendered from cache immediately.
3. If not cached, the engine sends a GET to `/regular_user/<username>/analysis/<id>/tab/<tab_name>`.
4. The server renders the requested partial template with the latest data from the database and returns it as HTML.
5. The engine injects the returned HTML into the content area and wires event listeners onto the newly injected content.
6. The rendered partial may contain its own inline script (e.g., `results.html` initializes the radar chart after injection).

### 4d. Edit Analysis Metadata

1. User clicks "Edit" on an analysis from the dashboard.
2. A modal prompts for updated title and/or notes.
3. Data is submitted as JSON via POST to `/analysis/<id>/edit`.
4. The analysis service updates `title` and/or `notes` on the `Analysis` record. Country is not editable.
5. A success JSON response is returned. The dashboard updates the title in the UI without a full page reload.

### 4e. Delete Analysis

1. User clicks "Delete" on an analysis from the dashboard archive.
2. A confirmation modal is displayed.
3. On confirm, a POST is sent to `/analysis/<id>/delete`.
4. The analysis service deletes the `Analysis` record. All `Comment` records where `analysis_id` matches are also deleted via cascade.
5. A success JSON response is returned. The browser reloads the dashboard. The deleted analysis no longer appears in the archive.

---

## 5. Comment Workflow

### 5a. Post a Comment

1. User clicks the **Comments** button on a question card in the Questionnaire tab.
2. A modal opens showing all existing human-authored comments for that question (sorted by `created_at` ascending). AI comments are never shown here.
3. User types a comment and submits via POST to `/analysis/question/<qid>/comment`.
4. Request body includes: comment text and optionally the current `analysis_id`.
5. The analysis service creates a `Comment` record:
   - `question_id` = the target question's ID
   - `analysis_id` = the current analysis ID if provided, or `null` if no analysis context
   - `user_display` = current user's username at time of writing
   - `text` = sanitized via `utils/sanitizer.py`
   - `created_at` = now (UTC)
6. The backend returns the new comment as JSON. The new comment appears in the modal immediately without a page reload.

### 5b. Delete Comment (Author or Admin — via Analysis Page)

1. Comment author (or admin) clicks the delete icon on a comment in the modal.
2. A DELETE request is sent to `/analysis/question/<qid>/comment/<cid>/delete`.
3. The analysis service verifies the requester is the comment author (matched by username) or has admin role. Unauthorized deletion is rejected with a 403 response.
4. The `Comment` record is deleted from the database.
5. The comment row is removed from the modal via DOM manipulation.

### 5c. Delete Comment (Admin — via Admin Panel)

1. Admin navigates to `/admin/comments`.
2. A global feed of all user-authored comments is displayed (across all questions and analyses, sorted by most recent).
3. For comments with a non-null `analysis_id`, a link is shown to the original analysis workspace.
4. Admin clicks **Delete** on any comment.
5. A DELETE request is sent to `/analysis/question/<qid>/comment/<cid>/delete`.
6. The `Comment` record is deleted. The row fades out from the admin table.

---

## 6. Tool Browsing (Analysis → Tools Tab)

1. User navigates to the Tools tab of an analysis workspace (via tab click or direct URL `/regular_user/<username>/analysis/<id>/tab/tools`).
2. The server renders the `tools.html` partial with:
   - The full ordered list of all 28 `Tool` records.
   - The current `Analysis.triggered_tools` list.
3. The partial renders triggered tools (those whose ID is in `triggered_tools`) with a distinct highlight style.
4. Un-triggered tools are rendered in a neutral/muted style.
5. User clicks **More Info** on any tool.
6. A modal opens displaying the tool's full `content` field (HTML rendered safely).

---

## 7. Admin User Management

### 7a. View Users

1. Admin navigates to `/admin/users`.
2. The user service returns all users where `role='user'`. AI-role users are never included.
3. Admin can search/filter by username or email using the client-side search input.

### 7b. Create User (Manual)

1. Admin clicks **Create User**.
2. A modal prompts for: username, full name, email, password.
3. Form is submitted via POST to `/admin/users/create`.
4. The user service validates for username/email uniqueness, hashes the password, and creates the `User` record with `role='user'`, `is_active=True`, and `boolean_flag_indicating_if_user_profile_has_been_completed=False`.
5. The new user appears in the user list immediately.

### 7c. Edit User

1. Admin clicks **Edit** on a user row.
2. A modal displays current full name and email.
3. Admin updates fields and submits via POST to `/admin/users/<id>/edit`.
4. The user service updates the user record. Role field is not exposed in this form and cannot be changed via this route.

### 7d. Toggle Blacklist

1. Admin clicks **Blacklist** (or **Unblacklist**) on a user row.
2. A POST is sent to `/admin/users/<id>/blacklist`.
3. The user service toggles `boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted`.
4. A blacklisted user cannot log in. If already logged in, their session is invalidated on the next authenticated request (Flask-Login `is_active` check).

### 7e. Delete User

1. Admin clicks **Delete** on a user row.
2. A confirmation prompt is displayed.
3. On confirm, a POST is sent to `/admin/users/<id>/delete`.
4. The user service verifies the target is not the admin's own account. If so, deletion is rejected.
5. The `User` record is permanently deleted. The user row is removed from the list.

---

## 8. API Key Management (AI User)

### 8a. Add API Key

1. AI user navigates to `/ai/api-keys`.
2. Clicks the **+** button for a provider.
3. Selects a provider from the dropdown: `groq`, `openai`, `claude`, `gemini`, or `openrouter`.
4. Enters the API key string.
5. Form is submitted via POST to `/ai/api-keys/save`.
6. The API key service encrypts the key via the encryption utility (Fernet) and saves a new `APIKey` record with `is_active=True` and `order` set to the end of the existing list.
7. New key appears in the list with provider label, masked key value, active status, and drag handle.

### 8b. Toggle Key Active/Inactive

1. AI user clicks the toggle switch on a key row.
2. POST is sent to `/ai/api-keys/<id>/toggle`.
3. The API key service flips `is_active` on the `APIKey` record.
4. Inactive keys are visually grayed out. They are skipped entirely during provider cascade at evaluation time.

### 8c. Reorder Keys

1. AI user drags a key row to a new position in the list.
2. On drop, a POST is sent to `/ai/api-keys/reorder` with the full ordered list of key IDs.
3. The API key service performs a bulk update of the `order` field for all `APIKey` records belonging to this user.
4. The provider cascade will follow the updated order on the next evaluation.

### 8d. Delete Key

1. AI user clicks **Delete** on a key row.
2. A DELETE request is sent to `/ai/api-keys/<id>/delete`.
3. The API key service deletes the `APIKey` record.
4. The key row is removed from the UI.

---

## 9. AI Country Evaluation

1. **Trigger**: AI user navigates to `/ai/analysis`, selects a country from the static dropdown, and clicks "Generate AI Analysis".

2. **Pre-check**: The AI service checks if an `AIAnalysis` record already exists for the country.
   - If it exists: the record is reset in-place — `status='in_progress'`, `ai_scores_for_all_questions=null`, `ai_comments_for_all_questions=null`.
   - If it does not exist: a new `AIAnalysis` record is created with `status='in_progress'`.

3. **Background execution**: The route spawns an async background task via `ThreadPoolExecutor`. The HTTP request returns immediately with the analysis `id`. The frontend begins polling.

4. **Provider resolution**: The AI service retrieves the user's `APIKey` records, sorted by `order` ascending, filtered to `is_active=True`. Keys are decrypted via the encryption utility at resolution time.

5. **Prompt construction**: The AI service loads all `Sphere` and `Question` records. A structured prompt is constructed containing all questions across all 9 spheres, including each question's answer scale (1–7 options with min/max labels) and type classification.

6. **Concurrent LLM requests**: The AI service dispatches concurrent requests to the selected provider — one per sphere — to minimize total evaluation time.

7. **Response validation**: Each provider response must conform to the expected JSON structure: `{ "question_id": score }` for scores and `{ "question_id": "reasoning" }` for comments. Scores must be on the raw 1–7 scale. Invalid or malformed responses trigger fallback to the next key.

8. **Fallback cascade**: If a provider call fails (network error, rate limit, invalid key, malformed response), the service tries the next active key in order. If all keys fail, `status` is set to `'error'` and no partial results are saved.

9. **Persistence**: On full success, the AI service atomically updates the `AIAnalysis` record:
   - `ai_scores_for_all_questions` = merged score map across all spheres: `{ "question_id": score_value }`
   - `ai_comments_for_all_questions` = merged comment map across all spheres: `{ "question_id": "reasoning text" }`
   - `metadata_json` = provider used, timestamp, model info
   - `status='completed'`, `updated_at=now`

10. **Polling**: The frontend polls `GET /ai/analysis/<id>/status` at regular intervals (max 120 attempts over 4 minutes).
    - On `'completed'`: the user is redirected to `/ai/analysis/<id>` (the analysis view page).
    - On `'error'`: a failure message is shown. No partial data is displayed.
    - On timeout (120 attempts exceeded without resolution): the UI displays a timeout message.

---

## 10. Results Tab — Spider Chart Data Composition

When the Results tab renders, the spider chart series are composed as follows:

**Composition order** (deterministic):

1. **Current analysis** (always index 0, always included): sphere scores computed from `Analysis.answers` by the frontend scoring engine.
2. **AI baseline** (index 1, if available): scores derived from `AIAnalysis.ai_scores_for_all_questions` where `country = Analysis.country` and `status='completed'`. The backend transforms the flat `{ question_id: score }` structure into the nested `{ sphere_name: { question_id: score } }` format required by the frontend scoring engine.
3. **Other users' analyses** (indices 2–5, up to 4): the most recently updated `Analysis` records where `country = Analysis.country` AND `user_id ≠ current user.id`, ordered by `updated_at` descending.

**Maximum series**: 6 (current + AI baseline + 4 others).

**Fallback behavior** (all silent — no error shown):
- If AI analysis does not exist or is not `'completed'`: the AI series slot is skipped. Other users may fill indices 2–5.
- If fewer than 4 other user analyses exist: only available ones are shown.
- Minimum: if only the current analysis exists, only one series is rendered.

The backend pre-serializes all series into a uniform structure (list of plain dicts with `title`, `answers_dict`, `is_current`, `is_ai` keys) before passing to the template, since ORM objects are not JSON-serializable.
