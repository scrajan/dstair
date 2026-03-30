import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from models.analysis_models import Analysis
from models.core_models import Comment
from services.analysis_service import AnalysisService

logger = logging.getLogger(__name__)

analysis_bp = Blueprint('analysis', __name__)
analysis_service = AnalysisService()


# ── Analysis Workspace ──────────────────────────────────────────────────────

@analysis_bp.route('/regular_user/<username>/analysis/<int:analysis_id>', endpoint='view')
@analysis_bp.route('/analysis/<int:analysis_id>')
@login_required
def view(analysis_id, username=None):
    """
    Analysis workspace shell (workflow §4).
    Loads the index template with the questionnaire tab active by default.
    Tab content is loaded dynamically via AJAX to the /tab/<name> endpoint.
    The primary URL is /regular_user/<username>/analysis/<id>.
    The legacy /analysis/<id> route is kept for admin panel compatibility.
    """
    analysis = Analysis.get_by_id_and_user(
        analysis_id, current_user.unique_database_identifier_integer
    )
    if not analysis:
        flash('Analysis not found.', 'error')
        return redirect(url_for('dashboard.index', username=current_user.user_account_unique_username_string))

    spheres = analysis_service.get_all_spheres()
    return render_template(
        'user/analysis/index.html',
        analysis=analysis,
        spheres=spheres
    )


@analysis_bp.route('/regular_user/<username>/analysis/<int:analysis_id>/tab/<tab_name>', endpoint='tab')
@analysis_bp.route('/analysis/<int:analysis_id>/tab/<tab_name>')
@login_required
def tab(analysis_id, tab_name, username=None):
    """
    AJAX endpoint: render a tab partial and return it as HTML (workflow §4c).
    Valid tabs: questionnaire, results, tools.
    """
    analysis = Analysis.get_by_id_and_user(
        analysis_id, current_user.unique_database_identifier_integer
    )
    if not analysis:
        abort(404)

    if tab_name == 'questionnaire':
        spheres = analysis_service.get_all_spheres()
        return render_template(
            'user/analysis/partials/questionnaire.html',
            analysis=analysis,
            spheres=spheres
        )

    if tab_name == 'results':
        spheres = analysis_service.get_all_spheres()
        radar_analyses = analysis_service.get_radar_chart_analyses(
            analysis.country, analysis
        )
        # Pre-serialize for JS: ORM objects are not JSON-serializable
        radar_series = []
        for i, a in enumerate(radar_analyses):
            if isinstance(a, dict):
                radar_series.append({
                    'title': a.get('title', 'AI Baseline'),
                    'answers_dict': a.get('answers_dict', {}),
                    'is_current': False,
                    'is_ai': a.get('is_ai', False),
                })
            else:
                radar_series.append({
                    'title': a.title,
                    'answers_dict': a.answers_dict or {},
                    'is_current': (i == 0),
                    'is_ai': False,
                })
        sphere_labels = [{'name': s.name, 'label': s.label} for s in spheres]
        return render_template(
            'user/analysis/partials/results.html',
            analysis=analysis,
            spheres=spheres,
            radar_analyses=radar_analyses,
            radar_series=radar_series,
            sphere_labels=sphere_labels
        )

    if tab_name == 'tools':
        tools = analysis_service.get_sorted_tools(analysis_id)
        triggered_ids = set(analysis.triggered_tools or [])
        return render_template(
            'user/analysis/partials/tools.html',
            analysis=analysis,
            tools=tools,
            triggered_ids=triggered_ids
        )

    if tab_name == 'ai_analysis':
        from models.ai_analysis_models import AIAnalysis
        from models.core_models import Sphere
        ai_analysis = AIAnalysis.get_by_country(analysis.country)
        spheres = Sphere.get_all_ordered()
        questions_map = {str(q.id): q for s in spheres for q in s.questions}
        return render_template(
            'user/analysis/partials/ai_analysis.html',
            analysis=analysis,
            ai_analysis=ai_analysis,
            spheres=spheres,
            questions_map=questions_map
        )

    abort(404)


# ── Analysis CRUD ───────────────────────────────────────────────────────────

@analysis_bp.route('/analysis/create', methods=['POST'])
@login_required
def create():
    """Create a new blank analysis (workflow §4a). Returns JSON with analysis ID and redirect URL."""
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    country = data.get('country', '').strip()
    notes = data.get('notes', '').strip() or None

    if not title or not country:
        return jsonify({'success': False, 'error': 'Title and country are required.'}), 400

    analysis = analysis_service.create_analysis(
        user_id=current_user.unique_database_identifier_integer,
        title=title,
        country=country,
        notes=notes
    )
    return jsonify({
        'success': True,
        'analysis_id': analysis.id,
        'redirect': url_for('analysis.view', username=current_user.user_account_unique_username_string, analysis_id=analysis.id)
    })


@analysis_bp.route('/analysis/<int:analysis_id>/edit', methods=['POST'])
@login_required
def edit(analysis_id):
    """Update analysis title and notes (workflow §4d). Country is not editable."""
    analysis = Analysis.get_by_id_and_user(
        analysis_id, current_user.unique_database_identifier_integer
    )
    if not analysis:
        return jsonify({'success': False, 'error': 'Not found.'}), 404

    body = request.get_json(silent=True) or {}
    title = body.get('title', '').strip()
    notes = body.get('notes', '').strip() or None

    if not title:
        return jsonify({'success': False, 'error': 'Title is required.'}), 400

    try:
        analysis_service.update_analysis_metadata(analysis_id, title, notes)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@analysis_bp.route('/analysis/<int:analysis_id>/delete', methods=['POST'])
