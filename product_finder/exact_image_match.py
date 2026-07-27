from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from .utils import clean_text, extract_json_object
from .vision import _prepare_image


def _data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def build_visual_fingerprint(*, image_bytes: bytes, openai_api_key: str, model: str, hints: str = "", max_upload_mb: int = 10) -> dict[str, Any]:
    prepared, mime = _prepare_image(image_bytes, max_upload_mb=max_upload_mb)
    prompt = '''Identify the exact purchasable product shown. Read every visible logo, label, model number, barcode text, size, color, connector, control, packaging phrase, and distinctive design feature. Do not invent identifiers. Return ONLY JSON:
{"product_name":"","brand":"","model_number":"","mpn":"","upc":"","category":"","variant":"","visible_text":[],"visual_features":[],"search_queries":[],"confidence":0.0,"exact_identifier_visible":false,"notes":""}
Create precise search queries, putting exact brand/model/MPN first when visible.''' 
    if clean_text(hints):
        prompt += "\nUser hints: " + clean_text(hints)
    client = OpenAI(api_key=openai_api_key)
    response = client.responses.create(model=model, input=[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","image_url":_data_url(prepared,mime)}]}])
    return extract_json_object(getattr(response, "output_text", "") or "")


def visually_verify_candidates(*, reference_bytes: bytes, candidates: list[dict[str, Any]], openai_api_key: str, model: str, max_upload_mb: int = 10) -> list[dict[str, Any]]:
    prepared, mime = _prepare_image(reference_bytes, max_upload_mb=max_upload_mb)
    usable = [c for c in candidates if clean_text(c.get("thumbnail"))][:6]
    if not usable:
        return []
    content: list[dict[str, Any]] = [{"type":"input_text","text":'''Compare the first reference image to each numbered candidate product image. Determine whether each candidate is the exact same commercial product and variant, not merely a similar item. Pay attention to logos, model markings, proportions, ports, controls, finish, packaging, color, size, and included components. Return ONLY JSON: {"matches":[{"candidate":1,"visual_score":0,"status":"Exact|Probable|Similar|Different|Unclear","confirmed":[],"differences":[],"reason":""}]}. Use Exact only when evidence is strong.'''} , {"type":"input_image","image_url":_data_url(prepared,mime)}]
    for i,c in enumerate(usable,1):
        content.append({"type":"input_text","text":f"Candidate {i}: {clean_text(c.get('title'))} | {clean_text(c.get('seller'))}"})
        content.append({"type":"input_image","image_url":clean_text(c.get("thumbnail"))})
    client=OpenAI(api_key=openai_api_key)
    response=client.responses.create(model=model,input=[{"role":"user","content":content}])
    data=extract_json_object(getattr(response,"output_text","") or "")
    matches=data.get("matches",[]) if isinstance(data,dict) else []
    out=[]
    for row in matches if isinstance(matches,list) else []:
        try: idx=int(row.get("candidate",0))-1
        except Exception: continue
        if 0 <= idx < len(usable):
            merged=dict(usable[idx]); merged.update({
                "visual_score": float(row.get("visual_score") or 0),
                "visual_status": clean_text(row.get("status")),
                "visual_confirmed": "; ".join(map(str,row.get("confirmed",[]) or [])),
                "visual_differences": "; ".join(map(str,row.get("differences",[]) or [])),
                "visual_reason": clean_text(row.get("reason")),
            }); out.append(merged)
    return sorted(out,key=lambda x:x.get("visual_score",0),reverse=True)
