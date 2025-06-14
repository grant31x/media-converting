# tmdb_client.py
# This module handles all communication with The Movie Database (TMDb) API.

import json
from urllib import request, parse, error
from pathlib import Path
from typing import List, Dict, Optional, Any

def get_api_key() -> Optional[str]:
    """Reads the TMDb API key from the api_config.json file."""
    try:
        config_path = Path(__file__).parent / "api_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            key = config.get("tmdb_api_key")
            if key and key != "YOUR_API_KEY_GOES_HERE":
                return key
    except (IOError, json.JSONDecodeError):
        pass
    return None

def search_movie(query: str, year: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Searches for a movie on TMDb by query and optional year.
    Returns a list of search results.
    """
    api_key = get_api_key()
    if not api_key:
        print("[DEBUG] TMDb API key not found or configured in api_config.json.")
        return []

    params = {"api_key": api_key, "query": query}
    if year:
        params["year"] = year

    encoded_params = parse.urlencode(params)
    url = f"https://api.themoviedb.org/3/search/movie?{encoded_params}"
    
    print(f"[DEBUG] Sending request to TMDb: {url.replace(api_key, 'REDACTED')}")

    try:
        # Added a 10-second timeout to the network request.
        with request.urlopen(url, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read())
                print("[DEBUG] TMDb API request successful.")
                return data.get("results", [])
    except error.URLError as e:
        # MODIFIED: Added more detailed error printing for diagnostics.
        print(f"[DEBUG] A network error occurred while contacting TMDb: {e}")
        return []
    except Exception as e:
        print(f"[DEBUG] An unexpected error occurred: {e}")
        return []

def get_movie_details(movie_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetches detailed information for a specific movie by its TMDb ID.
    """
    api_key = get_api_key()
    if not api_key:
        return None
        
    url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={api_key}"
    
    try:
        with request.urlopen(url, timeout=10) as response:
            if response.status == 200:
                return json.loads(response.read())
    except error.URLError as e:
        print(f"Error getting movie details from TMDb: {e}")
        return None