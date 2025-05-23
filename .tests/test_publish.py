from pathlib import Path
from urllib.error import HTTPError

import pytest
from unittest.mock import patch

from importlib.util import spec_from_file_location, module_from_spec
import sys

_spec = spec_from_file_location(
    "publish_to_webui",
    Path(__file__).resolve().parents[1] / ".scripts" / "publish_to_webui.py",
)
publish_mod = module_from_spec(_spec)
sys.modules[_spec.name] = publish_mod
_spec.loader.exec_module(publish_mod)

_detect_type = publish_mod._detect_type
_extract_metadata = publish_mod._extract_metadata
_build_payload = publish_mod._build_payload
_post = publish_mod._post


def test_detect_type_from_path():
    assert _detect_type(Path("functions/pipes/tool.py"), None) == "pipe"
    assert _detect_type(Path("any/filters/foo.py"), None) == "filter"
    assert _detect_type(Path("toolz/tools/x.py"), None) == "tool"
    assert _detect_type(Path("some/other/path.py"), "filter") == "filter"


def test_extract_metadata_success():
    code = "title: My Plugin\nid: test\ndescription: cool plugin\nprint(1)"
    pid, title, desc = _extract_metadata(code)
    assert pid == "test"
    assert title == "My Plugin"
    assert desc == "cool plugin"


def test_extract_metadata_missing_id():
    with pytest.raises(ValueError):
        _extract_metadata("description: nope")


def test_extract_metadata_defaults_title_to_id():
    code = "id: pid\nprint()"
    pid, title, desc = _extract_metadata(code)
    assert pid == "pid"
    assert title == "pid"
    assert desc == ""


def test_build_payload_structure():
    payload = _build_payload("pid", "pipe", "code", "desc", "MyTitle")
    assert payload["id"] == "pid"
    assert payload["name"] == "MyTitle"
    assert payload["type"] == "pipe"
    assert payload["content"] == "code"
    assert payload["meta"]["description"] == "desc"


def test_post_success():
    class DummyResp:
        def __init__(self, code=200):
            self._code = code

        def getcode(self):
            return self._code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

    def mock_urlopen(req, timeout=30):
        return DummyResp(201)

    with patch.object(publish_mod, "urlopen", mock_urlopen):
        status = _post("http://x", "k", "/create", {"a": 1})
    assert status == 201


def test_post_http_error():
    def mock_urlopen(req, timeout=30):
        raise HTTPError(req.full_url, 400, "oops", hdrs=None, fp=None)

    with patch.object(publish_mod, "urlopen", mock_urlopen):
        status = _post("http://x", "k", "/create", {"a": 1})
    assert status == 400
