"""Automated GitHub streak maintainer script using Gemini API and GitHub REST API."""

import base64
from datetime import datetime, timezone
import json
import os
import random
import sys
import time
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
import requests

# Use the Google GenAI SDK
from google import genai
from google.genai import types

# Load environment variables from .env file for local testing
load_dotenv()

# ==========================================
# HELPER LOGGING & CONFIGURATION
# ==========================================
def log(msg: str) -> None:
    """Logs a formatted debug message with the current ISO timestamp in UTC.

    Args:
        msg: Message string to log to standard output.
    """
    print(f"[DEBUG] {datetime.now(timezone.utc).isoformat()} - {msg}")

def validate_environment() -> Tuple[str, str]:
    """Validates required environment variables and returns GH_TOKEN and GEMINI_API_KEY.
    
    Returns:
        Tuple containing GitHub token and Gemini API key strings.

    Exits the process with code 1 if either variable is missing.
    """
    github_token = os.environ.get("GH_TOKEN")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not github_token or not gemini_key:
        log("ERROR: GH_TOKEN or GEMINI_API_KEY environment variable is missing.")
        log("Please create a .env file locally, or set them in GitHub Secrets.")
        sys.exit(1)
    return github_token, gemini_key

GITHUB_TOKEN, GEMINI_API_KEY = validate_environment()

# Initialize the Gemini SDK client and chat session
client = genai.Client(api_key=GEMINI_API_KEY)
chat = client.chats.create(
    model="gemini-3.6-flash",
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
    )
)

HEADERS: Dict[str, str] = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

HISTORY_FILE: str = "history.json"
MAX_HISTORY_ENTRIES: int = 100
MAX_FILES_SAMPLE: int = 500
REQUEST_TIMEOUT: int = 30
VALID_EXTENSIONS: Tuple[str, ...] = ('.py', '.js', '.ts', '.html', '.css', '.md', '.java', '.cpp', '.c', '.go', '.rs', '.json')

