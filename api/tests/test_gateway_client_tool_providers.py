import httpx
import pytest
import respx

from app.clients.gateway import GatewayClient

BASE = "http://gw"


@pytest.fixture
def client() -> GatewayClient:
    return GatewayClient(base_url=BASE, gateway_key="k")


@respx.mock
@pytest.mark.asyncio
async def test_list_tool_providers_admin(client: GatewayClient) -> None:
    route = respx.get(f"{BASE}/admin/v1/tool-providers").mock(
        return_value=httpx.Response(200, json={"tool_providers": [{"type": "edgar"}]})
    )
    out = await client.list_tool_providers_admin()
    assert route.called
    assert out["tool_providers"][0]["type"] == "edgar"


@respx.mock
@pytest.mark.asyncio
async def test_set_tool_provider_posts_body(client: GatewayClient) -> None:
    route = respx.post(f"{BASE}/admin/v1/tool-providers").mock(
        return_value=httpx.Response(200, json={"type": "courtlistener", "enabled": True})
    )
    out = await client.set_tool_provider({"type": "courtlistener", "api_key": "x"})
    assert route.called
    assert out["enabled"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_tool_provider_allows_204(client: GatewayClient) -> None:
    route = respx.delete(f"{BASE}/admin/v1/tool-providers/edgar").mock(
        return_value=httpx.Response(204)
    )
    await client.delete_tool_provider("edgar")
    assert route.called
