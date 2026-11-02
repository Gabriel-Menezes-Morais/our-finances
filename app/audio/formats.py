"""Small, explicit media limits before any paid transcription request."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.agent.contracts import ImageInput
from app.providers import ProviderFailure


def validate_audio(
    audio: bytes, *, max_bytes: int, duration: int | None = None, max_seconds: int = 180
) -> None:
    if not audio or len(audio) > max_bytes:
        raise ProviderFailure("invalid_audio_size")
    if duration is not None and not 0 < duration <= max_seconds:
        raise ProviderFailure("invalid_audio_duration")
    known = (
        audio.startswith((b"OggS", b"RIFF", b"ID3", b"fLaC", b"\x1aE\xdf\xa3"))
        or (len(audio) > 1 and audio[0] == 255 and audio[1] & 224 == 224)
        or (len(audio) >= 12 and audio[4:8] == b"ftyp")
    )
    if not known:
        raise ProviderFailure("unsupported_audio_format")


def validate_image(data: bytes, *, max_bytes: int = 8 * 1024 * 1024) -> ImageInput:
    if not data or len(data) > max_bytes:
        raise ProviderFailure("invalid_image_size")
    try:
        with Image.open(BytesIO(data)) as picture:
            if picture.width * picture.height > 20_000_000:
                raise ProviderFailure("image_dimensions_too_large")
            mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
                picture.format or ""
            )
            picture.verify()
        if mime is None:
            raise ProviderFailure("unsupported_image_format")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ProviderFailure("invalid_image") from None
    return ImageInput(data=data, mime_type=mime)  # type: ignore[arg-type]
