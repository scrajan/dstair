import logging
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for
from flask_login import current_user
from utils.decorators import ai_role_required_decorator
from services.ai_service import AIService
from services.api_key_service import APIKeyService
from models import APIKey, AIAnalysis, Country
from extensions import limiter

ai_dashboard_bp = Blueprint('ai_dashboard', __name__, url_prefix='/ai')

ai_service = AIService()
api_key_service = APIKeyService()
logger = logging.getLogger(__name__)

# Background pool for long-running LLM evaluation tasks (workflow §9 step 3)
ai_executor = ThreadPoolExecutor(max_workers=4)


# ── Pages ───────────────────────────────────────────────────────────────────

@ai_dashboard_bp.route('/dashboard')
@ai_role_required_decorator
def index():
    """AI Dashboard — stats and archive of all country evaluations (workflow §4 AI)."""
    all_ai_evals = AIAnalysis.get_all()
    all_ai_evals.sort(key=lambda x: x.updated_at or x.created_at, reverse=True)

    return render_template(
        'ai/dashboard.html',
        user=current_user,
        analyses=all_ai_evals,
        total_runs=len(all_ai_evals),
        completed_runs=sum(1 for a in all_ai_evals if a.status == 'completed'),
        in_progress_runs=sum(1 for a in all_ai_evals if a.status == 'in_progress')
    )


@ai_dashboard_bp.route('/analysis')
@ai_role_required_decorator
def analysis():
    """Country evaluation trigger page (workflow §9 step 1)."""
    all_ai_evals = AIAnalysis.get_all()
    all_ai_evals.sort(key=lambda x: x.updated_at or x.created_at, reverse=True)
    evaluated_countries = {a.country for a in all_ai_evals if a.status == 'completed'}
    all_countries = Country.get_all_ordered()

    active_keys = APIKey.get_active_user_keys(current_user.unique_database_identifier_integer)
    active_keys_data = [k.to_dict() for k in active_keys]
    has_system_key = bool(os.getenv('GROQ_API_KEY'))

    return render_template(
        'ai/analysis.html',
        user=current_user,
        analyses=all_ai_evals,
        all_countries=all_countries,
        evaluated_countries=evaluated_countries,
        active_keys=active_keys_data,
        has_system_key=has_system_key,
    )


@ai_dashboard_bp.route('/analysis/<int:analysis_id>')
@ai_role_required_decorator
def view_analysis(analysis_id):
    """View an AI analysis result (any status)."""
    ai_analysis = AIAnalysis.get_by_id(analysis_id)
    if not ai_analysis:
        return redirect(url_for('ai_dashboard.index'))
    from models.core_models import Sphere
    spheres = Sphere.get_all_ordered()
    questions_map = {str(q.id): q for s in spheres for q in s.questions}
    return render_template(
        'ai/analysis_view.html',
        user=current_user,
        ai_analysis=ai_analysis,
        spheres=spheres,
        questions_map=questions_map
    )


@ai_dashboard_bp.route('/api-keys')
@ai_role_required_decorator
def api_keys():
    """BYOK API key manager (workflow §8)."""
    user_keys = api_key_service.get_user_keys(current_user.unique_database_identifier_integer)
    keys_by_provider = {}
    for key in user_keys:
        keys_by_provider.setdefault(key.provider, []).append(key.to_dict())

    return render_template(
        'ai/api_keys.html',
        user=current_user,
        providers=APIKey.PROVIDERS,
        keys_by_provider=keys_by_provider
    )


# ── AI Evaluation API ────────────────────────────────────────────────────────

@ai_dashboard_bp.route('/analysis/evaluate', methods=['POST'])
@ai_role_required_decorator
@limiter.limit("5 per minute")
def evaluate():
    """
    Trigger a background AI country evaluation (workflow §9 steps 2–3).
    Returns immediately with the analysis ID. Frontend polls /analysis/<id>/status.
    Per spec: if a record exists for the country, reset in-place; else create new.
    """
    data = request.get_json(silent=True) or {}
    country_code = (data.get('country') or '').strip()
    additional_instructions = data.get('additional_instructions', '').strip() or None
    selected_key_id = data.get('selected_key_id') or None  # int key ID, 'system', or None

    if not country_code:
        return jsonify({'success': False, 'error': 'Country code is required.'}), 400

    country_record = Country.find_one(code=country_code) or Country.find_one(name=country_code)
    if not country_record:
        return jsonify({'success': False, 'error': f'Country "{country_code}" not recognized.'}), 400

    country_code = country_record.code

    try:
        ai_analysis = AIAnalysis.get_by_country(country_code)

        if ai_analysis and ai_analysis.status == 'in_progress':
            return jsonify({
                'success': False,
                'error': 'An evaluation is already in progress for this country.'
            }), 409

        if not ai_analysis:
            ai_analysis = AIAnalysis(country=country_code, status='not_started')
            ai_analysis.save()

        # Reset in-place per spec overwrite behavior
        ai_analysis.mark_in_progress()
        analysis_id = ai_analysis.id

        app = current_app._get_current_object()
        user_id = current_user.unique_database_identifier_integer

        def run_eval(app_ctx, uid, code, aid, instr, key_id):
            with app_ctx.app_context():
                try:
                    ai_service.evaluate_country(uid, code, existing_analysis_id=aid,
                                                additional_instructions=instr,
                                                selected_key_id=key_id)
                except Exception as e:
                    logger.error("Background AI evaluation failed for %s: %s", code, e)
                    record = AIAnalysis.get_by_id(aid)
                    if record:
                        record.mark_error(str(e))

        ai_executor.submit(run_eval, app, user_id, country_code, analysis_id,
                           additional_instructions, selected_key_id)

        return jsonify({'success': True, 'analysis_id': analysis_id})

    except Exception:
        logger.exception("Failed to start AI evaluation for %s", country_code)
        return jsonify({'success': False, 'error': 'Failed to start evaluation.'}), 500


