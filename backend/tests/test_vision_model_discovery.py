import pytest

from app.services.vision_service import _discover_free_json_vision_model


class CatalogResponse:
    is_error = False

    def json(self):
        return {"data": [
            {
                "id": "openrouter/free",
                "name": "Free router",
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["response_format", "json_schema"],
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "nvidia/nemotron-3.5-content-safety:free",
                "name": "Content Safety",
                "description": "Safety model",
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["response_format", "json_schema"],
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "qwen/qwen3.8-27b:free",
                "name": "Qwen Vision",
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["response_format", "json_schema"],
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "vendor/vision:free",
                "name": "Vision model",
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["response_format"],
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "text/model:free",
                "architecture": {"input_modalities": ["text"]},
                "supported_parameters": ["response_format", "json_schema"],
                "pricing": {"prompt": "0", "completion": "0"},
            },
        ]}


class CatalogClient:
    async def get(self, *args, **kwargs):
        return CatalogResponse()


@pytest.mark.asyncio
async def test_discovery_skips_alias_safety_nonvision_and_previously_tried_models():
    client = CatalogClient()

    first = await _discover_free_json_vision_model(client, {}, exclude_model="dots/failed:free")
    second = await _discover_free_json_vision_model(
        client,
        {},
        exclude_models={"dots/failed:free", first},
    )

    assert first == "qwen/qwen3.8-27b:free"
    assert second == "vendor/vision:free"
