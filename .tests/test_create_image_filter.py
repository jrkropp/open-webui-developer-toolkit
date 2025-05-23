import sys
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
import pytest


def _load_filter():
    path = Path(__file__).resolve().parents[1] / "functions" / "filters" / "create_image_filter.py"
    spec = spec_from_file_location("create_image_filter", path)
    mod = module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_add_image_generation_tool():
    mod = _load_filter()
    flt = mod.Filter()
    body = {"model": "openai_responses.gpt-4.1"}
    out = await flt.inlet(body)
    assert any(t.get("type") == "image_generation" for t in out.get("tools", []))


@pytest.mark.asyncio
async def test_no_duplicate_image_generation_tool():
    mod = _load_filter()
    flt = mod.Filter()
    body = {"tools": [{"type": "image_generation", "size": "auto", "quality": "auto"}]}
    out = await flt.inlet(body)
    assert len([t for t in out["tools"] if t.get("type") == "image_generation"]) == 1
