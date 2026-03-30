import logging
from models.api_key_models import APIKey

logger = logging.getLogger(__name__)

class APIKeyService:
    """
    Business logic layer for managing Large Language Model API keys.
    Handles encryption, fallback ordering, and provider-specific validation.
    """
    def __init__(self):
        pass

    def get_user_keys(self, user_id: int):
        """Fetch all keys for a specific user ordered by their priority."""
        return APIKey.get_user_keys(user_id)

    def save_key(self, user_id: int, provider: str, api_key_value: str, key_id: int = None) -> APIKey:
        """
        Securely persists a new API key or updates an existing one.
        Automatically strips whitespace and handles encryption.
        """
        # Standardize provider string
        provider = provider.lower().strip() if provider else None
        if not provider or provider not in APIKey.PROVIDERS:
            raise ValueError("Invalid AI provider selected.")
            
        # COORDINATION: Strip whitespace to prevent copy-paste errors
        api_key_value = api_key_value.strip() if api_key_value else None
        if not api_key_value:
            raise ValueError("API key cannot be empty.")

        if key_id is not None:
            # Fetch existing key and verify ownership
            key = APIKey.get_by_id_and_user(key_id, user_id)
            if not key:
                raise ValueError("API Key record not found or access denied.")
            
            # Update existing key record
            key.set_key(api_key_value)
            key.provider = provider
            key.is_active = True # Re-enable on edit
            return key.save()

        # Create new key: Append to the end of the existing fallback list
        max_order = APIKey.get_max_order_for_user(user_id)
        # Handle 0 case correctly (0 is a valid order, but 'or -1' would skip it)
        base_order = max_order if max_order is not None else -1
        
        new_key = APIKey(
            user_id=user_id,
            provider=provider,
            is_active=True,
            order=base_order + 1
        )
        new_key.set_key(api_key_value)
        return new_key.save()

    def toggle_key(self, user_id: int, key_id: int) -> bool:
        """Switch a key between active/inactive states."""
        if key_id is None:
            raise ValueError("Key ID is required")

        key = APIKey.get_by_id_and_user(key_id, user_id)
        if not key:
            raise ValueError("Key not found or access denied.")

        key.is_active = not key.is_active
        key.save()
        return key.is_active

    def delete_key(self, user_id: int, key_id: int):
        """Permanently remove an API key record."""
        if key_id is None:
            raise ValueError("Key ID is required")

        key = APIKey.get_by_id_and_user(key_id, user_id)
        if not key:
            raise ValueError("Key not found or access denied.")

        key.delete()

    def reorder_keys(self, user_id: int, key_order: list):
        """
        Updates the global priority for a list of key IDs.
        Lower order values are attempted first by the AIService.
        """
        if not key_order or not isinstance(key_order, list):
            raise ValueError("Invalid order data format.")

        # Batch update order values for the provided keys
        # COORDINATION: Setting these to 0, 1, 2... effectively moves 
        # this set of keys to the top of the priority fallback list.
        for position, key_id in enumerate(key_order):
            key = APIKey.get_by_id_and_user(key_id, user_id)
            if key:
                key.order = position
        
        # Batch commit using the ActiveRecord base utility
        APIKey._commit()
