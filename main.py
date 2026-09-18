import base64
from datetime import datetime
import json
import os
import random
import sys
import time
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
import requests

# Use the new SDK
from google import genai
from google.genai import types

# Load environment variables from .env file for local testing
load_dotenv()

# ==========================================
# CONFIGURATION & SETUP
# ==========================================
GITHUB_TOKEN = os.environ.get("GH_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GITHUB_TOKEN or not GEMINI_API_KEY:
    print("ERROR: GH_TOKEN or GEMINI_API_KEY environment variable is missing.")
    print("Please create a .env file locally, or set them in GitHub Secrets.")
    sys.exit(1)

# Initialize the new Gemini SDK client
client = genai.Client(api_key=GEMINI_API_KEY)
chat = client.chats.create(
    model="gemini-3.6-flash",
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
    )
)

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

HISTORY_FILE = "history.json"
VALID_EXTENSIONS = ('.py', '.js', '.ts', '.html', '.css', '.md', '.java', '.cpp', '.c', '.go', '.rs')

def log(msg: str) -> None:
    """Logs a formatted debug message with the current ISO timestamp."""
    print(f"[DEBUG] {datetime.now().isoformat()} - {msg}")

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def parse_json_response(text: str) -> dict:
    """Safely parses JSON responses from the AI model, stripping code fences if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)

def send_message_with_retry(prompt: str, retries: int = 5, delay: int = 10) -> Any:
    """Sends a prompt to the Gemini API with exponential backoff on retryable errors."""
    for attempt in range(retries):
        try:
            return chat.send_message(prompt)
        except Exception as e:
            err_msg = str(e)
            if any(code in err_msg for code in ("503", "UNAVAILABLE", "429")):
                log(f"API busy or quota exceeded (Attempt {attempt + 1}/{retries}). Waiting {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise e
    raise RuntimeError("Max retries exceeded for Gemini API")

def load_history() -> List[Dict[str, Any]]:
    """Loads historical commit tracking records from local file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as e:
            log(f"Error loading history: {e}")
    return []

def save_history(history: List[Dict[str, Any]]) -> None:
    """Persists tracking history to local JSON storage."""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4)

def get_repos() -> List[Dict[str, str]]:
    """Fetches user's owned non-fork repositories via GitHub API."""
    log("Fetching user repositories...")
    url = "https://api.github.com/user/repos?affiliation=owner&sort=updated&per_page=50"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    repos = []
    for r in response.json():
        if not r['fork']: 
            repos.append({
                "name": r['full_name'],
                "description": r['description'] or "No description",
                "default_branch": r['default_branch']
            })
    return repos

def get_repo_files(repo_name: str, branch: str) -> List[str]:
    """Retrieves source code file paths matching supported extensions."""
    log(f"Fetching file tree for {repo_name} on branch {branch}...")
    url = f"https://api.github.com/repos/{repo_name}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    tree = response.json().get('tree', [])
    
    files = [
        item['path']
        for item in tree
        if item.get('type') == 'blob' and item['path'].endswith(VALID_EXTENSIONS)
    ]
    return files

def get_file_content(repo_name: str, file_path: str) -> Tuple[str, str]:
    """Downloads and base64-decodes file contents along with its git SHA."""
    log(f"Fetching content of {file_path} from {repo_name}...")
    url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    content = response.json()
    decoded = base64.b64decode(content['content']).decode('utf-8')
    return decoded, content['sha']

def update_file(repo_name: str, file_path: str, new_content: str, commit_msg: str, sha: str, branch: str) -> None:
    """Pushes updated file contents and commit message back to GitHub."""
    log(f"Committing changes to {file_path} in {repo_name}...")
    url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
    data = {
        "message": commit_msg,
        "content": base64.b64encode(new_content.encode('utf-8')).decode('utf-8'),
        "sha": sha,
        "branch": branch
    }
    response = requests.put(url, headers=HEADERS, json=data, timeout=30)
    response.raise_for_status()
    log("Commit successful!")

# ==========================================
# MAIN WORKFLOW
# ==========================================
def main() -> None:
    """Executes the automated streak maintainer workflow."""
    history = load_history()
    log(f"Loaded {len(history)} past commit records.")

    repos = get_repos()
    
    prompt_1 = f"""
    You are an AI assistant acting as a real developer to maintain a GitHub streak.
    Here is the history of your last few commits (do not spam the exact same repo continuously):
    {json.dumps(history[-10:], indent=2)}

    Here are the available repositories:
    {json.dumps(repos, indent=2)}

    TASK:
    Analyze the history and available repos, and choose exactly ONE repository to work on today.
    
    STRICT JSON RESPONSE FORMAT:
    {{
        "selected_repo": "owner/repo_name",
        "default_branch": "main",
        "reasoning": "Why you chose this repo based on history"
    }}
    """
    log("Asking AI to select a repository...")
    resp_1 = send_message_with_retry(prompt_1)
    choice_1 = parse_json_response(resp_1.text)
    selected_repo = choice_1['selected_repo']
    default_branch = choice_1['default_branch']
    log(f"AI selected repo: {selected_repo}. Reasoning: {choice_1.get('reasoning')}")

    files = get_repo_files(selected_repo, default_branch)
    if len(files) > 500:
        files = random.sample(files, 500)

    prompt_2 = f"""
    You have selected the repository '{selected_repo}'.
    Here are the available text/code files in this repository:
    {json.dumps(files, indent=2)}

    TASK:
    Choose ONE file that would be appropriate for a minor, realistic improvement. 
    Good candidates are files where you might add a docstring, fix formatting, add a minor comment, or improve variable names.
    
    STRICT JSON RESPONSE FORMAT:
    {{
        "selected_file": "path/to/file.ext",
        "reasoning": "Why you chose this file"
    }}
    """
    log("Asking AI to select a file...")
    resp_2 = send_message_with_retry(prompt_2)
    choice_2 = parse_json_response(resp_2.text)
    selected_file = choice_2['selected_file']
    log(f"AI selected file: {selected_file}. Reasoning: {choice_2.get('reasoning')}")

    code, file_sha = get_file_content(selected_repo, selected_file)
    
    prompt_3 = f"""
    Here is the source code of '{selected_file}':
    
    ```
    {code}
    ```

    TASK:
    Make a minor, realistic improvement to this code. 
    - You may add helpful comments, docstrings, or perform minor refactoring.
    - CRITICAL RULE: DO NOT break the code. DO NOT change the core logic. Ensure the file remains fully functional.
    - Provide a realistic, short commit message that a human would write for this specific change.
    - Return the FULL ENTIRE source code including your changes. Do not return partial snippets.
    
    STRICT JSON RESPONSE FORMAT:
    {{
        "commit_message": "your realistic commit message here",
        "updated_code": "the full entire source code with your modifications"
    }}
    """
    log("Asking AI to modify code...")
    resp_3 = send_message_with_retry(prompt_3)
    choice_3 = parse_json_response(resp_3.text)
    
    new_code = choice_3['updated_code']
    commit_message = choice_3['commit_message']
    
    log(f"AI generated commit message: {commit_message}")
    
    update_file(selected_repo, selected_file, new_code, commit_message, file_sha, default_branch)
    
    history.append({
        "timestamp": datetime.now().isoformat(),
        "repo": selected_repo,
        "file": selected_file,
        "commit_message": commit_message
    })
    
    if len(history) > 100:
        history = history[-100:]
        
    save_history(history)
    log("Process completed successfully.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        sys.exit(1)
