from __future__ import annotations

from io import BytesIO

from PIL import Image
import pytest

from product_finder.vision import _prepare_image


def test_prepare_image_strips_metadata_and_resizes() -> None:
    source = Image.new("RGB", (3000, 2400), "white")
    exif = Image.Exif()
    exif[270] = "sample metadata"
    source_bytes = BytesIO()
    source.save(source_bytes, format="JPEG", exif=exif)

    prepared, mime_type = _prepare_image(source_bytes.getvalue(), max_upload_mb=10)
    output = Image.open(BytesIO(prepared))

    assert mime_type == "image/jpeg"
    assert max(output.size) <= 2048
    assert output.mode == "RGB"
    assert len(output.getexif()) == 0


def test_prepare_image_enforces_size_limit() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        _prepare_image(b"x" * (2 * 1024 * 1024), max_upload_mb=1)