@ai_dashboard_bp.route('/analysis/<int:analysis_id>/status')
@ai_role_required_decorator
def analysis_status(analysis_id):
    """Poll endpoint for frontend during evaluation (workflow §9 step 10)."""
    ai_analysis = AIAnalysis.get_by_id(analysis_id)
    if not ai_analysis:
        return jsonify({'error': 'Not found.'}), 404

    return jsonify({
        'id': ai_analysis.id,
        'country': ai_analysis.country,
        'status': ai_analysis.status,
        'metadata': ai_analysis.metadata_json or {},
        'completed': ai_analysis.status == 'completed',
        'error': ai_analysis.status == 'error'
    })


@ai_dashboard_bp.route('/analysis/<int:analysis_id>/delete', methods=['DELETE'])
@ai_role_required_decorator
def delete_analysis(analysis_id):
    """Permanently delete an AI analysis record (workflow §4 AI, archive)."""
    ai_analysis = AIAnalysis.get_by_id(analysis_id)
    if not ai_analysis:
        return jsonify({'success': False, 'error': 'Not found.'}), 404

    try:
        ai_analysis.delete()
        return jsonify({'success': True})
    except Exception:
        logger.exception("Error deleting AI analysis %s", analysis_id)
        return jsonify({'success': False, 'error': 'Failed to delete.'}), 500


# ── API Key Management ───────────────────────────────────────────────────────

@ai_dashboard_bp.route('/api-keys/save', methods=['POST'])
@ai_role_required_decorator
def save_api_key():
    """Encrypt and persist a new provider API key (workflow §8a)."""
    data = request.get_json(silent=True) or {}
    provider = data.get('provider', '').strip()
    api_key_value = data.get('api_key', '').strip()

    if not provider or provider not in APIKey.PROVIDERS:
        return jsonify({'success': False, 'error': 'Invalid provider.'}), 400
    if not api_key_value:
        return jsonify({'success': False, 'error': 'API key cannot be empty.'}), 400

    try:
        api_key_service.save_key(
            current_user.unique_database_identifier_integer,
            provider,
            api_key_value
        )
        return jsonify({'success': True})
    except Exception:
        logger.exception("Failed to save API key for provider %s", provider)
        return jsonify({'success': False, 'error': 'Failed to save key.'}), 500


@ai_dashboard_bp.route('/api-keys/<int:key_id>/toggle', methods=['POST'])
@ai_role_required_decorator
def toggle_api_key(key_id):
    """Toggle a key active/inactive (workflow §8b)."""
    try:
        is_active = api_key_service.toggle_key(
            current_user.unique_database_identifier_integer, key_id
        )
        return jsonify({'success': True, 'is_active': is_active})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        logger.exception("Error toggling API key %s", key_id)
        return jsonify({'success': False, 'error': 'Failed to toggle key.'}), 500


@ai_dashboard_bp.route('/api-keys/<int:key_id>/delete', methods=['DELETE'])
@ai_role_required_decorator
def delete_api_key(key_id):
    """Delete a key (workflow §8d)."""
    try:
        api_key_service.delete_key(
            current_user.unique_database_identifier_integer, key_id
        )
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        logger.exception("Error deleting API key %s", key_id)
        return jsonify({'success': False, 'error': 'Failed to delete key.'}), 500


@ai_dashboard_bp.route('/api-keys/reorder', methods=['POST'])
@ai_role_required_decorator
def reorder_api_keys():
    """Update key execution priority order (workflow §8c)."""
    data = request.get_json(silent=True) or {}
    key_order = data.get('order', [])

    if not key_order or not isinstance(key_order, list):
        return jsonify({'success': False, 'error': 'Invalid ordering data.'}), 400

    try:
        int_order = [int(k) for k in key_order]
        api_key_service.reorder_keys(current_user.unique_database_identifier_integer, int_order)
        return jsonify({'success': True})
    except Exception:
        logger.exception("Error reordering API keys")
        return jsonify({'success': False, 'error': 'Failed to reorder keys.'}), 500
