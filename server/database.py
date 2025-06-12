from typing import Any, Dict, Optional
import sqlite3
from datetime import datetime, timedelta
import os
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Database setup
DB_PATH = os.getenv("DB_PATH", "server_data.db")

def get_db_connection():
    """Get a database connection"""
    return sqlite3.connect(DB_PATH)

def _create_tables():
    """Create necessary database tables if they don't exist"""
    conn = get_db_connection()
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

def save_request(device_id: str, server_ip: str) -> tuple[bool, Optional[int], Optional[datetime]]:
    """
    Save a new request and check for duplicates within 5 minutes.
    Returns: (is_duplicate, request_id, timestamp)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        current_time = datetime.now()
        five_minutes_ago = current_time - timedelta(minutes=5)
        
        # Check for duplicate requests
        cursor.execute("""
            SELECT id, timestamp 
            FROM server_requests 
            WHERE device_id = ? AND server_ip = ? 
            AND timestamp > ?
            ORDER BY timestamp DESC
        """, (device_id, server_ip, five_minutes_ago))
        
        recent_requests = cursor.fetchall()
        
        if recent_requests:
            # Found a duplicate request
            logger.info(f"Duplicate request detected within 5 minutes for device {device_id}")
            return True, recent_requests[0][0], recent_requests[0][1]
        
        # No duplicate found, save new request
        cursor.execute("""
            INSERT INTO server_requests (device_id, server_ip, timestamp, change_config, change_server)
            VALUES (?, ?, ?, 0, 0)
        """, (device_id, server_ip, current_time))
        
        request_id = cursor.lastrowid
        conn.commit()
        
        logger.info(f"Added new request with ID: {request_id}")
        return False, request_id, current_time
        
    except Exception as e:
        logger.error(f"Error in save_request: {str(e)}")
        return False, None, None
    finally:
        conn.close()

def update_server_status(device_id: str, server_ip: str, is_live: bool) -> bool:
    """Update server status and parameters based on ping result"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # First get the latest request ID
        cursor.execute("""
            SELECT id FROM server_requests 
            WHERE device_id = ? AND server_ip = ? 
            ORDER BY timestamp DESC LIMIT 1
        """, (device_id, server_ip))
        
        latest_request = cursor.fetchone()
        if not latest_request:
            logger.warning(f"No request found for device {device_id} and server {server_ip}")
            return False
            
        # Update the parameters for the latest request
        if is_live:
            cursor.execute("""
                UPDATE server_requests 
                SET change_config = 1, change_server = 0
                WHERE id = ?
            """, (latest_request[0],))
        else:
            cursor.execute("""
                UPDATE server_requests 
                SET change_config = 0, change_server = 1
                WHERE id = ?
            """, (latest_request[0],))
        
        affected_rows = cursor.rowcount
        conn.commit()
        return affected_rows > 0
        
    except Exception as e:
        logger.error(f"Error in update_server_status: {str(e)}")
        return False
    finally:
        conn.close()

def get_latest_decision(device_id: str, server_ip: str) -> Optional[Dict[str, Any]]:
    """Get the latest decision for a device and server"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, device_id, server_ip, timestamp, change_config, change_server
            FROM server_requests
            WHERE device_id = ? AND server_ip = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (device_id, server_ip))
        
        result = cursor.fetchone()
        
        if result:
            return dict(result)
        return None
        
    except Exception as e:
        logger.error(f"Error in get_latest_decision: {str(e)}")
        return None
    finally:
        conn.close()

# Initialize database tables
_create_tables() 