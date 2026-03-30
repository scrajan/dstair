import logging
from models.core_models import Sphere, Tool, Question, Comment
from models.analysis_models import Analysis
from models.ai_analysis_models import AIAnalysis
from extensions import db
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

# Module-level primitive cache to prevent repeated DB hits during live scoring
_global_sphere_questions_cache = {}

class AnalysisService:
    """
    Core business logic layer for the questionnaire system.
    Handles analysis CRUD, answer persistence, tool trigger evaluation,
    comment management, and radar chart data composition.

    Score computation contract:
    - Scores (T_j, I_j) are NEVER stored and NEVER returned to the frontend.
    - The backend computes scores internally ONLY to evaluate tool triggers.
    - The frontend JS engine recomputes scores independently on every render.
    """

    def __init__(self):
        self._sphere_info_cache: dict = {}

    # ── Sphere helpers ──────────────────────────────────────────────────

    def _get_sphere_info_map(self) -> dict:
        """Returns a map of {name: {'id': id, 'label': label, 'name': name}}."""
        if not self._sphere_info_cache:
            for s in Sphere.get_all_ordered():
                self._sphere_info_cache[s.name] = {
                    'id': s.id,
                    'label': s.label,
                    'name': s.name
                }
        return self._sphere_info_cache

    def get_all_spheres(self) -> list:
        return Sphere.get_all_ordered()

    # ── Analysis CRUD ───────────────────────────────────────────────────

    def get_analyses_for_user(self, user_id: int) -> list:
        return Analysis.get_all_for_user(user_id)

    def get_analysis_for_user(self, analysis_id: int, user_id: int):
        return Analysis.get_by_id_and_user(analysis_id, user_id)

    def get_country_comparisons(self, country: str, exclude_user_id: int) -> list:
        """Return other users' analyses for the same country (no status filter per spec)."""
        if not country:
            return []
        return Analysis.get_by_country_excluding_user(country, exclude_user_id)

    def get_radar_chart_analyses(self, country: str, current_analysis) -> list:
        """
        Compose the spider chart series per spec §10:
        1. Current analysis (always included)
        2. AI baseline for the country (if completed)
        3. Up to 4 most recently updated other-user analyses for the same country
        Maximum: 6 series total.
        """
        if not country:
            return [current_analysis]

        radar_analyses = [current_analysis]

        # 1. AI baseline
        ai_eval = AIAnalysis.get_by_country(country)
        if ai_eval and ai_eval.status == 'completed':
            ai_proxy = {
                'id': f'ai-{ai_eval.id}',
                'title': ai_eval.title,
                'is_current': False,
                'is_ai': True,
                'answers': self._transform_ai_scores_to_nested(ai_eval.ai_scores_for_all_questions),
                'answers_dict': self._transform_ai_scores_to_nested(ai_eval.ai_scores_for_all_questions)
            }
            radar_analyses.append(ai_proxy)

        # 2. Other users' analyses (up to 4, filling remaining slots to max 6)
        exclude_id = getattr(current_analysis, 'user_id', 0) or 0
        other_users = Analysis.get_by_country_excluding_user(country, exclude_id)
        needed = 6 - len(radar_analyses)
        for o in other_users[:needed]:
            radar_analyses.append(o)

        return radar_analyses

    def _transform_ai_scores_to_nested(self, ai_scores: dict) -> dict:
        """
        Converts flat AI scores {question_id: score} into nested sphere structure
        {sphere_name: {question_id: score}} required by the frontend scoring engine.
        """
        if not ai_scores:
            return {}

        all_spheres = Sphere.get_all_ordered()
        nested = {}
        q_to_sphere = {}
        for s in all_spheres:
            nested[s.name] = {}
            for q in s.questions:
                q_to_sphere[str(q.id)] = s.name

        for q_id, rating in ai_scores.items():
            s_name = q_to_sphere.get(str(q_id))
            if s_name:
                nested[s_name][str(q_id)] = rating

        return nested

    def count_analyses(self, user_id: int) -> int:
        return Analysis.count_total_for_user(user_id)

    def count_unique_countries(self, user_id: int) -> int:
        return Analysis.get_unique_countries_count(user_id)

    def get_aggregated_triggered_tools_count(self, user_id: int) -> int:
        """Count of unique tool IDs triggered across all of this user's analyses."""
        analyses = Analysis.get_all_for_user(user_id)
        unique_tool_ids = set()
        for analysis in analyses:
            for tool_id in (analysis.triggered_tools or []):
                unique_tool_ids.add(tool_id)
        return len(unique_tool_ids)

    def create_analysis(self, user_id: int, title: str, country: str, notes: str = None):
        """
        Create a new analysis with a pre-populated answers skeleton per workflow §4a.
        Every sphere name and question ID is present as a key from creation.
        All values are initialized to '-1' (unanswered/N/A sentinel).
        """
        skeleton = {}
        for sphere in Sphere.get_all_ordered():
            skeleton[sphere.name] = {
                str(q.id): '-1' for q in sphere.questions
            }

        analysis = Analysis(
            user_id=user_id,
            title=title,
            country=country,
            notes=notes,
            answers=skeleton,
            triggered_tools=[]
        )
        analysis.save(commit=True)
        return analysis

    def delete_analysis(self, analysis_id: int):
        analysis = Analysis.get_by_id(analysis_id)
        if analysis:
            analysis.delete()

    def update_analysis_metadata(self, analysis_id: int, title: str, notes: str):
        """Update analysis title and notes per workflow §4d. Country is not editable."""
        analysis = Analysis.get_by_id(analysis_id)
        if not analysis:
            raise ValueError("Analysis not found")
        analysis.title = title
        analysis.notes = notes
        return analysis.save()

    # ── Scoring Algorithm ───────────────────────────────────────────────
    # NOTE: Used internally for tool trigger evaluation only.
    # Scores are NEVER stored and NEVER returned to the frontend.

    def calculate_all_scores(self, answers: dict) -> dict:
        """
        Calculate legitimacy scores (T_j) for all spheres.
        Returns: {'CONSTITUTION': 0.850, ...}
        """
        scores = {}
        sphere_info_map = self._get_sphere_info_map()
        for s_name in sphere_info_map:
            score = self.calculate_sphere_legitimacy(s_name, answers)
            if score != -1:
                scores[s_name] = score
        return scores

    def calculate_aggregate_index(self, scores: dict) -> float:
        """Calculate the 0.0–1.0 global composite legitimacy index."""
        if not scores:
            return 0.0
        return round(sum(scores.values()) / len(scores), 3)

    def calculate_sphere_legitimacy(self, sphere_name: str, answers: dict) -> float:
        """
        A(j) = Σᵢ(aᵢⱼ × rᵢⱼ) / (7 × Σᵢ aᵢⱼ)

        rᵢⱼ  = raw 1–7 rating (no remapping).
        aᵢⱼ  = importance weight (1=LOW, 2=MEDIUM, 3=HIGH).
        7    = λ_max (maximum possible rating).
        Sum  is over answered questions only (sentinel -1 excluded).
        Returns -1 if no valid answers exist for the sphere.
        """
        sphere_info_map = self._get_sphere_info_map()
        sphere_info = sphere_info_map.get(sphere_name)
        if not sphere_info:
            return -1

        sphere_id = sphere_info['id']
        global _global_sphere_questions_cache
        if sphere_id not in _global_sphere_questions_cache:
            raw_qs = Question.filter_by(sphere_id=sphere_id)
            _global_sphere_questions_cache[sphere_id] = [
                {'id': str(q.id), 'importance': float(q.importance or 1.0)}
                for q in raw_qs
            ]

        cached_questions = _global_sphere_questions_cache[sphere_id]
        sphere_answers = answers.get(sphere_name, {})
        numerator = 0.0
        denominator = 0.0

        for cq in cached_questions:
            user_val = sphere_answers.get(cq['id']) or sphere_answers.get(int(cq['id']))
            if user_val is None or user_val == 'NA' or user_val == '' or str(user_val) == '-1':
                continue
            try:
                rating = max(1, min(7, int(user_val)))
                weight = cq['importance']
                numerator += weight * rating
                denominator += weight * 7  # λ_max = 7
            except (ValueError, TypeError):
                pass

        if denominator > 0:
            return round(numerator / denominator, 3)

        return -1

    def save_answer_and_evaluate_tools(
        self,
        analysis_id: int,
        sphere_name: str,
        question_id: str,
        value: str,
        client_timestamp: int = 0
    ) -> list:
        """
        Atomically save a raw answer and recalculate triggered tools.
        Returns the current list of triggered tool IDs.

        Per spec:
        - Scores are computed internally for tool logic but NEVER stored or returned.
        - The backend returns only the triggered_tools list.
        - Pessimistic locking prevents race conditions on concurrent AJAX saves.
        """
        analysis = Analysis.get_by_id_locked(analysis_id)
        if not analysis:
            raise ValueError("Analysis not found")

        # Reject stale out-of-order requests
        if client_timestamp and analysis.last_sync_timestamp and client_timestamp < analysis.last_sync_timestamp:
            return analysis.triggered_tools or []

        # Merge the new answer into the current answers map
        current_answers = dict(analysis.answers or {})
        if sphere_name not in current_answers:
            current_answers[sphere_name] = {}
        current_answers[sphere_name][str(question_id)] = value
        analysis.answers = current_answers
        flag_modified(analysis, "answers")

        if client_timestamp:
            analysis.last_sync_timestamp = client_timestamp

        # Evaluate tool triggers (scores computed here are NOT stored or returned)
        internal_scores = self.calculate_all_scores(current_answers)
        self._update_triggered_tools(analysis, internal_scores)

        analysis.save(commit=True)
        return analysis.triggered_tools or []

    # ── Tool Evaluation ─────────────────────────────────────────────────

    def _update_triggered_tools(self, analysis, scores: dict) -> None:
        """
        Recalculate which tools are triggered and persist as a JSON list of IDs.

        Trigger logic (AND across all criteria):
          For each ToolCriteria: condition satisfied when
            A(j) >= min_score_threshold  OR  A(j) == -1 (sphere unanswered)
          A tool triggers only when ALL of its criteria conditions are satisfied.
        """
        all_tools = Tool.get_all_with_criteria()
        sphere_info_map = self._get_sphere_info_map()
        id_to_name = {info['id']: info['name'] for info in sphere_info_map.values()}

        new_tool_ids = []
        for tool in all_tools:
            if not tool.criteria:
                continue
            triggered = True
            for criteria in tool.criteria:
                s_name = id_to_name.get(criteria.sphere_id)
                if not s_name:
                    triggered = False
                    break
                try:
                    s_score = float(scores.get(s_name, -1))
                except (ValueError, TypeError):
                    s_score = -1
                # Condition satisfied: score >= threshold OR sphere unanswered (-1)
                if s_score != -1 and s_score < criteria.min_score_threshold:
                    triggered = False
                    break
            if triggered:
                new_tool_ids.append(tool.id)

        current_ids = set(analysis.triggered_tools or [])
        if current_ids != set(new_tool_ids):
            analysis.triggered_tools = new_tool_ids
            flag_modified(analysis, "triggered_tools")

    def get_sorted_tools(self, analysis_id: int) -> list:
        """Return all tools with triggered ones first, then by ID."""
        analysis = Analysis.get_by_id(analysis_id)
        triggered_ids = set(analysis.triggered_tools or []) if analysis else set()
        all_tools = Tool.get_all_with_criteria()
        for tool in all_tools:
            tool.is_flagged = tool.id in triggered_ids
        return sorted(all_tools, key=lambda x: (0 if x.id in triggered_ids else 1, x.id))

    def get_all_tools(self) -> list:
        return Tool.get_all()

    def get_all_tools_with_criteria(self) -> list:
        return Tool.get_all_with_criteria()

    def get_aggregated_user_tools(self, user_id: int) -> list:
        """Return all unique Tool objects triggered across all of this user's analyses."""
        analyses = Analysis.get_all_for_user(user_id)
        unique_tool_ids = set()
        for analysis in analyses:
            for tool_id in (analysis.triggered_tools or []):
                unique_tool_ids.add(tool_id)
        if not unique_tool_ids:
            return []
        all_tools = Tool.get_all_with_criteria()
        return sorted([t for t in all_tools if t.id in unique_tool_ids], key=lambda x: x.id)

    # ── AI Integration ──────────────────────────────────────────────────

    def get_ai_question_context(self, question_id: int, country_code: str) -> dict:
        """
        Fetch the AI-generated score and reasoning for a specific question.
        Returns None if no completed AI analysis exists for the country.
        """
        if not country_code:
            return None

        ai_eval = AIAnalysis.get_by_country(country_code)
        if not ai_eval or ai_eval.status != 'completed':
            return None

        qid_str = str(question_id)
        score = (ai_eval.ai_scores_for_all_questions or {}).get(qid_str)
        comment = (ai_eval.ai_comments_for_all_questions or {}).get(qid_str)

        if score is None:
            return None

        return {
            'score': score,
            'comment': comment or "No reasoning provided by AI.",
            'timestamp': ai_eval.updated_at.strftime('%m/%d/%Y') if ai_eval.updated_at else 'Unknown'
        }

    # ── Comments ────────────────────────────────────────────────────────

    def add_comment_to_question(
        self,
        question_id: int,
        user_display: str,
        comment_text: str,
        analysis_id: int = None
    ) -> dict:
        """
        Create a Comment record for a question.
        user_display is the author's current full name captured at write time.
        analysis_id is nullable — null for standalone comments outside an analysis context.
        """
        import uuid
        from datetime import datetime
        from models.user_models import User
        from core.exceptions import RequestedResourceNotFoundError, RequestPayloadValidationError

        question = Question.get_by_id(question_id)
        if not question:
            raise RequestedResourceNotFoundError("Question not found")
        if not comment_text.strip():
            raise RequestPayloadValidationError("Comment cannot be empty")

        timestamp = datetime.now()
        new_comment_id = str(uuid.uuid4())

        new_comment_dict = {
            'id': new_comment_id,
            'user': user_display,
            'date': timestamp.strftime('%m/%d/%Y %I:%M:%S %p'),
            'comment': comment_text.strip()
        }

        question.add_comment(new_comment_dict, analysis_id=analysis_id)

        user = User.get_by_username(user_display)
        return {
            'id': new_comment_id,
            'user': user_display,
            'user_full_name': user.user_account_full_name_string if user else user_display,
            'user_avatar': user.file_path_string_for_user_profile_avatar_image if user else None,
            'comment': comment_text.strip(),
            'date': timestamp.strftime('%m/%d/%Y %I:%M:%S %p'),
            'analysis_id': analysis_id
        }

    def delete_comment(self, question_id: int, comment_id: str) -> None:
        """
        Delete a comment by ID after verifying it belongs to this question.
        Authorization (owner or admin) is enforced at the route layer.
        """
        from core.exceptions import RequestedResourceNotFoundError
        question = Question.get_by_id(question_id)
        if not question:
            raise RequestedResourceNotFoundError("Question not found")
        success = question.remove_comment(comment_id)
        if not success:
            raise RequestedResourceNotFoundError("Comment not found")
