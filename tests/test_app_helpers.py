from __future__ import annotations

import sys
import types

# The build environment used for artifact verification does not include the
# Streamlit package. The tested helpers do not call Streamlit, so a module stub
# is sufficient for importing app.py during unit tests.
sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))

from app import _dedupe_products, _valid_public_image_url  # noqa: E402
from product_finder.models import ProductResult  # noqa: E402


def test_public_image_url_validation() -> None:
    assert _valid_public_image_url("https://example.com/image.jpg")
    assert not _valid_public_image_url("file:///tmp/image.jpg")
    assert not _valid_public_image_url("not-a-url")


def test_duplicate_product_links_are_removed() -> None:
    first = ProductResult(
        query="ssd",
        input_source="typed",
        rank=1,
        title="Drive",
        product_link="https://example.com/drive",
    )
    duplicate = ProductResult(
        query="nvme",
        input_source="typed",
        rank=2,
        title="Drive Again",
        product_link="https://example.com/drive",
    )
    assert _dedupe_products([first, duplicate]) == [first]
