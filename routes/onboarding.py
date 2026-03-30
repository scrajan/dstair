import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from services.user_service import UserService
from utils.sanitizer import sanitize_input

# Shared profile page — accessible by all authenticated roles (user, admin, ai).
onboarding_bp = Blueprint('onboarding', __name__, url_prefix='/onboarding')
user_service = UserService()
logger = logging.getLogger(__name__)


@onboarding_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    Profile page for all authenticated roles (workflow §3).
    GET: Display current profile data.
    POST: Validate and persist name, email, and optional profile image.

    First-login behavior (workflow §1e):
    If the user has not yet completed their profile, a successful POST marks the
    profile as completed and redirects to their role dashboard. On subsequent
    visits, a successful POST flashes success and remains on the profile page.
    """
    if request.method == 'POST':
        from utils.uploads import get_profile_upload_dir, save_validated_profile_image, validate_image_upload

        name = sanitize_input(request.form.get('name', '')).strip()
        email = sanitize_input(request.form.get('email', '')).strip()

        if not name or not email:
            flash('Full name and email address are required.', 'error')
            return redirect(url_for('onboarding.profile'))

        profile_image = request.files.get('profile_image')
        image_filename = current_user.file_path_string_for_user_profile_avatar_image

        try:
            if profile_image and profile_image.filename != '':
                validated_image = validate_image_upload(profile_image)
                save_dir = get_profile_upload_dir(current_app.static_folder)
                image_filename = save_validated_profile_image(
                    validated_image,
                    save_dir,
                    current_user.user_account_unique_username_string
                )

            user_service.update_profile(current_user, name, email, image_filename)

            is_first_completion = not current_user.boolean_flag_indicating_if_user_profile_has_been_completed
            if is_first_completion:
                current_user.boolean_flag_indicating_if_user_profile_has_been_completed = True
                current_user.save()
                flash('Profile setup complete. Welcome to DSTAIR.', 'success')
                return _redirect_to_role_dashboard(current_user)

            flash('Profile updated successfully.', 'success')

        except ValueError as e:
            flash(str(e), 'error')
        except Exception:
            logger.exception(
                "Unexpected error updating profile for user %s",
                current_user.user_account_unique_username_string
            )
            flash('An unexpected error occurred. Please try again.', 'error')

        return redirect(url_for('onboarding.profile'))

    return render_template('shared/profile.html', user=current_user)


def _redirect_to_role_dashboard(user):
    if user.is_admin:
        return redirect(url_for('admin.dashboard'))
    elif user.is_ai:
        return redirect(url_for('ai_dashboard.index'))
    return redirect(url_for('dashboard.index', username=user.user_account_unique_username_string))
