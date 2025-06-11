from typing import Any, Dict, Optional
import sqlite3
import subprocess
import platform
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server
mcp = FastMCP("server_management")

# Database setup
DB_PATH = "server_data.db"


def _create_tables():
    """Create necessary database tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create server_requests table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        server_ip TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        change_config BOOLEAN DEFAULT FALSE,
        change_server BOOLEAN DEFAULT FALSE
    )
    """)
    
    conn.commit()
    conn.close()


def _add_request(device_id: str, server_ip: str) -> int:
    """Add a new request to the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    timestamp = datetime.now()
    cursor.execute(
        "INSERT INTO server_requests (device_id, server_ip, timestamp) VALUES (?, ?, ?)",
        (device_id, server_ip, timestamp)
    )
    
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return request_id


def _get_recent_request(device_id: str, server_ip: str) -> Optional[Dict[str, Any]]:
    """Get the most recent request for a device_id and server_ip within the last 5 minutes"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    five_mins_ago = datetime.now() - timedelta(minutes=5)
    
    cursor.execute(
        """SELECT * FROM server_requests 
           WHERE device_id = ? AND server_ip = ? AND timestamp > ? 
           ORDER BY timestamp DESC LIMIT 1""",
        (device_id, server_ip, five_mins_ago)
    )
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def _update_parameters(device_id: str, server_ip: str, change_config: bool, change_server: bool) -> bool:
    """Update the parameters for the most recent request"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        """UPDATE server_requests 
           SET change_config = ?, change_server = ? 
           WHERE device_id = ? AND server_ip = ? 
           ORDER BY timestamp DESC LIMIT 1""",
        (change_config, change_server, device_id, server_ip)
    )
    
    affected_rows = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected_rows > 0


def _get_parameters(device_id: str, server_ip: str) -> Optional[Dict[str, Any]]:
    """Get the parameters for a device_id and server_ip"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT * FROM server_requests 
           WHERE device_id = ? AND server_ip = ? 
           ORDER BY timestamp DESC LIMIT 1""",
        (device_id, server_ip)
    )
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def _ping_server(server_ip: str) -> bool:
    """Ping a server to check if it's alive"""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', server_ip]
    
    try:
        return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except Exception:
        return False


# Initialize database tables
_create_tables()


@mcp.tool()
def report_server_status(device_id: str, server_ip: str) -> str:
    """
    Report server status and get action recommendations.
    Args:
        device_id: The ID of the device reporting the status
        server_ip: The IP address of the server to check
    """
    # Add the request to the database
    _add_request(device_id, server_ip)
    
    # Check if there was a previous request within 5 minutes
    recent_request = _get_recent_request(device_id, server_ip)
    
    # If there was a recent request, perform the next action
    if recent_request and recent_request["id"] != _add_request(device_id, server_ip):
        # Check if the server is live
        server_is_live = _ping_server(server_ip)
        
        # Determine the appropriate action based on server status
        if server_is_live:
            change_config = True
            change_server = False
            action_msg = "Server is live. Configuration update is recommended."
        else:
            change_config = False
            change_server = True
            action_msg = "Server is not responding. Server change is recommended."
        
        # Update the parameters in the database
        _update_parameters(
            device_id=device_id,
            server_ip=server_ip,
            change_config=change_config,
            change_server=change_server
        )
        
        return f"""
        Device ID: {device_id}
        Server IP: {server_ip}
        Status: {"Live" if server_is_live else "Not responding"}
        Action: {action_msg}
        Change Config: {change_config}
        Change Server: {change_server}
        Timestamp: {datetime.now()}
        """
    else:
        return f"""
        Device ID: {device_id}
        Server IP: {server_ip}
        Status: Initial report received
        Action: Waiting for second report within 5 minutes to determine action
        Change Config: False
        Change Server: False
        Timestamp: {datetime.now()}
        """


@mcp.tool()
def get_server_parameters(device_id: str, server_ip: str) -> str:
    """
    Get the current parameters for a device and server.
    Args:
        device_id: The ID of the device
        server_ip: The IP address of the server
    """
    parameters = _get_parameters(device_id, server_ip)
    
    if not parameters:
        return f"No data found for device {device_id} and server {server_ip}"
    
    return f"""
    Device ID: {parameters["device_id"]}
    Server IP: {parameters["server_ip"]}
    Change Config: {bool(parameters["change_config"])}
    Change Server: {bool(parameters["change_server"])}
    Timestamp: {parameters["timestamp"]}
    """


@mcp.tool()
def ping_server_status(server_ip: str) -> str:
    """
    Ping a server to check if it's alive.
    Args:
        server_ip: The IP address of the server to ping
    """
    is_live = _ping_server(server_ip)
    
    if is_live:
        return f"Server {server_ip} is live and responding to ping requests."
    else:
        return f"Server {server_ip} is not responding to ping requests."


@mcp.resource("server_status://{device_id}/{server_ip}")
def server_status_resource(device_id: str, server_ip: str) -> str:
    """Resource to get server status information"""
    parameters = _get_parameters(device_id, server_ip)
    
    if not parameters:
        return f"No data found for device {device_id} and server {server_ip}"
    
    return f"""
    Device ID: {parameters["device_id"]}
    Server IP: {parameters["server_ip"]}
    Change Config: {bool(parameters["change_config"])}
    Change Server: {bool(parameters["change_server"])}
    Timestamp: {parameters["timestamp"]}
    """