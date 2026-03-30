import logging
import secrets
import string
import urllib.parse
from datetime import datetime, timezone
from models.access_request_models import AccessRequest
from services.user_service import UserService
from utils.sanitizer import sanitize_input

logger = logging.getLogger(__name__)

class AccessRequestService:
    """
    Manages the onboarding pipeline for new analysts.
    Handles submission, approval (account provisioning), and rejection of access requests.
    """
    def __init__(self):
        self.user_service = UserService()

    def submit_request(self, name: str, email: str, organization: str, message: str) -> AccessRequest:
        """
        Persists a new access request from the public contact form.
        Sanitizes all text inputs to prevent XSS in the Admin dashboard.
        """
        # COORDINATION: Ensure no duplicate pending requests for the same email
        existing = AccessRequest.get_by_email_and_status(email, 'pending')
        if existing:
            raise ValueError("An access request with this email is already pending review.")
            
        req = AccessRequest(
            name=sanitize_input(name),
            email=sanitize_input(email),
            organization=sanitize_input(organization) if organization else None,
            message=sanitize_input(message) if message else None
        )
        return req.save()

    def get_requests(self, status: str = 'pending'):
        """Fetch access requests filtered by status, ordered by most recent first."""
        if status == 'all':
            return AccessRequest.get_all_ordered_by_date()
        return AccessRequest.get_by_status_ordered(status)

    def get_pending_count(self) -> int:
        """Return the count of requests awaiting admin review."""
        return AccessRequest.count_by_status('pending')
        
    def get_request(self, request_id: int) -> AccessRequest:
        """Fetch a specific request by ID with basic existence validation."""
        req = AccessRequest.get_by_id(request_id)
        if not req:
            raise ValueError("Access request not found.")
        return req
        
    def delete_request(self, request_id: int):
        """Permanently remove a request record from the system."""
        req = self.get_request(request_id)
        req.delete()
        
    def reject_request(self, request_id: int) -> AccessRequest:
        """Mark a pending request as rejected."""
        req = self.get_request(request_id)
        if req.status != 'pending':
            raise ValueError(f"Request cannot be rejected; current status is '{req.status}'.")
        
        req.mark_rejected()
        return req

    def approve_request(self, request_id: int) -> dict:
        """
        Approves a request, provisions a new user account, and returns credentials for the Admin.
        
        Strictly follows the manual sharing policy:
        1. Generates unique username and secure random password.
        2. Creates account with 'user' role only.
        3. Returns a pre-formatted 'mailto' link to assist the Admin in manual sharing.
        """
        req = self.get_request(request_id)
        if req.status != 'pending':
            raise ValueError(f"Request cannot be approved; current status is '{req.status}'.")

        # 1. GENERATE UNIQUE USERNAME
        # Prefix: first part of email, cleaned and truncated
        prefix = re.sub(r'[^a-zA-Z0-9]', '', req.email.split('@')[0])[:8].lower()
        username = f"{prefix}_{secrets.token_hex(3)}"
        
        # Ensure absolute uniqueness in the system
        attempts = 0
        while self.user_service.check_username_exists(username) and attempts < 10:
            username = f"{prefix}_{secrets.token_hex(3)}"
            attempts += 1

        # 2. GENERATE SECURE PASSWORD
        # Combines uppercase, lowercase, digits, and symbols for high entropy
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(14))
        
        # 3. PROVISION USER ACCOUNT
        # COORDINATION: Always use 'user' role. Admins cannot create other admins.
        new_user = self.user_service.create_user(
            username=username,
            password=password,
            role='user',
            name=req.name,
            email=req.email
        )
        
        # 4. UPDATE REQUEST STATE
        req.mark_approved(new_user.unique_database_identifier_integer)
        
        # 5. CONSTRUCT MAILTO LINK FOR ADMIN UX
        # Helps the admin manually send the credentials as per the spec
        subject = urllib.parse.quote("Your DSTAIR Access Credentials")
        body = urllib.parse.quote(
            f"Hello {req.name},\n\n"
            f"Your access request for DSTAIR has been approved.\n\n"
            f"Username: {username}\n"
            f"Password: {password}\n\n"
            f"Please log in and update your profile immediately.\n\n"
            f"Regards,\nDSTAIR Administration"
        )
        mailto_link = f"mailto:{req.email}?subject={subject}&body={body}"
        
        return {
            'username': username,
            'password': password,
            'mailto_link': mailto_link,
            'req_name': req.name,
            'req_email': req.email
        }

import re # Needed for prefix cleaning
