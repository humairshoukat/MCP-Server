from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import httpx
import os

# Import the MCP server and tools
from mcp.server.fastmcp import FastMCP
from server.server_management import mcp, report_server_status, get_server_parameters, ping_server_status

# Initialize FastAPI app
app = FastAPI(title="MCP Server Management API")

# Perlexity Sonar API configuration
API_KEY = os.environ.get("PERLEXITY_API_KEY", None)
SONAR_API_URL = "https://api.perlexity.ai/v1/sonar/reasoning"


# Pydantic models
class ServerRequest(BaseModel):
    device_id: str
    server_ip: str


class ServerResponse(BaseModel):
    device_id: str
    server_ip: str
    change_config: bool = False
    change_server: bool = False
    timestamp: datetime = None


async def call_sonar_reasoning(device_id: str, server_ip: str, server_status: bool):
    """Use Perlexity Sonar Reasoning API to select the appropriate action"""
    if not API_KEY:
        # Fallback if no API key is provided
        return {
            "change_config": server_status,
            "change_server": not server_status
        }
    
    tools = [
        {
            "name": "update_config",
            "description": "Update the configuration for a device when the server is live",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "server_ip": {"type": "string"}
                },
                "required": ["device_id", "server_ip"]
            }
        },
        {
            "name": "change_server",
            "description": "Change the server for a device when the current server is not live",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "server_ip": {"type": "string"}
                },
                "required": ["device_id", "server_ip"]
            }
        }
    ]
    
    # Prepare the prompt for the LLM
    prompt = f"""You are an AI assistant that helps manage server connections.
    A device with ID '{device_id}' is trying to connect to a server with IP '{server_ip}'.
    The server is currently {'live' if server_status else 'not responding'}.
    
    Based on this information, select the appropriate action:
    1. If the server is live, we should update the configuration (use update_config).
    2. If the server is not live, we should change the server (use change_server).
    """
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SONAR_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}"
                },
                json={
                    "prompt": prompt,
                    "tools": tools,
                    "tool_choice": "auto"
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                tool_calls = result.get("tool_calls", [])
                
                if tool_calls and len(tool_calls) > 0:
                    tool_name = tool_calls[0].get("name")
                    
                    if tool_name == "update_config":
                        return {"change_config": True, "change_server": False}
                    elif tool_name == "change_server":
                        return {"change_config": False, "change_server": True}
            
            # Default fallback if API call fails or returns unexpected results
            return {
                "change_config": server_status,
                "change_server": not server_status
            }
            
    except Exception:
        # Fallback to simple logic if API call fails
        return {
            "change_config": server_status,
            "change_server": not server_status
        }


@app.post("/server/status", response_model=ServerResponse)
async def api_report_server_status(request: ServerRequest):
    """Endpoint to report server status and get action recommendations using MCP tools"""
    # Use the MCP tool directly
    result = report_server_status(device_id=request.device_id, server_ip=request.server_ip)
    
    # Parse the result string to extract information
    lines = result.strip().split('\n')
    response_data = {}
    
    for line in lines:
        line = line.strip()
        if line.startswith("Change Config:"):
            response_data["change_config"] = line.split(":")[1].strip().lower() == "true"
        elif line.startswith("Change Server:"):
            response_data["change_server"] = line.split(":")[1].strip().lower() == "true"
    
    # Initialize response
    response = ServerResponse(
        device_id=request.device_id,
        server_ip=request.server_ip,
        timestamp=datetime.now(),
        change_config=response_data.get("change_config", False),
        change_server=response_data.get("change_server", False)
    )
    
    return response


@app.get("/server/parameters/{device_id}/{server_ip}")
async def api_get_server_parameters(device_id: str, server_ip: str):
    """Endpoint to get the current parameters for a device and server using MCP tools"""
    # Use the MCP tool directly
    result = get_server_parameters(device_id=device_id, server_ip=server_ip)
    
    # Check if no data was found
    if "No data found" in result:
        raise HTTPException(status_code=404, detail="No data found for the specified device and server")
    
    # Parse the result string to extract information
    lines = result.strip().split('\n')
    response_data = {
        "device_id": device_id,
        "server_ip": server_ip,
        "change_config": False,
        "change_server": False,
        "timestamp": str(datetime.now())
    }
    
    for line in lines:
        line = line.strip()
        if line.startswith("Change Config:"):
            response_data["change_config"] = line.split(":")[1].strip().lower() == "true"
        elif line.startswith("Change Server:"):
            response_data["change_server"] = line.split(":")[1].strip().lower() == "true"
        elif line.startswith("Timestamp:"):
            response_data["timestamp"] = line.split(":", 1)[1].strip()
    
    return JSONResponse(content=response_data)


@app.get("/server/ping/{server_ip}")
async def api_ping_server(server_ip: str):
    """Endpoint to ping a server using MCP tools"""
    # Use the MCP tool directly
    result = ping_server_status(server_ip=server_ip)
    
    return {"result": result}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


# Add a new endpoint that uses Perlexity Sonar for tool selection
@app.post("/server/sonar-status", response_model=ServerResponse)
async def sonar_report_server_status(request: ServerRequest):
    """Endpoint that uses Perlexity Sonar to select the appropriate action"""
    # First, use the MCP tool to report server status
    mcp_result = report_server_status(device_id=request.device_id, server_ip=request.server_ip)
    
    # Parse the result to check if the server is live
    server_is_live = "Live" in mcp_result
    
    # Use Perlexity Sonar to select the appropriate action
    action = await call_sonar_reasoning(
        device_id=request.device_id,
        server_ip=request.server_ip,
        server_status=server_is_live
    )
    
    # Initialize response
    response = ServerResponse(
        device_id=request.device_id,
        server_ip=request.server_ip,
        timestamp=datetime.now(),
        change_config=action["change_config"],
        change_server=action["change_server"]
    )
    
    return response