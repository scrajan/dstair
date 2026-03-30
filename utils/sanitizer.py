"""
Centralized HTML/string sanitization module.
==============================================
This is the SINGLE source of truth for all bleach-based sanitization.
No other file in the project should import bleach directly.

Per spec/constitution.md:
    "All HTML/string sanitization via bleach MUST go through utils/sanitizer.py.
     No direct bleach calls are allowed in services or models."
"""
import bleach


# ── Plain‐text sanitizer (for profile fields, usernames, emails) ───
def sanitize_input(value: str) -> str:
    """
    Strip ALL HTML tags and return plain text.
    Use this for user-supplied strings that must never contain markup
    (names, emails, organization fields, etc.).
    """
    if not value:
        return value
    return bleach.clean(value, tags=[], strip=True)


# ── Rich‐text sanitizer (for UGC comments) ────────────────────────
# Allows a safe subset of formatting tags for user comments on questions.
ALLOWED_COMMENT_TAGS = ['p', 'b', 'i', 'u', 'em', 'strong', 'ul', 'ol', 'li', 'br']


def sanitize_comment(value: str) -> str:
    """
    Sanitize rich‐text comment content, allowing only safe formatting tags.
    Use this for Comment.text and similar user‐generated‐content fields.
    """
    if not value:
        return value
    return bleach.clean(value, tags=ALLOWED_COMMENT_TAGS, strip=True)
