import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import limiter, csrf
from services.access_request_service import AccessRequestService
from utils.sanitizer import sanitize_input

# Initialize Blueprint for standard public-facing marketing pages
public_bp = Blueprint('public', __name__)
access_request_service = AccessRequestService()
logger = logging.getLogger(__name__)

@public_bp.route('/')
def home():
    """Renders the primary high-fidelity landing page (marketing UI)."""
    return render_template('landing.html')

@public_bp.route('/about')
def about():
    """Renders the About DSTAIR page."""
    return render_template('public/about.html')

@public_bp.route('/how-it-works')
def how_it_works():
    """Renders the Methodology/How It Works page."""
    return render_template('public/how_it_works.html')

@public_bp.route('/resources')
def resources():
    """Renders the educational Resources page."""
    return render_template('public/resources.html')

@public_bp.route('/contact')
def contact():
    """Renders the Contact Us / Access Request page."""
    return render_template('public/contact.html')

@public_bp.route('/faq')
def faq():
    """Renders the Frequently Asked Questions page."""
    return render_template('public/faq.html')

@public_bp.route('/contact', methods=['POST'])
@limiter.limit("5 per hour")
def submit_contact():
    """
    Handle access request submission from the Contact Us page.
    Sanitizes input and queues a pending request for Admin review.
    """
    # Extract and sanitize inputs to prevent XSS/injection
    name = sanitize_input(request.form.get('name', '')).strip()
    email = sanitize_input(request.form.get('email', '')).strip()
    organization = sanitize_input(request.form.get('organization', '')).strip()
    message = sanitize_input(request.form.get('message', '')).strip()

    if not name or not email:
        flash('Name and email are required to process your request.', 'error')
        return redirect(url_for('public.contact'))

    try:
        access_request_service.submit_request(name, email, organization, message)
        flash('Your access request has been submitted. You will be contacted once approved.', 'success')
    except ValueError as e:
        # Expected business logic errors (e.g., duplicate pending request)
        flash(str(e), 'info')
    except Exception:
        logger.exception("Failed to process access request for %s", email)
        flash('An unexpected error occurred. Please try again later.', 'error')

    return redirect(url_for('public.contact'))

@public_bp.route('/healthz')
def healthz():
    """Liveness probe for health monitoring and deployment systems."""
    return jsonify({'status': 'ok'}), 200
