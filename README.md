# 🚀 AI GitHub Streak Maintainer

Ever wanted to maintain your GitHub streak but didn't want to make fake, empty commits? 
**AI GitHub Streak Maintainer** solves this by using AI (Google Gemini) to make *actual, realistic minor improvements* (like adding docstrings, fixing typos, or small refactors) across your various repositories!

It runs entirely on GitHub Actions on autopilot. It maintains a history of its past edits so it doesn't spam the same repository twice in a row.

---

## 🛠️ How it works
1. **Cron Job triggers:** GitHub Actions wakes up the Python script randomly 4 times a day.
2. **AI Chooses a Repo:** The script fetches your repos and gives the list to Gemini AI. AI looks at the `history.json` and selects a repo that hasn't been touched recently.
3. **AI Chooses a File:** The script fetches the repo's file tree. AI picks a file that looks like a good candidate for a minor improvement.
4. **AI Commits:** The script downloads the file, gives it to AI. AI refactors it slightly, writes a realistic commit message, and commits it back via the GitHub API!
5. **State Saved:** The bot updates `history.json` in this repository so it remembers what it did for next time.

---

## 🚀 Setup Guide

To get this running on your own GitHub account safely, follow these steps:

### 1. Fork this Repository
Click the **Fork** button at the top right of this repository to create your own copy.
> **Important:** Keep your forked repository **Private** if you don't want others to see your `history.json` log. (Though public is fine too since secrets are hidden).

### 2. Get your Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Click **Create API Key**.
3. Copy the generated key. **Keep it safe!**

### 3. Get your GitHub Personal Access Token
1. Go to your GitHub [Developer Settings > Personal Access Tokens (Classic)](https://github.com/settings/tokens).
2. Click **Generate new token (classic)**.
3. Give it a note (e.g., "AI Committer Bot").
4. **Important:** Select the `repo` scope (this gives it permission to read and commit to your repositories).
5. Generate and copy the token (it starts with `ghp_...`). **You won't be able to see it again!**

### 4. Add the Secrets to your Fork
To keep your keys safe, **NEVER put them in the code directly**. Instead, add them to GitHub Secrets:
1. Go to your forked repository on GitHub.
2. Click on **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**:
   - **Name:** `GEMINI_API_KEY`
   - **Secret:** Paste your Gemini API key here.
   - Click **Add secret**.
4. Click **New repository secret** again:
   - **Name:** `GH_TOKEN`
   - **Secret:** Paste your GitHub Token here.
   - Click **Add secret**.

### 6. Enable GitHub Actions Permissions
Because the bot needs to update `history.json` and push it back to the repo, you need to give GitHub Actions write permissions:
1. Go to your repository **Settings**.
2. On the left sidebar, click **Actions** > **General**.
3. Scroll down to **Workflow permissions**.
4. Select **Read and write permissions**.
5. Check the box for **Allow GitHub Actions to create and approve pull requests**.
6. Click **Save**.

### 7. Run the Workflow
1. Go to the **Actions** tab in your repository.
2. GitHub might ask you to "Enable Actions on this fork". Click **Yes**.
3. On the left side, you should see **AI Streak Committer** (this is the one you need to run!).
4. Click **Run workflow** to test it manually!

---

## 💻 Running Locally (Optional)

If you want to test the script on your local machine before putting it on GitHub Actions:

1. Clone your repo locally.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the root folder and add your keys:
   ```env
   GH_TOKEN=ghp_your_token_here
   GEMINI_API_KEY=AIzaSy_your_api_key_here
   ```
   *(Make sure `.env` is in your `.gitignore` so you don't accidentally upload it!)*
4. Run the script:
   ```bash
   python main.py
   ```

Enjoy your automated, hyper-realistic, AI-powered GitHub streak! 🔥
