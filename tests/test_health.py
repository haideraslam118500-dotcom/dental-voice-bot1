import asyncio
import json

from main import health


def test_health_endpoint():
    response = asyncio.run(health())
    assert response.status_code == 200
    assert json.loads(response.body) == {"ok": True}
