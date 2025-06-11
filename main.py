import uvicorn


def main():
    """Run the FastAPI application"""
    # Import the server modules to register them with MCP
    import server.weather
    import server.server_management
    
    # Run the FastAPI server
    uvicorn.run("server.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()