@login_required
def delete(analysis_id):
    """
    Delete an analysis and cascade-delete its linked comments (workflow §4e).
    Returns JSON so the AJAX caller can redirect client-side.
    """
    analysis = Analysis.get_by_id_and_user(
        analysis_id, current_user.unique_database_identifier_integer
    )
    if not analysis:
        return jsonify({'success': False, 'error': 'Not found.'}), 404

    try:
        analysis_service.delete_analysis(analysis_id)
        return jsonify({'success': True, 'redirect': url_for('dashboard.index', username=current_user.user_account_unique_username_string)})
    except Exception:
        logger.exception('Error deleting analysis %s', analysis_id)
        return jsonify({'success': False, 'error': 'Failed to delete analysis.'}), 500


# ── Answer Save ─────────────────────────────────────────────────────────────

@analysis_bp.route('/analysis/<int:analysis_id>/answer', methods=['POST'])
@login_required
def answer(analysis_id):
    """
    AJAX: save a single answer and return updated triggered_tools (workflow §4b).

    Per spec invariant #3:
    - The backend NEVER computes or returns scores.
    - This endpoint returns ONLY triggered_tools (list of IDs).
    """
    analysis = Analysis.get_by_id_and_user(
        analysis_id, current_user.unique_database_identifier_integer
    )
    if not analysis:
        return jsonify({'success': False, 'error': 'Not found.'}), 404

    data = request.get_json(silent=True) or {}
    sphere = data.get('sphere')
    question_id = str(data.get('question_id', ''))
    value = data.get('value')
    client_timestamp = int(data.get('timestamp', 0))

    if not sphere or not question_id or value is None:
        return jsonify({'success': False, 'error': 'Missing required fields.'}), 400

    try:
        triggered_tools = analysis_service.save_answer_and_evaluate_tools(
            analysis_id=analysis_id,
            sphere_name=sphere,
            question_id=question_id,
            value=value,
            client_timestamp=client_timestamp
        )
        return jsonify({'success': True, 'triggered_tools': triggered_tools})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ── AI Context ──────────────────────────────────────────────────────────────

@analysis_bp.route('/analysis/question/<int:question_id>/ai-context')
@login_required
def ai_context(question_id):
    """
    AJAX: fetch AI-generated score and reasoning for a question (constitution §3, Tab 1).
    The country is derived from the analysis_id query parameter.
    Returns the AI data or a 'not available' message.
    """
    from models.core_models import Question as QuestionModel
    analysis_id = request.args.get('analysis_id', type=int)
    country = None

    if analysis_id:
        analysis = Analysis.get_by_id_and_user(
            analysis_id, current_user.unique_database_identifier_integer
        )
        if analysis:
            country = analysis.country

    question = QuestionModel.query.get(question_id)
    question_content = question.content if question else ''
    question_order   = question.order if question else 0
    scale_min        = question.scale_min_label if question else 'Low'
    scale_max        = question.scale_max_label if question else 'High'

    context = analysis_service.get_ai_question_context(question_id, country)
    if context:
        return jsonify({
            'available': True,
            'question_content': question_content,
            'question_order': question_order,
            'scale_min_label': scale_min,
            'scale_max_label': scale_max,
            'country': country or '',
            **context
        })
    return jsonify({
        'available': False,
        'message': 'AI analysis is currently not available for this country.',
        'question_content': question_content,
        'country': country or ''
    })


@analysis_bp.route('/analysis/question/<int:question_id>/comments', methods=['GET'])
@login_required
def get_comments(question_id):
    """AJAX: fetch all comments for a question."""
    from models.core_models import Question as QuestionModel
    question = QuestionModel.query.get_or_404(question_id)
    return jsonify({'success': True, 'comments': question.serialize_comments})


# ── Comments ────────────────────────────────────────────────────────────────

@analysis_bp.route('/analysis/question/<int:question_id>/comment', methods=['POST'])
@login_required
def post_comment(question_id):
    """
    Post a comment on a question (workflow §5a).
    user_display stores the author's username for identity tracking.
    analysis_id is nullable — linked when posted inside an analysis context.
    """
    data = request.get_json(silent=True) or {}
    comment_text = data.get('text', '').strip()
    analysis_id = data.get('analysis_id')  # nullable

    if not comment_text:
        return jsonify({'success': False, 'error': 'Comment text is required.'}), 400

    try:
        result = analysis_service.add_comment_to_question(
            question_id=question_id,
            user_display=current_user.user_account_unique_username_string,
            comment_text=comment_text,
            analysis_id=analysis_id
        )
        return jsonify({'success': True, 'comment': result})
    except Exception as e:
        logger.exception('Error posting comment on question %s', question_id)
        return jsonify({'success': False, 'error': str(e)}), 400


@analysis_bp.route('/analysis/question/<int:question_id>/comment/<comment_id>/delete', methods=['DELETE'])
@login_required
def delete_comment(question_id, comment_id):
    """
    Delete a comment (workflow §5b, §5c).
    Allowed if the requester is the comment author (matched by username) or an admin.
    Returns 403 if unauthorized.
    """
    comment = Comment.get_by_id(comment_id)
    if not comment or comment.question_id != question_id:
        return jsonify({'success': False, 'error': 'Comment not found.'}), 404

    is_author = (comment.user_display == current_user.user_account_unique_username_string)
    is_admin = current_user.is_admin

    if not is_author and not is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized.'}), 403

    try:
        analysis_service.delete_comment(question_id, comment_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.exception('Error deleting comment %s', comment_id)
        return jsonify({'success': False, 'error': str(e)}), 400
