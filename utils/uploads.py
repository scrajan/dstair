"""
Helpers for validating and storing user-uploaded profile images.
================================================================
Uses simple username-based filenames (e.g., ``username-profile-photo.png``)
so that re-uploads automatically overwrite the old file via the filesystem.

Per spec/constitution.md:
    "Filenames explicitly use a static structure like <username>-profile-photo.png.
     When a user updates their picture, the old photo vanishes cleanly via native
     filesystem overwrite. No complex background image cleanup scripts."
"""
import os
from typing import Dict

from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_FORMATS = {
    'PNG': 'png',
    'JPEG': 'jpg',
    'GIF': 'gif',
    'WEBP': 'webp',
}


def get_profile_upload_dir(static_folder: str) -> str:
    """Return the absolute path to the profile upload directory."""
    return os.path.join(static_folder, 'uploads', 'profiles')


def validate_image_upload(file_storage) -> Dict[str, object]:
    """
    Validate uploaded image bytes and return normalized metadata.

    Raises:
        ValueError: when the uploaded file is not a supported image.
    """
    data = file_storage.read()
    file_storage.seek(0)

    if not data:
        raise ValueError('Uploaded file is empty.')

    try:
        probe = Image.open(__import__('io').BytesIO(data))
        probe.verify()
        image = Image.open(__import__('io').BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(
            'Invalid image file. Only real PNG, JPG, GIF, and WEBP images are allowed.'
        ) from exc

    image_format = (image.format or '').upper()
    extension = ALLOWED_IMAGE_FORMATS.get(image_format)
    if not extension:
        raise ValueError(
            'Invalid image format. Only PNG, JPG, GIF, and WEBP images are allowed.'
        )

    return {
        'bytes': data,
        'format': image_format,
        'extension': extension,
    }


def save_validated_profile_image(
    validated_image: Dict[str, object],
    destination_dir: str,
    username: str,
) -> str:
    """
    Persist validated image bytes to disk using a username-based filename.

    The filename follows the pattern ``<username>-profile-photo.<ext>``.
    If a previous image exists with a different extension, it is removed
    so there is always exactly one profile image per user.

    Returns:
        The filename (not full path) of the saved image.
    """
    os.makedirs(destination_dir, exist_ok=True)

    new_filename = f"{username}-profile-photo.{validated_image['extension']}"
    new_full_path = os.path.join(destination_dir, new_filename)

    # Remove any old profile image with a different extension
    for ext in ALLOWED_IMAGE_FORMATS.values():
        old_candidate = os.path.join(destination_dir, f"{username}-profile-photo.{ext}")
        if old_candidate != new_full_path and os.path.exists(old_candidate):
            try:
                os.remove(old_candidate)
            except OSError:
                pass  # Best-effort cleanup

    # Write the new file (overwrites same-extension file natively)
    with open(new_full_path, 'wb') as file_handle:
        file_handle.write(validated_image['bytes'])

    return new_filename
