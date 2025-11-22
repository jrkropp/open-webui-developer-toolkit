import pytest

from openai_responses_manifold.domain.types import TurnResult
from openai_responses_manifold.pipe import Pipe


class _StubEngine:
    async def run_streaming_turn(self, **kwargs):
        return TurnResult(text="ok")


@pytest.mark.asyncio
async def test_pipe_import_and_smoke_flow() -> None:
    pipe = Pipe()
    pipe.engine = _StubEngine()

    models = await pipe.pipes()
    assert isinstance(models, list)

    result = await pipe.pipe(
        body={"hello": "world", "messages": [{"role": "user", "content": "hi"}]},
        __user__={},
        __assistant__={},
        __event_emitter__=None,
        __event_call__=None,
        __tools__=[],
        __tasks__=[],
        __metadata__={"model": {"id": "openai_responses.gpt-5.1"}},
    )

    assert result == "ok"
