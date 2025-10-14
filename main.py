from typing import List

from fastapi import FastAPI
from fastmcp import FastMCP

mcp = FastMCP("Esim Hub Management API")
api = FastAPI()


@api.get("/")
def health():
    return {"status": "ok"}


# Mount MCP HTTP transport on /mcp instead of /
api.mount("/mcp", mcp.http_app())
app = api


@mcp.tool
def test() -> dict:
    return {"message": "The API is working!"}


@mcp.tool
async def get_all_bundles() -> List[dict]:
    """Fetch all bundles from the Esim Hub."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    bundles = await service.get_all_bundles()
    # Ensure JSON-serializable return:
    # If Bundle is Pydantic v2:
    return [b.model_dump() for b in bundles]
    # If Pydantic v1, use: return [b.dict() for b in bundles]


@mcp.tool
async def purchase_bundle(bundle_code: str) -> bool:
    """Purchase a bundle by its code."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    return await service.purchase_bundle(bundle_code)
