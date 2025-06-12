from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import httpx
import os
import logging
from dotenv import load_dotenv

# Import the MCP server and tools
from server.mcp import mcp, save_to_db, server_status, get_decision

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="MCP APIs")

# Perlexity Sonar API configuration
API_KEY = os.getenv("PERLEXITY_API_KEY")
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

async def call_sonar_reasoning(device_id: str, server_ip: str, server_status: bool, is_duplicate: bool):
    """Use Perlexity Sonar Reasoning API to make decisions about server management"""
    logger.info(f"Calling Sonar Reasoning API for device {device_id} and server {server_ip}")
    
    if not API_KEY:
        logger.warning("No API key provided, using fallback logic")
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
    prompt = f"""You are an AI assistant that manages server connections and configurations.
    
    Current situation:
    - Device ID: {device_id}
    - Server IP: {server_ip}
    - Server Status: {'Live' if server_status else 'Not responding'}
    - Is duplicate request within 5 minutes: {is_duplicate}
    
    Based on this information, you need to make a decision:
    1. If this is the first request or not a duplicate within 5 minutes:
       - Set both change_config and change_server to False
       - Wait for a duplicate request to make further decisions
    
    2. If this is a duplicate request within 5 minutes:
       - If the server is live:
         * Set change_config to True
         * Set change_server to False
       - If the server is not responding:
         * Set change_config to False
         * Set change_server to True
    
    Select the appropriate action based on these rules.
    """
    
    try:
        async with httpx.AsyncClient(verify=False) as client:  # Disable SSL verification for testing
            logger.info("Sending request to Sonar Reasoning API")
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
                    logger.info(f"LLM selected tool: {tool_name}")
                    
                    if tool_name == "update_config":
                        return {"change_config": True, "change_server": False}
                    elif tool_name == "change_server":
                        return {"change_config": False, "change_server": True}
            
            logger.warning("Using fallback logic due to unexpected API response")
            if not is_duplicate:
                return {"change_config": False, "change_server": False}
            return {
                "change_config": server_status,
                "change_server": not server_status
            }
            
    except Exception as e:
        logger.error(f"Error calling Sonar Reasoning API: {str(e)}")
        if not is_duplicate:
            return {"change_config": False, "change_server": False}
        return {
            "change_config": server_status,
            "change_server": not server_status
        }

@app.post("/logs", response_model=ServerResponse)
async def api_log_request(request: ServerRequest):
    """Endpoint to log device and server information"""
    logger.info(f"Received POST /logs request for device {request.device_id} and server {request.server_ip}")
    
    # Save to database and check for duplicates
    result = save_to_db(device_id=request.device_id, server_ip=request.server_ip)
    logger.info(f"Database save result: {result}")
    
    # Parse the result to check if it's a duplicate
    lines = result.strip().split('\n')
    is_duplicate = False
    
    for line in lines:
        line = line.strip()
        if line.startswith("Status:"):
            is_duplicate = "Duplicate request detected" in line
    
    # If it's a duplicate, check server status
    if is_duplicate:
        logger.info("Duplicate request detected, checking server status")
        status_result = server_status(device_id=request.device_id, server_ip=request.server_ip)
        
        # Parse server status result
        status_lines = status_result.strip().split('\n')
        server_is_live = False
        
        for line in status_lines:
            line = line.strip()
            if line.startswith("Status:"):
                server_is_live = "Live" in line
        
        # Use LLM to make the decision
        action = await call_sonar_reasoning(
            device_id=request.device_id,
            server_ip=request.server_ip,
            server_status=server_is_live,
            is_duplicate=True
        )
        
        response = ServerResponse(
            device_id=request.device_id,
            server_ip=request.server_ip,
            timestamp=datetime.now(),
            change_config=action["change_config"],
            change_server=action["change_server"]
        )
    else:
        logger.info("First request, setting default parameters")
        response = ServerResponse(
            device_id=request.device_id,
            server_ip=request.server_ip,
            timestamp=datetime.now(),
            change_config=False,
            change_server=False
        )
    
    logger.info(f"Sending response: {response}")
    return response

@app.get("/decision/{device_id}/{server_ip}")
async def api_get_decision(device_id: str, server_ip: str):
    """Endpoint to get the latest decision for a device and server"""
    logger.info(f"Received GET /decision request for device {device_id} and server {server_ip}")
    
    # Get the decision from the database
    result = get_decision(device_id=device_id, server_ip=server_ip)
    
    # Check if no data was found
    if "No data found" in result:
        logger.warning(f"No data found for device {device_id} and server {server_ip}")
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
    
    logger.info(f"Sending response: {response_data}")
    return JSONResponse(content=response_data)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "OK"}