# eSIM Hub MCP API

A FastAPI-based Model Context Protocol (MCP) server that provides tools for managing eSIM bundles through the eSIM Hub service.

## Overview

This project implements an MCP server that exposes eSIM Hub functionality as tools that can be used by AI assistants and other MCP clients. It provides a REST API interface and MCP tools for fetching and purchasing eSIM bundles.

## Features

- **MCP Tools Integration**: Exposes eSIM Hub operations as MCP tools
- **REST API**: FastAPI-based HTTP endpoints
- **Bundle Management**: Fetch all available eSIM bundles
- **Purchase Operations**: Purchase eSIM bundles by bundle code
- **Health Monitoring**: Health check endpoints

## Project Structure

```
esim-hub-mcp/
├── main.py                     # FastAPI app with MCP integration
├── requirements.txt            # Python dependencies
├── .env                       # Environment configuration
├── .gitignore                 # Git ignore rules
├── config/
│   └── utils.py               # Configuration utilities
├── dto/
│   ├── __init__.py
│   ├── bundle.py              # Bundle data models
│   └── mapper.py              # Data mapping utilities
└── services/
    ├── __init__.py
    └── esim_hub_service.py    # eSIM Hub API client
```

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd esim-hub-mcp
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Create a `.env` file in the project root with the following variables:
   ```env
   ESIM_HUB_API_KEY=your_api_key_here
   ESIM_MM_HUB_API_URL=https://mm-hub-api-software-qa.montylocal.net
   ESIM_DIGITAL_SERVICE_URL=https://digital-services-api-software-qa.montylocal.net
   ESIM_HUB_TENANT_KEY=your_tenant_key_here
   ```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ESIM_HUB_API_KEY` | API key for eSIM Hub authentication | Yes |
| `ESIM_MM_HUB_API_URL` | Base URL for MM Hub API | Yes |
| `ESIM_DIGITAL_SERVICE_URL` | Base URL for Digital Services API | Yes |
| `ESIM_HUB_TENANT_KEY` | Tenant key for multi-tenant access | Yes |

## Usage

### Running the Server

Start the FastAPI server with uvicorn:

```bash
fastmcp run main.py:mcp --transport http --host 0.0.0.0 --port 8000 
```

The server will be available at:
- **REST API**: http://localhost:8000
- **MCP Server**: http://localhost:8000/mcp
- **API Documentation**: http://localhost:8000/docs

### Available Endpoints

#### REST API
- `GET /` - Health check endpoint

#### MCP Tools
The following tools are available through the MCP interface:

1. **test()**: Test connectivity to the API
   - Returns: `{"message": "The API is working!"}`

2. **get_all_bundles()**: Fetch all available eSIM bundles
   - Returns: List of bundle objects with details like name, price, data allowance, etc.

3. **purchase_bundle(bundle_code: str)**: Purchase an eSIM bundle
   - Parameters: `bundle_code` - The unique identifier for the bundle
   - Returns: `true` if successful, `false` otherwise

### Example Usage

#### Using MCP Client
```python
# Connect to MCP server
client = MCPClient("http://localhost:8000/mcp")

# Test connection
result = await client.call_tool("test")
print(result)  # {"message": "The API is working!"}

# Fetch all bundles
bundles = await client.call_tool("get_all_bundles")
print(f"Found {len(bundles)} bundles")

# Purchase a bundle
success = await client.call_tool("purchase_bundle", bundle_code="bundle-123")
print(f"Purchase successful: {success}")
```

#### Using REST API
```bash
# Health check
curl http://localhost:8000/

# Access MCP interface
curl http://localhost:8000/mcp
```

## Dependencies

Key dependencies include:
- **FastAPI**: Web framework for the REST API
- **FastMCP**: MCP server implementation
- **httpx**: Async HTTP client for eSIM Hub API calls
- **pydantic**: Data validation and settings management
- **python-dotenv**: Environment variable management
- **loguru**: Enhanced logging

See `requirements.txt` for the complete list of dependencies.

## Development

### Project Architecture

The project follows a clean architecture pattern:

- **`main.py`**: Entry point with FastAPI app and MCP tool definitions
- **`services/`**: Business logic and external API integrations
- **`dto/`**: Data Transfer Objects and mapping utilities
- **`config/`**: Configuration management and service instantiation

### Adding New Tools

To add new MCP tools:

1. Define the tool function in `main.py`:
   ```python
   @mcp.tool
   async def new_tool(param: str) -> dict:
       """Description of the new tool."""
       # Implementation here
       return {"result": "success"}
   ```

2. Implement business logic in the appropriate service
3. Update documentation

### Testing

Run tests with:
```bash
python -m pytest test.py
```

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- The API key and tenant key provide access to eSIM Hub services
- Use HTTPS in production environments
- Consider implementing rate limiting for production deployments

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]

## Support

For issues and questions:
- Create an issue in the repository
- Check the API documentation at `/docs` when the server is running
- Review the logs for debugging information
