import os
import logging
import sqlite3
from datetime import datetime, timedelta
import subprocess
import platform
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from server.database import save_request, update_server_status, get_latest_decision

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize MCP server
mcp = FastMCP()

def get_db_connection():
    """Get a connection to the SQLite database"""
    try:
        conn = sqlite3.connect('server_data.db')
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {str(e)}")
        raise

def init_db():
    """Initialize the database with required tables"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create server_data table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                server_ip TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                change_config BOOLEAN DEFAULT FALSE,
                change_server BOOLEAN DEFAULT FALSE,
                UNIQUE(device_id, server_ip)
            )
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()

@mcp.tool()
def save_to_db(device_id: str, server_ip: str) -> str:
    """Save device and server information to database and check for duplicates"""
    logger.info(f"Saving data for device {device_id} and server {server_ip}")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check for duplicate request within 5 minutes
        five_minutes_ago = datetime.now() - timedelta(minutes=5)
        cursor.execute('''
            SELECT * FROM server_data 
            WHERE device_id = ? AND server_ip = ? AND timestamp > ?
        ''', (device_id, server_ip, five_minutes_ago))
        
        existing_record = cursor.fetchone()
        
        if existing_record:
            logger.info("Duplicate request detected within 5 minutes")
            return f"Status: Duplicate request detected\nTimestamp: {existing_record['timestamp']}"
        
        # Insert new record
        cursor.execute('''
            INSERT OR REPLACE INTO server_data (device_id, server_ip, timestamp)
            VALUES (?, ?, ?)
        ''', (device_id, server_ip, datetime.now()))
        
        conn.commit()
        logger.info("Data saved successfully")
        return f"Status: New request saved\nTimestamp: {datetime.now()}"
        
    except sqlite3.Error as e:
        error_msg = f"Database error: {str(e)}"
        logger.error(error_msg)
        return f"Error: {error_msg}"
    finally:
        if conn:
            conn.close()

@mcp.tool()
def server_status(device_id: str, server_ip: str) -> str:
    """Check server status and update parameters"""
    logger.info(f"Checking status for device {device_id} and server {server_ip}")
    
    try:
        # Ping the server
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', server_ip]
        
        result = subprocess.run(command, capture_output=True, text=True)
        is_live = result.returncode == 0
        
        # Update database with new parameters
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE server_data 
                SET change_config = ?, change_server = ?, timestamp = ?
                WHERE device_id = ? AND server_ip = ?
            ''', (is_live, not is_live, datetime.now(), device_id, server_ip))
            
            # If no row was updated, insert a new one
            if cursor.rowcount == 0:
                cursor.execute('''
                    INSERT INTO server_data (device_id, server_ip, timestamp, change_config, change_server)
                    VALUES (?, ?, ?, ?, ?)
                ''', (device_id, server_ip, datetime.now(), is_live, not is_live))
            
            conn.commit()
            
            status = "Live" if is_live else "Not responding"
            logger.info(f"Server status: {status}")
            
            return f"""Status: {status}
Change Config: {is_live}
Change Server: {not is_live}
Timestamp: {datetime.now()}"""
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {str(e)}")
            return f"Error: Database error - {str(e)}"
        finally:
            conn.close()
            
    except subprocess.SubprocessError as e:
        error_msg = f"Ping error: {str(e)}"
        logger.error(error_msg)
        return f"Error: {error_msg}"
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        return f"Error: {error_msg}"

@mcp.tool()
def get_decision(device_id: str, server_ip: str) -> str:
    """Get the latest decision parameters for a device and server"""
    logger.info(f"Getting decision for device {device_id} and server {server_ip}")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM server_data 
            WHERE device_id = ? AND server_ip = ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (device_id, server_ip))
        
        record = cursor.fetchone()

        # return record
        
        if not record:
            logger.warning(f"No data found for device {device_id} and server {server_ip}")
            return "No data found for the specified device and server"
        
        result = {
            "device_id": record['device_id'],
            "server_ip": record['server_ip'],
            "change_config": True if record['change_config'] else False,
            "change_server": True if record['change_server'] else False,
            "timestamp": record['timestamp']
        }
        return result
        
        return f"""Device ID: {record['device_id']}
Server IP: {record['server_ip']}
Change Config: {record['change_config']}
Change Server: {record['change_server']}
Timestamp: {record['timestamp']}"""
        
    except sqlite3.Error as e:
        error_msg = f"Database error: {str(e)}"
        logger.error(error_msg)
        return f"Error: {error_msg}"
    finally:
        if conn:
            conn.close()

# Initialize database on module import
init_db() 