# ==========================================
# API & HELPER FUNCTIONS
# ==========================================
def parse_json_response(text: str) -> Dict[str, Any]:
    """Safely parses JSON responses from the AI model, stripping Markdown code fences if present.
    
    Args:
        text: Raw text string response from the Gemini model.

    Returns:
        Parsed dictionary representation of the JSON object.

    Raises:
        json.JSONDecodeError: If parsing the string into JSON fails.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        log(f"Failed to parse JSON response: {e}. Raw text preview: {text[:200]!r}...")
        raise

def send_message_with_retry(prompt: str, retries: int = 5, delay: int = 10) -> Any:
    """Sends a prompt to the Gemini API with exponential backoff on retryable rate limits or busy errors.
    
    Args:
        prompt: The text prompt to send to the chat instance.
        retries: Maximum number of retry attempts.
        delay: Initial delay in seconds before doubling for retry logic.

    Returns:
        The response object returned from the Gemini chat model.

    Raises:
        RuntimeError: If all retries are exhausted without a successful response.
    """
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
                log(f"Unhandled exception encountered during API call: {e}")
                raise e
    raise RuntimeError("Max retries exceeded for Gemini API")

def load_history() -> List[Dict[str, Any]]:
    """Loads historical commit tracking records from local storage.

    Returns:
        List of commit history records, or an empty list if file reading fails.
    """
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            log(f"Error loading history file ({HISTORY_FILE}): {e}")
    return []

def save_history(history: List[Dict[str, Any]]) -> None:
    """Persists commit tracking history to local JSON storage.

    Args:
        history: List of dictionary entries representing past commit logs.
    """
    try:
        dirname = os.path.dirname(HISTORY_FILE)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4)
            f.write('\n')
    except Exception as e:
        log(f"Error saving history file ({HISTORY_FILE}): {e}")

def get_repos() -> List[Dict[str, str]]:
    """Fetches user's owned non-fork repositories via GitHub API.

    Returns:
        List of dictionaries containing repository name, description, and default branch.
    """
    log("Fetching user repositories...")
    url = "https://api.github.com/user/repos?affiliation=owner&sort=updated&per_page=50"
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    raw_repos = response.json()
    repos: List[Dict[str, str]] = [
        {
            "name": r['full_name'],
            "description": r.get('description') or "No description",
            "default_branch": r.get('default_branch', 'main')
        }
        for r in raw_repos
        if isinstance(r, dict) and not r.get('fork')
    ]
    log(f"Found {len(repos)} non-fork repositories.")
    return repos

def get_repo_files(repo_name: str, branch: str) -> List[str]:
    """Retrieves source code file paths matching supported extensions.

    Args:
        repo_name: Full repository name (e.g., 'owner/repo').
        branch: Target branch name to query git tree.

    Returns:
        List of relative file paths present in the repository tree.
    """
    log(f"Fetching file tree for {repo_name} on branch {branch}...")
    url = f"https://api.github.com/repos/{repo_name}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    tree: List[Dict[str, Any]] = response.json().get('tree', []) or []
    
    files = [
        item['path']
        for item in tree
        if item.get('type') == 'blob' and item.get('path', '').lower().endswith(VALID_EXTENSIONS)
    ]
    return files

def get_file_content(repo_name: str, file_path: str) -> Tuple[str, str]:
    """Downloads and base64-decodes file contents along with its git SHA.

    Args:
        repo_name: Full repository name in 'owner/repo' format.
        file_path: Relative file path within the repository.

    Returns:
        A tuple containing (decoded_text_content, file_sha_hash).
    """
    log(f"Fetching content of {file_path} from {repo_name}...")
    url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content = response.json()
    decoded = base64.b64decode(content['content']).decode('utf-8', errors='replace')
    return decoded, content['sha']

def update_file(repo_name: str, file_path: str, new_content: str, commit_msg: str, sha: str, branch: str) -> None:
    """Pushes updated file contents and commit message back to GitHub.

    Args:
        repo_name: Full repository name in 'owner/repo' format.
        file_path: Target file path within the repository.
        new_content: Modified text file content to commit.
        commit_msg: Commit message summary string.
        sha: Original Git blob SHA hash of the file.
        branch: Target branch name to push the commit to.
    """
    log(f"Committing changes to {file_path} in {repo_name}...")
    url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
    data = {
        "message": commit_msg,
        "content": base64.b64encode(new_content.encode('utf-8')).decode('utf-8'),
        "sha": sha,
        "branch": branch
    }
    response = requests.put(url, headers=HEADERS, json=data, timeout=REQUEST_TIMEOUT)
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
    if not repos:
        log("No repositories found for user. Exiting.")
        return
    
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
    selected_repo = choice_1.get('selected_repo')
    default_branch = choice_1.get('default_branch', 'main')
    if not selected_repo:
        log("AI failed to specify a valid target repository. Exiting.")
        return
    log(f"AI selected repo: {selected_repo}. Reasoning: {choice_1.get('reasoning')}")

    files = get_repo_files(selected_repo, default_branch)
    if not files:
        log(f"No eligible source files found in {selected_repo}. Exiting workflow.")
        return

    if len(files) > MAX_FILES_SAMPLE:
        files = random.sample(files, MAX_FILES_SAMPLE)

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
    selected_file = choice_2.get('selected_file')
    if not selected_file:
        log("AI failed to specify a valid target file. Exiting.")
        return
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
    
    new_code = choice_3.get('updated_code')
    commit_message = choice_3.get('commit_message', 'refactor: automated maintenance update')
    
    if not new_code:
        log("AI returned empty updated code. Aborting update.")
        return

    log(f"AI generated commit message: {commit_message}")
    
    update_file(selected_repo, selected_file, new_code, commit_message, file_sha, default_branch)
    
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": selected_repo,
        "file": selected_file,
        "commit_message": commit_message
    })
    
    if len(history) > MAX_HISTORY_ENTRIES:
        history = history[-MAX_HISTORY_ENTRIES:]
        
    save_history(history)
    log("Process completed successfully.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        sys.exit(1)
