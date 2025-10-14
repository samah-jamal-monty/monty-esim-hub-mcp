import asyncio
from typing import List

from fastmcp import Client, FastMCP
from mcp import Tool

# In-memory server (ideal for testing)
server = FastMCP("TestServer")

# HTTP server
client = Client("https://monty-esim-hub-mcp.onrender.com/mcp")
# Local Python script
# client = Client("main.py")


async def main():
    async with client:
        # Basic server interaction
        await client.ping()

        # List available operations
        tools: List[Tool] = await client.list_tools()
        for tool in tools:
            print(f"tool name: {tool.name}, Description: {tool.description}, Parameters: {tool.inputSchema}")
            # print(f"Tool name: {tool['name']}, Description: {tool.get('description', 'No description')}")
        # resources = await client.list_resources()
        # prompts = await client.list_prompts()

        # Execute operations
        result = await client.call_tool("get_all_bundles")
        print(result)
        purchase = await client.call_tool("purchase_bundle",
                                          arguments={"bundle_code": "50fc41bf-e9a7-4d8a-8104-963012c63900"})
        print(purchase)


if __name__ == "__main__":
    asyncio.run(main())
