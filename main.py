from fastmcp import FastMCP
import asyncio
import logging
import os
import requests
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv


# Load environment variables if any
load_dotenv()

# Setup logging
logger = logging.getLogger("MCP-Server")

# Create an MCP server
mcp = FastMCP("MCP")


# Add MCP Tools here

@mcp.tool()
async def web_search(query: str) -> dict:
    """
    Get quick, short, and fast web search results.

    Args:
        query: The search query string

    Returns:
        Dictionary containing search results data
    """
    import requests

    search_url = f"https://api.duckduckgo.com/?q={query}&format=json"
    try:
        response = requests.get(search_url)
        response.raise_for_status()
        data = response.json()
        return {"results": data.get("RelatedTopics", [])}
    except requests.RequestException as e:
        logger.error(f"Web search error: {str(e)}")
        return {"error": str(e)}

@mcp.tool()
async def get_weather(city: str, country: Optional[str] = None) -> dict:
    """
    Get current weather information for a specified city.

    Args:
        city: The city name
        country: Optional ISO 3166 country code (e.g., 'US', 'UK')
    Returns:
        Comprehensive weather information in a JSON format
    """
    import requests

    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        logger.error("OpenWeather API key not found in environment variables")
        return {"error": "API key not configured"}

    location = f"{city},{country}" if country else city
    weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=metric"

    try:
        response = requests.get(weather_url)
        response.raise_for_status()
        data = response.json()
        if data.get("cod") != 200:
            return {"error": data.get("message", "Error fetching weather data")}
        return {
            "city": data["name"],
            "country": data["sys"]["country"],
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"]
        }
    except requests.RequestException as e:
        logger.error(f"Weather API error: {str(e)}")
        return {"error": str(e)}


# Main Function to Start the MCP Server

if __name__ == "__main__":
    
    logger.info("Starting VPN MCP Server")

    # This will handle the MCP protocol communication
    try:
        asyncio.run(
            mcp.run_async(
                transport="streamable-http",
                host="0.0.0.0",
                port=8000,
            )
        )
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("MCP Server shutdown complete")
