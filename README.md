# MCP Server

This is a simple MCP server implementation using FastMCP. It provides tools like 'web_search' and 'check_weather' to search the internet and get the latest update of your city's weather respectively.

## Setup
1. Make sure you have Python 3.12 or higher installed
2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the project root with your API Keys (if needed):
   ```
   OPENWEATHER_API_KEY=your_openweather_api_key_here
   ANY_OTHER_API_KEY=your_any_other_api_key_here
   ```

## Running the Server
Start the server with:
```bash
python main.py
```

The server will start on `http://localhost:8000` by default.

## Connecting to the Server

To use this server with your custom MCP client:

Make sure your client is configured to connect to the MCP server URL:
   ```
   http://localhost:8000/mcp
   ```

## API Keys Required

- **Weather API**: Get from [OpenWeatherMap](https://openweathermap.org/api) (free tier available)