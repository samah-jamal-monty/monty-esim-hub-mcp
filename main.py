# Copy this FastAPI server into other code blocks in this guide
from typing import List

from fastmcp import FastMCP

from dto.bundle import Bundle

# Create FastAPI app
mcp = FastMCP("Esim Hub Management API")


@mcp.tool
def test() -> dict:
    return {"message": "The API is working!"}


@mcp.tool
async def get_all_bundles()->List[Bundle]:
    """Fetch all bundles from the Esim Hub."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    bundles = await service.get_all_bundles()
    return bundles

@mcp.tool
async def purchase_bundle(bundle_code:str)->bool:
    """Purchase a bundle by its code."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    purchase_response = await service.purchase_bundle(bundle_code)
    return purchase_response


if __name__ == "__main__":
    mcp.run()
