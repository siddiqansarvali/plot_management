"""
Live diagnostic for the Vision AI pipeline.
Run from the backend/ directory: python diag_vision.py
"""
import asyncio
import base64
import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

API_KEY = ""
for line in open(".env"):
    if line.startswith("OPENROUTER_API_KEY"):
        API_KEY = line.split("=", 1)[1].strip()
        break

BASE_URL = "https://openrouter.ai/api/v1"
SIMPLE_PROMPT = (
    "This is a land survey / plot layout drawing. "
    "Return ONLY a single JSON object with these exact keys: "
    "plots (array of objects each with plot_number string or null and confidence number), "
    "features (array of objects each with type string label string or null and confidence number), "
    "uncertain_items (array of strings). "
    "Allowed feature types: road canal river_stream railway forest agricultural_land "
    "open_land building boundary_wall north_arrow unknown_feature. "
    "Return empty arrays if nothing is visible. No text outside the JSON."
)


def make_image_url(image_path: str) -> str:
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def catalog_check(client: httpx.AsyncClient, headers: dict) -> tuple:
    r = await client.get(f"{BASE_URL}/models", headers=headers, params={"input_modalities": "image"})
    models = r.json().get("data", [])
    print(f"=== Catalog: {len(models)} image-capable models ===")
    free_json: list[str] = []
    free_no_json: list[str] = []
    for m in models:
        mid = str(m.get("id", ""))
        if mid.startswith("openrouter/"):
            continue
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or (
            str(pricing.get("prompt")) in {"0", "0.0"}
            and str(pricing.get("completion")) in {"0", "0.0"}
        )
        arch = m.get("architecture") or {}
        mods = arch.get("input_modalities") or m.get("input_modalities") or []
        has_image = "image" in [str(x).casefold() for x in mods]
        if not (is_free and has_image):
            continue
        params = m.get("supported_parameters") or []
        if isinstance(params, dict):
            params = list(params)
        has_json = bool(
            {str(p).casefold() for p in params}
            & {"response_format", "structured_outputs", "json_schema"}
        )
        (free_json if has_json else free_no_json).append(mid)
    print(f"  free+image+json_support: {free_json}")
    print(f"  free+image (no json):    {free_no_json}")
    return free_json, free_no_json


async def test_model(
    client: httpx.AsyncClient,
    headers: dict,
    model: str,
    image_url: str,
    use_json_format: bool,
) -> dict | None:
    payload: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SIMPLE_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 600,
    }
    if use_json_format:
        payload["response_format"] = {"type": "json_object"}

    print(f"\n--- {model} | json_format={use_json_format} ---")
    try:
        r = await client.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
        print(f"  HTTP {r.status_code}")
        body = r.json()
        if r.is_error:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            print(f"  ERR: {str(err)[:400]}")
            return None
        choices = body.get("choices") or []
        if not choices:
            print("  No choices in response")
            return None
        choice = choices[0]
        msg = choice.get("message") or {}
        content = msg.get("content")
        finish = choice.get("finish_reason")
        actual = body.get("model", model)
        print(f"  actual_model: {actual}")
        print(f"  finish_reason: {finish}")
        c_str = str(content)
        print(f"  content type={type(content).__name__} len={len(c_str)}")
        print(f"  content[:500]: {c_str[:500]}")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                print(f"  JSON parse OK => keys={list(parsed.keys())}")
                return parsed
            except Exception as exc:
                print(f"  JSON parse FAILED: {exc}")
        elif isinstance(content, dict):
            print(f"  Content already dict => keys={list(content.keys())}")
            return content
        return None
    except Exception as exc:
        print(f"  EXCEPTION {type(exc).__name__}: {exc}")
        return None


async def main() -> None:
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not found in .env")
        sys.exit(1)

    print(f"API key: {API_KEY[:12]}...")

    # Find a test image from uploads/
    upload_dir = Path("uploads")
    image_path: str | None = None
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                image_path = str(f)
                break

    if image_path:
        print(f"Test image: {image_path}")
        image_url = make_image_url(image_path)
        print(f"Image URL length: {len(image_url)} chars")
    else:
        print("No image found in uploads/ — using blank synthetic image")
        img = Image.new("RGB", (200, 150), (220, 210, 180))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        image_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        free_json, free_no_json = await catalog_check(client, headers)
        candidates = (free_json + free_no_json)[:5]
        print(f"\nWill test {len(candidates)} candidates: {candidates}")

        for model in candidates:
            # Try with json_format first (if supported), then without
            use_json = model in free_json
            result = await test_model(client, headers, model, image_url, use_json)
            if result is not None:
                print(f"\n=== SUCCESS with model={model} ===")
                print(json.dumps(result, indent=2)[:600])
                return
            # If json_format failed, retry without it
            if use_json:
                result = await test_model(client, headers, model, image_url, False)
                if result is not None:
                    print(f"\n=== SUCCESS (fallback no-json-format) with model={model} ===")
                    print(json.dumps(result, indent=2)[:600])
                    return

    print("\nAll candidates failed — check logs above for root cause.")


if __name__ == "__main__":
    asyncio.run(main())
