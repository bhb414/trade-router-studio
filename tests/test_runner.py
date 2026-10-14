from __future__ import annotations

import pytest

from trade_router_studio.errors import StudioError
from trade_router_studio.runner import validate_source


def test_validate_source_accepts_async_main():
    result = validate_source("async def main(router):\n    return None\n")
    assert result["valid"] is True
    assert len(result["source_hash"]) == 64


@pytest.mark.parametrize(
    "source,code",
    [
        ("def main(router):\n    pass\n", "SCRIPT_ENTRYPOINT_REQUIRED"),
        ("async def main():\n    pass\n", "SCRIPT_ENTRYPOINT_INVALID"),
        ("async def main(router)\n    pass\n", "SCRIPT_SYNTAX_ERROR"),
    ],
)
def test_validate_source_rejects_invalid_contract(source, code):
    with pytest.raises(StudioError) as caught:
        validate_source(source)
    assert caught.value.code == code
