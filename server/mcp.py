import subprocess
import platform
from datetime import datetime
import logging
from mcp.server.fastmcp import FastMCP
from server.database import save_request, update_server_status, get_latest_decision

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP()

@mcp.tool()
def save_to_db(device_id: str, server_ip: str) -> str:
    """Save incoming data to database and check for duplicates"""
    logger.info(f"Processing save_to_db request for device {device_id} and server {server_ip}")
    
    is_duplicate, request_id, timestamp = save_request(device_id, server_ip)
    
    if is_duplicate:
        return f"""
        Device ID: {device_id}
        Server IP: {server_ip}
        Status: Duplicate request detected
        Action: Processing duplicate request
        Request ID: {request_id}
        Timestamp: {timestamp}
        """
    else:
        return f"""
        Device ID: {device_id}
        Server IP: {server_ip}
        Status: Initial request received
        Action: Waiting for duplicate request within 5 minutes
        Request ID: {request_id}
        Timestamp: {timestamp}
        """

@mcp.tool()
def server_status(device_id: str, server_ip: str) -> str:
    """Check server status and update parameters"""
    logger.info(f"Checking server status for device {device_id} and server {server_ip}")
    
    try:
        # Extract host and port from server_ip
        if ':' in server_ip:
            host, port = server_ip.split(':')
        else:
            host = server_ip
            port = '443'  # Default to HTTPS port
        
        # Determine the ping command based on the platform
        if platform.system().lower() == "windows":
            ping_cmd = ["ping", "-n", "1", "-w", "1000", host]
        else:
            ping_cmd = ["ping", "-c", "1", "-W", "1", host]
        
        # Execute the ping command
        result = subprocess.run(ping_cmd, capture_output=True, text=True)
        is_live = result.returncode == 0
        
        # Update the database with the server status
        update_server_status(device_id, server_ip, is_live)
        
        current_time = datetime.now()
        return f"""
        Device ID: {device_id}
        Server IP: {server_ip}
        Status: {'Live' if is_live else 'Not responding'}
        Action: {'Updating configuration' if is_live else 'Changing server'}
        Timestamp: {current_time}
        """
        
    except Exception as e:
        logger.error(f"Error in server_status: {str(e)}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_decision(device_id: str, server_ip: str) -> str:
    """Get the latest decision for a device and server"""
    logger.info(f"Fetching decision for device {device_id} and server {server_ip}")
    
    result = get_latest_decision(device_id, server_ip)
    
    if result:
        logger.info(f"Found parameters for device {device_id}: {result}")
        return f"""
        Device ID: {result['device_id']}
        Server IP: {result['server_ip']}
        Change Config: {bool(result['change_config'])}
        Change Server: {bool(result['change_server'])}
        Timestamp: {result['timestamp']}
        """
    else:
        logger.warning(f"No data found for device {device_id} and server {server_ip}")
        return "No data found" 