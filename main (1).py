import os
import json
import time
import requests
import subprocess
import argparse
from pathlib import Path

# Constants
RPMSHARE_API_KEY = "cba926e36ff510351f459f27"
BASE_URL = "https://rpmshare.com/api/v1"
TSUKIHIME_API_URL = "https://api.tsukihime.org/v1"
ANIME_FOLDER = Path("Anime")
TRACKING_FILE = ANIME_FOLDER / "tracking.json"
TEMP_STATE_FILE = ANIME_FOLDER / "temp_state.json"
BASE_RPMSHARE_FOLDER_ID = "b33i"

class AnimeProcessor:
    def __init__(self, anime_name, process_types):
        self.anime_name = anime_name
        self.process_types = process_types # e.g., ["movie", "ova", "special", "tv"]
        self.state = self.load_state()
        self.anime_path = ANIME_FOLDER / anime_name
        self.anime_path.mkdir(parents=True, exist_ok=True)
        for sub in ["Soft Sub", "Hard Sub", "Dub"]:
            (self.anime_path / sub).mkdir(exist_ok=True)

    def load_state(self):
        if TRACKING_FILE.exists():
            with open(TRACKING_FILE, 'r') as f:
                return json.load(f)
        return {"completed": [], "in_progress": {}}

    def save_state(self):
        with open(TRACKING_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def search_torrents(self):
        print(f"Searching torrents for: {self.anime_name}")
        all_torrents = []
        try:
            # Search for the anime across all pages
            page = 1
            while True:
                response = requests.get(f"{TSUKIHIME_API_URL}/search/torrents", params={"query": self.anime_name, "page": page})
                if response.status_code != 200:
                    break
                data = response.json()
                torrents = data.get("torrents", [])
                if not torrents:
                    break
                all_torrents.extend(torrents)
                page += 1
                if page > 10: # Safety limit
                    break
        except Exception as e:
            print(f"Error searching torrents: {e}")
        return all_torrents

    def filter_and_rank(self, torrents):
        print("Filtering for English translated and ranking by quality...")
        filtered = []
        for t in torrents:
            title = t.get("title", "").lower()
            # Filter English translated, exclude raws
            if "raw" in title:
                continue
            
            # Simple quality ranking (prioritize 1080p, 720p)
            score = 0
            if "1080p" in title: score = 10
            elif "720p" in title: score = 5
            
            # Check for categories (movie, ova, etc.)
            match_type = False
            for p_type in self.process_types:
                if p_type.lower() in title:
                    match_type = True
                    break
            
            if match_type or not self.process_types:
                t['score'] = score
                filtered.append(t)
        
        # Sort by score descending
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        return filtered

    def get_upload_endpoint(self):
        headers = {"api-token": RPMSHARE_API_KEY}
        try:
            response = requests.get(f"{BASE_URL}/video/upload", headers=headers)
            if response.status_code == 200:
                return response.json().get("endpoint")
        except:
            pass
        return None

    def create_folder(self, name, parent_id=BASE_RPMSHARE_FOLDER_ID):
        headers = {"api-token": RPMSHARE_API_KEY}
        data = {"name": name}
        if parent_id:
            data["parent_id"] = parent_id
        try:
            response = requests.post(f"{BASE_URL}/video/folder", headers=headers, json=data)
            if response.status_code in [200, 201]:
                return response.json().get("id")
        except:
            pass
        return None

    def download_with_aria2(self, btih, output_dir):
        magnet = f"magnet:?xt=urn:btih:{btih}"
        cmd = ["aria2c", "--dir", str(output_dir), "--seed-time=0", magnet]
        subprocess.run(cmd, check=True)

    def upload_file(self, file_path, folder_id):
        endpoint = self.get_upload_endpoint()
        if not endpoint:
            print("Failed to get upload endpoint")
            return False
            
        headers = {"api-token": RPMSHARE_API_KEY}
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {'folder_id': folder_id}
            response = requests.post(endpoint, headers=headers, files=files, data=data)
            return response.status_code in [200, 201]

    def run(self):
        print(f"Starting automation for {self.anime_name}")
        torrents = self.search_torrents()
        best_torrents = self.filter_and_rank(torrents)
        
        if not best_torrents:
            print("No suitable torrents found.")
            return

        # Create remote anime folder
        remote_anime_folder_id = self.create_folder(self.anime_name)
        
        for torrent in best_torrents:
            btih = torrent.get("btih")
            if not btih or btih in self.state['completed']:
                continue
                
            print(f"Processing torrent: {torrent.get('title')}")
            temp_dir = Path("temp_download")
            temp_dir.mkdir(exist_ok=True)
            
            try:
                self.download_with_aria2(btih, temp_dir)
                
                # Simple logic: upload all video files in temp_dir
                for video_file in temp_dir.glob("**/*"):
                    if video_file.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                        print(f"Uploading {video_file.name}...")
                        success = self.upload_file(video_file, remote_anime_folder_id)
                        if success:
                            print(f"Successfully uploaded {video_file.name}")
                
                self.state['completed'].append(btih)
                self.save_state()
            except Exception as e:
                print(f"Error processing torrent {btih}: {e}")
            finally:
                subprocess.run(["rm", "-rf", str(temp_dir)])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--anime", required=True, help="Name of the anime")
    parser.add_argument("--types", required=True, help="Comma separated types (movie,ova,special,tv)")
    args = parser.parse_args()
    
    types = [t.strip() for t in args.types.split(",")] if args.types else []
    processor = AnimeProcessor(args.anime, types)
    processor.run()
