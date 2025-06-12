import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Run the FastAPI application"""
    # Import the server modules to register them with MCP
    import server.mcp
    
    # Get server configuration from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    # Run the FastAPI server
    uvicorn.run("server.api:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()