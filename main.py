import os
import json
import time
import requests
import subprocess
import argparse
from pathlib import Path
import shutil

# Constants
RPMSHARE_API_KEY = "cba926e36ff510351f459f27"
BASE_URL = "https://rpmshare.com/api/v1"
TSUKIHIME_API_URL = "https://api.tsukihime.org/v1"

# Local working directory for the bot
BOT_WORKING_DIR = Path("bot_data")
BOT_WORKING_DIR.mkdir(exist_ok=True)

TRACKING_FILE = BOT_WORKING_DIR / "tracking.json"
TEMP_STATE_FILE = BOT_WORKING_DIR / "temp_state.json"

# RPMShare base folder ID (assuming it's already created as 'Anime')
BASE_RPMSHARE_FOLDER_ID = "b33i"

class AnimeProcessor:
    def __init__(self, anime_name, process_types):
        self.anime_name = anime_name
        self.process_types = process_types # e.g., ["movie", "ova", "special", "tv"]
        self.state = self.load_state()
        
        # Create local anime folder for this specific anime
        self.anime_local_path = BOT_WORKING_DIR / self.anime_name.replace(" ", "_")
        self.anime_local_path.mkdir(parents=True, exist_ok=True)

        # Create subfolders for processed content
        self.soft_sub_path = self.anime_local_path / "Soft Sub"
        self.hard_sub_path = self.anime_local_path / "Hard Sub"
        self.dub_path = self.anime_local_path / "Dub"
        
        self.soft_sub_path.mkdir(exist_ok=True)
        self.hard_sub_path.mkdir(exist_ok=True)
        self.dub_path.mkdir(exist_ok=True)

    def load_state(self):
        if TRACKING_FILE.exists():
            with open(TRACKING_FILE, 'r') as f:
                return json.load(f)
        return {"completed_torrents": [], "processed_files": [], "rpmshare_folders": {}}

    def save_state(self):
        with open(TRACKING_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def save_temp_state(self, data):
        with open(TEMP_STATE_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def load_temp_state(self):
        if TEMP_STATE_FILE.exists():
            with open(TEMP_STATE_FILE, 'r') as f:
                return json.load(f)
        return None

    def search_torrents(self):
        # Trim whitespace from anime name to avoid 422 errors
        search_query = self.anime_name.strip()
        print(f"Searching Tsukihime API for torrents for: {search_query}")
        all_torrents = []
        limit = 100
        offset = 0
        while True:
            try:
                # The API uses 'q' for query and 'offset' for pagination
                response = requests.get(f"{TSUKIHIME_API_URL}/search/torrents", params={"q": search_query, "limit": limit, "offset": offset})
                response.raise_for_status()
                data = response.json()
                # Based on standard API behavior, the results might be in 'torrents' or just the root list
                torrents = data.get("torrents", []) if isinstance(data, dict) else data
                
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

    def ai_filter_and_rank(self, raw_torrents):
        print("Asking AI to filter, deduplicate, and rank torrents...")
        # Simulate asking Manus for filtering and ranking
        # In a real scenario, this would be an LLM call with specific instructions
        # For now, we'll simulate a response based on the user's criteria
        
        # Construct the prompt for the AI
        prompt = f"""Here is a list of torrents for the anime '{self.anime_name}':
{json.dumps(raw_torrents, indent=2)}

Please perform the following actions:
1. Remove any duplicate torrents.
2. Filter out any torrents that are 'raw' (not English translated). If there are no English translated torrents, then keep the raw torrents and try to find subtitles online for them.
3. Prioritize torrents with higher quality (e.g., 1080p over 720p, then 720p over lower resolutions).
4. Identify and remove torrents that are 'multisub' if English-only options are available.
5. Organize the remaining torrents by type: movies, OVAs, specials, TV series.
6. For any remastered versions that are raw, suggest finding subtitles for that specific remastered version.
7. Provide the output as a JSON array of torrent objects, each including 'title', 'magnet_link', 'size', 'btih', and a new field 'suggested_action' (e.g., 'download', 'download_and_find_subs').
"""
        # This is where you would integrate with an actual LLM. 
        # For this exercise, we'll implement a basic Python-based filtering
        # based on the prompt instructions.

        filtered_torrents = []
        seen_btihs = set()

        for torrent in raw_torrents:
            btih = torrent.get("btih")
            if not btih or btih in seen_btihs:
                continue
            seen_btihs.add(btih)

            title = torrent.get("title", "").lower()
            magnet_link = f"magnet:?xt=urn:btih:{btih}"
            torrent["magnet_link"] = magnet_link

            is_raw = "raw" in title or "jpn" in title and "eng" not in title
            is_english = "eng" in title or "english" in title or "sub" in title and "raw" not in title
            is_multisub = "multisub" in title

            # Simple quality scoring
            score = 0
            if "1080p" in title: score += 10
            elif "720p" in title: score += 5
            if "remastered" in title: score += 2

            torrent["score"] = score
            torrent["is_raw"] = is_raw
            torrent["is_english"] = is_english
            torrent["is_multisub"] = is_multisub
            
            filtered_torrents.append(torrent)

        # Re-evaluate raw filtering after checking all torrents
        has_english_options = any(t["is_english"] for t in filtered_torrents)

        final_selection = []
        for torrent in filtered_torrents:
            if torrent["is_raw"] and has_english_options:
                continue # Skip raw if English options exist
            
            if torrent["is_multisub"] and has_english_options and not torrent["is_raw"]:
                # If multisub and English options exist, and not raw, prefer non-multisub
                # This logic needs more sophistication for true AI-like filtering
                pass # For now, we'll keep it simple and not remove multisub automatically unless explicitly told by AI

            if torrent["is_raw"] and not has_english_options:
                torrent["suggested_action"] = "download_and_find_subs"
            else:
                torrent["suggested_action"] = "download"
            
            final_selection.append(torrent)

        # Sort by score (quality) descending
        final_selection.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # Organize by type (simplified for now, a real AI would do better)
        organized_torrents = {"movies": [], "ovas": [], "specials": [], "tv": [], "other": []}
        for torrent in final_selection:
            title = torrent.get("title", "").lower()
            if "movie" in title: organized_torrents["movies"].append(torrent)
            elif "ova" in title: organized_torrents["ovas"].append(torrent)
            elif "special" in title: organized_torrents["specials"].append(torrent)
            elif "tv" in title or "episode" in title: organized_torrents["tv"].append(torrent)
            else: organized_torrents["other"].append(torrent)

        # Flatten the organized list for processing, maintaining priority
        ranked_torrents = []
        for key in ["movies", "ovas", "specials", "tv", "other"]:
            ranked_torrents.extend(organized_torrents[key])

        return ranked_torrents

    def get_upload_endpoint(self):
        headers = {"api-token": RPMSHARE_API_KEY}
        try:
            response = requests.get(f"{BASE_URL}/video/upload", headers=headers)
            if response.status_code == 200:
                return response.json().get("endpoint")
        except requests.exceptions.RequestException as e:
            print(f"Error getting upload endpoint: {e}")
        return None

    def create_rpmshare_folder(self, name, parent_id=BASE_RPMSHARE_FOLDER_ID):
        headers = {"api-token": RPMSHARE_API_KEY, "Content-Type": "application/json"}
        data = {"name": name}
        if parent_id:
            data["parent_id"] = parent_id
        try:
            response = requests.post(f"{BASE_URL}/video/folder", headers=headers, json=data)
            if response.status_code in [200, 201]:
                return response.json().get("id")
            elif response.status_code == 409: # Conflict, folder might exist
                print(f"Folder '{name}' already exists or conflict occurred. Trying to find existing folder.")
                # A more robust solution would be to list folders and find by name
                # For now, we'll assume if 409, it means it exists and we can't get ID this way
                return None # Indicate failure to get ID via creation
        except requests.exceptions.RequestException as e:
            print(f"Error creating RPMShare folder: {e}")
        return None

    def get_available_disk_space(self, path="."):
        stat = os.statvfs(path)
        return stat.f_bavail * stat.f_frsize # Free space in bytes

    def download_with_aria2(self, magnet_link, output_dir, files_to_download=None):
        print(f"Downloading {magnet_link} to {output_dir}")
        cmd = ["aria2c", "--dir", str(output_dir), "--seed-time=0", "--stop-on-hashing-error=false", "--console-log-level=warn", "--summary-interval=0"]
        if files_to_download:
            # aria2c --select-file=1,5,6 magnet_link
            cmd.append(f"--select-file={','.join(map(str, files_to_download))}")
        cmd.append(magnet_link)
        subprocess.run(cmd, check=True)

    def get_video_and_audio_streams(self, file_path):
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
            ]
            video_info = json.loads(subprocess.check_output(cmd))
            has_video = len(video_info.get("streams", [])) > 0

            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name,index,tags:language", "-of", "json", str(file_path)
            ]
            audio_info = json.loads(subprocess.check_output(cmd))
            audio_streams = audio_info.get("streams", [])
            
            english_audio_index = -1
            for stream in audio_streams:
                if stream.get("tags", {}).get("language") == "eng":
                    english_audio_index = stream["index"]
                    break
            return has_video, english_audio_index
        except Exception as e:
            print(f"Error probing streams for {file_path}: {e}")
            return False, -1

    def process_video(self, input_file, output_hardsub_path, output_dub_path, subtitles_file=None):
        print(f"Processing video: {input_file}")
        has_video, english_audio_index = self.get_video_and_audio_streams(input_file)

        if not has_video:
            print(f"No video stream found in {input_file}, skipping processing.")
            return None, None

        hardsub_output = None
        if subtitles_file and subtitles_file.exists():
            hardsub_output = output_hardsub_path / input_file.name.replace(input_file.suffix, f".hardsub{input_file.suffix}")
            print(f"Creating hardsub: {hardsub_output}")
            try:
                cmd = [
                    "ffmpeg", "-i", str(input_file),
                    "-vf", f"subtitles={subtitles_file}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                    "-c:a", "copy", str(hardsub_output)
                ]
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                print(f"Error creating hardsub for {input_file}: {e}")
                hardsub_output = None
        else:
            print(f"No subtitle file provided or found for hardsubbing {input_file}.")

        dub_output = None
        if english_audio_index != -1:
            dub_output = output_dub_path / input_file.name.replace(input_file.suffix, f".eng_audio.mka") # mka for audio only
            print(f"Extracting English audio: {dub_output}")
            try:
                cmd = [
                    "ffmpeg", "-i", str(input_file),
                    "-map", f"0:a:{english_audio_index}",
                    "-c:a", "copy", str(dub_output)
                ]
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                print(f"Error extracting English audio for {input_file}: {e}")
                dub_output = None
        else:
            print(f"No English audio track found in {input_file}, skipping dub extraction.")

        return hardsub_output, dub_output

    def upload_file_to_rpmshare(self, file_path, remote_folder_id):
        print(f"Uploading {file_path.name} to RPMShare folder {remote_folder_id}...")
        upload_endpoint = self.get_upload_endpoint()
        if not upload_endpoint:
            print("Failed to get RPMShare upload endpoint.")
            return False

        headers = {"api-token": RPMSHARE_API_KEY}
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f, 'application/octet-stream')}
                data = {'folder_id': remote_folder_id}
                response = requests.post(upload_endpoint, headers=headers, files=files, data=data)
                response.raise_for_status()
                print(f"Successfully uploaded {file_path.name}. Response: {response.json()}")
                return True
        except requests.exceptions.RequestException as e:
            print(f"Error uploading {file_path.name} to RPMShare: {e}")
            if e.response:
                print(f"Response content: {e.response.text}")
        return False

    def run(self):
        print(f"Starting automation for {self.anime_name}")
        
        # 1. Search torrents
        raw_torrents = self.search_torrents()
        if not raw_torrents:
            print("No torrents found for this anime.")
            return

        # 2. AI-assisted filtering and ranking
        # This step simulates the LLM interaction. The output is a JSON string.
        # For actual execution, this would be an LLM call.
        # For now, we'll use the internal Python logic to produce the 'AI-filtered' list.
        ai_filtered_torrents = self.ai_filter_and_rank(raw_torrents)
        
        if not ai_filtered_torrents:
            print("No suitable torrents after AI filtering.")
            return

        # Create remote folder for this specific anime if it doesn't exist
        # Check if folder already exists in state or try to create
        remote_anime_folder_id = self.state["rpmshare_folders"].get(self.anime_name)
        if not remote_anime_folder_id:
            remote_anime_folder_id = self.create_rpmshare_folder(self.anime_name)
            if remote_anime_folder_id:
                self.state["rpmshare_folders"][self.anime_name] = remote_anime_folder_id
                self.save_state()
            else:
                print(f"Could not create or find remote folder for {self.anime_name}. Aborting.")
                return
        
        # Create subfolders for Soft Sub, Hard Sub, Dub inside the anime folder on RPMShare
        remote_hardsub_folder_id = self.create_rpmshare_folder("Hard Sub", parent_id=remote_anime_folder_id)
        remote_dub_folder_id = self.create_rpmshare_folder("Dub", parent_id=remote_anime_folder_id)
        # Soft Sub files will be uploaded directly to the anime folder, or if they are external, to a dedicated folder

        # Get available disk space for chunked downloads
        total_disk_space = shutil.disk_usage(".").total
        available_disk_space = self.get_available_disk_space()
        download_chunk_limit = available_disk_space / 3
        print(f"Total disk space: {total_disk_space / (1024**3):.2f} GB, Available: {available_disk_space / (1024**3):.2f} GB, Download chunk limit: {download_chunk_limit / (1024**3):.2f} GB")

        for torrent in ai_filtered_torrents:
            btih = torrent.get("btih")
            if not btih or btih in self.state["completed_torrents"]:
                print(f"Skipping already completed or invalid torrent: {torrent.get('title')}")
                continue
            
            print(f"Processing torrent: {torrent.get('title')}")
            temp_download_dir = self.anime_local_path / "temp_download"
            temp_download_dir.mkdir(exist_ok=True)

            try:
                # Download the torrent
                self.download_with_aria2(torrent["magnet_link"], temp_download_dir)
                
                # Find downloaded video files and potential subtitle files
                video_files = []
                subtitle_files = []
                for root, _, files in os.walk(temp_download_dir):
                    for f in files:
                        file_path = Path(root) / f
                        if file_path.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                            video_files.append(file_path)
                        elif file_path.suffix.lower() in [".srt", ".ass", ".vtt"]:
                            subtitle_files.append(file_path)

                for video_file in video_files:
                    # Find best matching subtitle file
                    best_sub_file = None
                    if subtitle_files:
                        # Simple matching: same base name or first available
                        for sub_f in subtitle_files:
                            if video_file.stem == sub_f.stem:
                                best_sub_file = sub_f
                                break
                        if not best_sub_file: # If no exact match, just take the first one
                            best_sub_file = subtitle_files[0]

                    # Process video (hardsub, dub extraction)
                    hardsub_output, dub_output = self.process_video(video_file, self.hard_sub_path, self.dub_path, best_sub_file)

                    # Upload processed files
                    if hardsub_output and hardsub_output.exists():
                        if self.upload_file_to_rpmshare(hardsub_output, remote_hardsub_folder_id):
                            self.state["processed_files"].append(str(hardsub_output))
                    
                    if dub_output and dub_output.exists():
                        if self.upload_file_to_rpmshare(dub_output, remote_dub_folder_id):
                            self.state["processed_files"].append(str(dub_output))

                    # Upload original video (soft sub) if not raw and no hardsub was made
                    if not torrent["is_raw"] and not hardsub_output:
                        print(f"Uploading original video (soft sub): {video_file.name}")
                        if self.upload_file_to_rpmshare(video_file, remote_anime_folder_id):
                            self.state["processed_files"].append(str(video_file))

                self.state["completed_torrents"].append(btih)
                self.save_state()

            except Exception as e:
                print(f"Error processing torrent {btih}: {e}")
            finally:
                # Clean up temporary download directory
                if temp_download_dir.exists():
                    shutil.rmtree(temp_download_dir)

        print("Automation finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--anime", required=True, help="Name of the anime")
    parser.add_argument("--types", help="Comma separated types (movie,ova,special,tv)", default="")
    args = parser.parse_args()
    
    types = [t.strip() for t in args.types.split(",")] if args.types else []
    processor = AnimeProcessor(args.anime, types)
    processor.run()
