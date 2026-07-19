import os
import json
import time
import requests
import argparse
from pathlib import Path

# Constants
RPMSHARE_API_KEY = "cba926e36ff510351f459f27"
TSUKIHIME_API_URL = "https://api.tsukihime.org/v1"
MANUS_API_URL = "https://api.manus.ai/v1"
MANUS_API_KEY = os.getenv("MANUS_API_KEY")

# Local working directory for the bot
BOT_WORKING_DIR = Path("bot_data")
BOT_WORKING_DIR.mkdir(exist_ok=True)

class AnimeCollector:
    def __init__(self, anime_name):
        self.anime_name = anime_name

    def search_torrents(self):
        search_query = self.anime_name.strip()
        print(f"Searching Tsukihime API for torrents for: {search_query}")
        all_torrents = []
        limit = 100
        offset = 0
        while True:
            try:
                response = requests.get(f"{TSUKIHIME_API_URL}/search/torrents", params={"q": search_query, "limit": limit, "offset": offset})
                response.raise_for_status()
                data = response.json()
                torrents = data.get("results", []) if isinstance(data, dict) else data
                
                if not torrents or not isinstance(torrents, list):
                    break
                    
                all_torrents.extend(torrents)
                offset += limit
                
                if len(torrents) < limit or offset >= 1000: # Safety limit
                    break
            except requests.exceptions.RequestException as e:
                print(f"Error during torrent search: {e}")
                break
        return all_torrents

    def ask_manus_for_executor(self, raw_torrents):
        if not MANUS_API_KEY:
            print("MANUS_API_KEY not found in environment. Skipping automated script generation.")
            return None

        print("Asking Manus API to generate the executor script...")
        
        prompt = f"""Here is all the magnet links for this anime '{self.anime_name}':
{json.dumps(raw_torrents, indent=2)}

Find me all the torrents and remove duplicates and filter out the raw things but if there are none that are English translated continue with the torrents one see if there are any subtitles online and include torrents for those.

Then, generate a Python script named 'executor.py' that:
1. Creates a main folder for the anime name on RPMShare (ID: b33i).
2. Creates subfolders for 'Dub', 'Hard Sub', and 'Soft Sub' inside it.
3. Downloads the selected torrents using aria2c (chunked to 1/3 of available disk space).
4. Processes videos:
   - Hard sub: FFmpeg ultrafast, CRF 22.
   - Dub: Extract English audio.
5. Uploads everything to the correct RPMShare folders using the API key 'cba926e36ff510351f459f27'.

Output ONLY the Python code for 'executor.py'."""

        headers = {
            "x-manus-api-key": MANUS_API_KEY,
            "Content-Type": "application/json"
        }
        
        data = {
            "message": prompt,
            "structured_output_schema": {
                "type": "object",
                "properties": {
                    "executor_code": {"type": "string"}
                },
                "required": ["executor_code"]
            }
        }
        
        try:
            # Step 1: Create a task
            response = requests.post(f"{MANUS_API_URL}/task.create", headers=headers, json=data)
            response.raise_for_status()
            task_id = response.json().get("task_id")
            print(f"Manus task created: {task_id}")
            
            # Step 2: Poll for completion
            while True:
                time.sleep(10)
                status_response = requests.get(f"{MANUS_API_URL}/task.detail", headers=headers, params={"task_id": task_id})
                status_response.raise_for_status()
                task_detail = status_response.json().get("task_detail", {})
                
                if task_detail.get("status") == "stopped":
                    result = task_detail.get("structured_output", {}).get("value", {})
                    return result.get("executor_code")
                elif task_detail.get("status") == "failed":
                    print("Manus task failed.")
                    return None
                
                print(f"Waiting for Manus... (Status: {task_detail.get('status')})")
        except Exception as e:
            print(f"Error communicating with Manus API: {e}")
        return None

    def run(self):
        print(f"Starting automation for {self.anime_name}")
        raw_torrents = self.search_torrents()
        
        if not raw_torrents:
            print("No torrents found for this anime.")
            return

        executor_code = self.ask_manus_for_executor(raw_torrents)
        
        if executor_code:
            with open("executor.py", "w") as f:
                f.write(executor_code)
            print("Successfully generated executor.py. Running it now...")
            subprocess.run(["python", "executor.py"], check=True)
        else:
            print("Failed to generate executor.py.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--anime", required=True, help="Name of the anime")
    args = parser.parse_args()
    
    collector = AnimeCollector(args.anime)
    collector.run()
