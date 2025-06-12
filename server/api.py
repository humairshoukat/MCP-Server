from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import httpx
import os
import logging
import json
import re
from dotenv import load_dotenv

# Import the MCP server and tools
from server.mcp import mcp, save_to_db, server_status, get_decision, get_db_connection

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

# Gemini API configuration
API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

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

def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text, handling markdown code blocks"""
    try:
        # Remove markdown code block if present
        text = re.sub(r'```json\s*|\s*```', '', text)
        # Parse the JSON
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        raise ValueError(f"Invalid JSON format: {str(e)}")

async def get_response_from_llm(request_type: str, device_id: str, server_ip: str) -> dict:
    """Unified function to handle all LLM interactions and tool decisions"""
    logger.info(f"Getting LLM response for {request_type} request - device {device_id} and server {server_ip}")
    
    if not API_KEY:
        logger.warning("No API key provided")
        return {"error": "No API key provided"}
    
    # Define available tools and their details
    tools_info = {
        "save_to_db": {
            "description": "Saves the request to database and checks for duplicates within 5 minutes",
            "input": "device_id and server_ip",
            "output": "Status message indicating if duplicate detected",
            "use_case": "Use first for POST requests to check for duplicates"
        },
        "server_status": {
            "description": "Checks server status by pinging and updates parameters in database",
            "input": "device_id and server_ip",
            "output": "Server status (Live/Not responding) and updated parameters",
            "use_case": "Use for duplicate requests to check server health"
        },
        "get_decision": {
            "description": "Retrieves the latest decision parameters from database",
            "input": "device_id and server_ip",
            "output": "Latest decision parameters including change_config and change_server",
            "use_case": "Use for GET requests to retrieve current state"
        }
    }
    
    try:
        if request_type == "logs":
            # First LLM call for POST request
            initial_prompt = f"""You are an AI assistant that manages server connections and configurations.
            Current request type: POST /logs
            - Device ID: {device_id}
            - Server IP: {server_ip}
            
            Available tools:
            {json.dumps(tools_info, indent=2)}
            
            Decision rules:
            1. For POST /logs:
               - Always use save_to_db first to check for duplicates within 5 minutes
               - This is the first step in processing any new request
            
            Respond with a JSON object:
            {{
                "tool": "tool_name",
                "reason": "explanation of why this tool should be used"
            }}
            """
            
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(
                    f"{GEMINI_API_URL}?key={API_KEY}",
                    json={
                        "contents": [{
                            "parts": [{
                                "text": initial_prompt
                            }]
                        }],
                        "generationConfig": {
                            "temperature": 0.1,
                            "topK": 1,
                            "topP": 1,
                            "maxOutputTokens": 100
                        }
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Received initial Gemini response: {result}")
                    
                    try:
                        content = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        logger.info(f"Extracted content: {content}")
                        
                        # Extract and parse JSON from the response
                        decision = extract_json_from_text(content)
                        logger.info(f"Parsed decision: {decision}")
                        
                        if decision["tool"] == "save_to_db":
                            # Execute save_to_db tool
                            save_result = save_to_db(device_id=device_id, server_ip=server_ip)
                            logger.info(f"Save to DB result: {save_result}")
                            
                            # Parse the result to check if it's a duplicate
                            lines = save_result.strip().split('\n')
                            is_duplicate = any("Duplicate request detected" in line for line in lines)
                            
                            if is_duplicate:
                                # Second LLM call for duplicate case
                                duplicate_prompt = f"""You are an AI assistant that manages server connections and configurations.
                                Current situation:
                                - Device ID: {device_id}
                                - Server IP: {server_ip}
                                - Status: Duplicate request detected within 5 minutes
                                - Previous action: save_to_db
                                - Result: {save_result}
                                
                                Available tools:
                                {json.dumps(tools_info, indent=2)}
                                
                                Decision rules:
                                1. For duplicate requests:
                                   - Use server_status to check server health
                                   - This will update the parameters in the database
                                
                                Respond with a JSON object:
                                {{
                                    "tool": "tool_name",
                                    "reason": "explanation of why this tool should be used"
                                }}
                                """
                                
                                response = await client.post(
                                    f"{GEMINI_API_URL}?key={API_KEY}",
                                    json={
                                        "contents": [{
                                            "parts": [{
                                                "text": duplicate_prompt
                                            }]
                                        }],
                                        "generationConfig": {
                                            "temperature": 0.1,
                                            "topK": 1,
                                            "topP": 1,
                                            "maxOutputTokens": 100
                                        }
                                    },
                                    timeout=30.0
                                )
                                
                                if response.status_code == 200:
                                    result = response.json()
                                    logger.info(f"Received duplicate Gemini response: {result}")
                                    
                                    try:
                                        content = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                        logger.info(f"Extracted content: {content}")
                                        
                                        # Extract and parse JSON from the response
                                        decision = extract_json_from_text(content)
                                        logger.info(f"Parsed decision: {decision}")
                                        
                                        if decision["tool"] == "server_status":
                                            # Execute server_status for duplicates
                                            status_result = server_status(device_id=device_id, server_ip=server_ip)
                                            logger.info(f"Server status result: {status_result}")
                                            
                                            # Parse status result to get the parameters
                                            status_lines = status_result.strip().split('\n')
                                            server_is_live = False
                                            
                                            for line in status_lines:
                                                line = line.strip()
                                                if line.startswith("Status:"):
                                                    server_is_live = "Live" in line
                                            
                                            # Update the database with new parameters
                                            conn = get_db_connection()
                                            cursor = conn.cursor()
                                            cursor.execute('''
                                                UPDATE server_data 
                                                SET change_config = ?, change_server = ?, timestamp = ?
                                                WHERE device_id = ? AND server_ip = ?
                                            ''', (server_is_live, not server_is_live, datetime.now(), device_id, server_ip))
                                            conn.commit()
                                            conn.close()
                                            
                                            return {"message": "Logs added successfully"}
                                        else:
                                            return {"error": f"Invalid tool selected for duplicate request: {decision['tool']}"}
                                            
                                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                                        logger.error(f"Error parsing Gemini response: {str(e)}")
                                        return {"error": f"Failed to parse response: {str(e)}"}
                                
                                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                                return {"error": f"API error: {response.status_code}"}
                            
                            # For non-duplicate requests, just return success
                            return {"message": "Logs added successfully"}
                        else:
                            return {"error": f"Invalid tool selected for initial request: {decision['tool']}"}
                            
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.error(f"Error parsing Gemini response: {str(e)}")
                        return {"error": f"Failed to parse response: {str(e)}"}
                
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                return {"error": f"API error: {response.status_code}"}
                
        elif request_type == "decision":
            # LLM call for GET request
            decision_prompt = f"""You are an AI assistant that manages server connections and configurations.
            Current request type: GET /decision
            - Device ID: {device_id}
            - Server IP: {server_ip}
            
            Available tools:
            {json.dumps(tools_info, indent=2)}
            
            Decision rules:
            1. For GET /decision:
               - Use get_decision to retrieve the latest parameters
               - This will return all data for the device and server
            
            Respond with a JSON object:
            {{
                "tool": "tool_name",
                "reason": "explanation of why this tool should be used"
            }}
            """
            
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(
                    f"{GEMINI_API_URL}?key={API_KEY}",
                    json={
                        "contents": [{
                            "parts": [{
                                "text": decision_prompt
                            }]
                        }],
                        "generationConfig": {
                            "temperature": 0.1,
                            "topK": 1,
                            "topP": 1,
                            "maxOutputTokens": 100
                        }
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Received decision Gemini response: {result}")
                    
                    try:
                        content = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        logger.info(f"Extracted content: {content}")
                        
                        # Extract and parse JSON from the response
                        decision = extract_json_from_text(content)
                        logger.info(f"Parsed decision: {decision}")
                        
                        if decision["tool"] == "get_decision":
                            # Execute get_decision tool
                            decision_result = get_decision(device_id=device_id, server_ip=server_ip)
                            response_data = decision_result
                            # print("Decision Result: ", decision_result)
                            # logger.info(f"Decision result: {decision_result}")
                            
                            # # Parse the decision result into a structured format
                            # lines = decision_result.strip().split('\n')
                            # response_data = {}
                            
                            # for line in lines:
                            #     line = line.strip()
                            #     if line.startswith("Device ID:"):
                            #         response_data["device_id"] = line.split(":", 1)[1].strip()
                            #     elif line.startswith("Server IP:"):
                            #         response_data["server_ip"] = line.split(":", 1)[1].strip()
                            #     elif line.startswith("Change Config:"):
                            #         response_data["change_config"] = line.split(":", 1)[1].strip().lower() == "true"
                            #     elif line.startswith("Change Server:"):
                            #         response_data["change_server"] = line.split(":", 1)[1].strip().lower() == "true"
                            #     elif line.startswith("Timestamp:"):
                            #         response_data["timestamp"] = line.split(":", 1)[1].strip()
                            
                            return response_data
                        else:
                            return {"error": f"Invalid tool selected for decision request: {decision['tool']}"}
                            
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.error(f"Error parsing Gemini response: {str(e)}")
                        return {"error": f"Failed to parse response: {str(e)}"}
                
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                return {"error": f"API error: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {"error": str(e)}

@app.post("/logs")
async def api_log_request(request: ServerRequest):
    """Endpoint to log device and server information"""
    logger.info(f"Received POST /logs request for device {request.device_id} and server {request.server_ip}")
    result = await get_response_from_llm("logs", request.device_id, request.server_ip)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.get("/decision/{device_id}/{server_ip}")
async def api_get_decision(device_id: str, server_ip: str):
    """Endpoint to get the latest decision for a device and server"""
    logger.info(f"Received GET /decision request for device {device_id} and server {server_ip}")
    result = await get_response_from_llm("decision", device_id, server_ip)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

# @app.get("/health")
# async def health_check():
#     """Health check endpoint"""
#     return {"status": "OK"}