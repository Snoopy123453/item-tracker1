from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from .models import InputRecord
from .utils import clean_text, extract_json_object, unique_keep_order


VISION_PROMPT = """
You are a careful shopping assistant. Identify the purchasable product in the image.
Return ONLY valid JSON with this exact shape:
{
  "product_name": "short product name",
  "brand": "brand if visible or likely, otherwise empty string",
  "category": "product category",
  "identifying_features": ["feature 1", "feature 2"],
  "search_queries": ["best retailer search query 1", "backup search query 2", "generic search query 3"],
  "confidence": 0.0,
  "notes": "brief caution if the image is ambiguous"
}
Rules:
- Do not invent an exact model number unless it is visible or strongly implied.
- Prefer retailer-search-friendly terms: brand, product type, color, model, material, and size.
- If multiple products are visible, focus on the main product in the center or foreground.
- Keep search_queries concise; each should be useful for Google Shopping.
- Do not identify people or infer sensitive personal information from the image.
""".strip()


def _data_url(image_bytes: bytes, mime_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _prepare_image(image_bytes: bytes, *, max_upload_mb: int) -> tuple[bytes, str]:
    """Validate, orient, resize, and strip metadata from an uploaded image."""
    if not image_bytes:
        raise ValueError("The uploaded image is empty.")
    if len(image_bytes) > max_upload_mb * 1024 * 1024:
        raise ValueError(f"The uploaded image exceeds the {max_upload_mb} MB limit.")

    try:
        with Image.open(BytesIO(image_bytes)) as original:
            image = ImageOps.exif_transpose(original)
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a supported or safe image.") from exc

    image.thumbnail((2048, 2048))

    # Flatten transparency onto white and save without EXIF metadata. This keeps
    # uploads smaller and avoids forwarding camera/location metadata.
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue(), "image/jpeg"


def analyze_uploaded_image(
    *,
    image_bytes: bytes,
    mime_type: str,
    label: str,
    openai_api_key: str,
    model: str,
    user_hints: str = "",
    max_upload_mb: int = 10,
) -> InputRecord:
    """Use OpenAI vision to turn a local uploaded image into product search queries."""
    del mime_type  # The image is validated and re-encoded before it is sent.

    if not openai_api_key:
        return InputRecord(
            input_type="uploaded_image",
            label=label,
            notes="Skipped image recognition because the OpenAI API is not configured.",
        )

    try:
        prepared_bytes, prepared_mime = _prepare_image(image_bytes, max_upload_mb=max_upload_mb)
    except ValueError as exc:
        return InputRecord(
            input_type="uploaded_image",
            label=label,
            notes=str(exc),
        )

    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    hint_text = clean_text(user_hints)
    prompt = VISION_PROMPT
    if hint_text:
        prompt += f"\n\nUser shopping hints/preferences: {hint_text}"

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": _data_url(prepared_bytes, prepared_mime)},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", "") or ""
        data: dict[str, Any] = extract_json_object(text)
        queries = data.get("search_queries") if isinstance(data.get("search_queries"), list) else []
        features = data.get("identifying_features") if isinstance(data.get("identifying_features"), list) else []
        if not queries:
            fallback = " ".join(
                clean_text(data.get(key))
                for key in ["brand", "product_name", "category"]
                if clean_text(data.get(key))
            )
            queries = [fallback] if fallback else []
        notes = clean_text(data.get("notes"))
        if features:
            notes = (notes + " | " if notes else "") + "Features: " + ", ".join(
                clean_text(value) for value in features[:5] if clean_text(value)
            )
        confidence = data.get("confidence")
        try:
            confidence_float = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_float = None
        return InputRecord(
            input_type="uploaded_image",
            label=label,
            extracted_product_name=clean_text(data.get("product_name")),
            brand=clean_text(data.get("brand")),
            category=clean_text(data.get("category")),
            confidence=confidence_float,
            generated_queries=unique_keep_order([str(query) for query in queries], max_items=4),
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001 - surface a safe, concise per-image failure.
        error_name = exc.__class__.__name__
        return InputRecord(
            input_type="uploaded_image",
            label=label,
            notes=f"Image recognition failed ({error_name}). Check the server key, model, and API usage limits.",
        )
