# -AutoWorkInstagram: Instagram Business & Content Manager

-AutoWorkInstagram is a robust, automated Instagram content planner, media compiler, and message manager built using Python (FastAPI) and the official Meta Graph & Instagram Content Publishing APIs. It is designed to automatically generate and schedule paired visual content, publish Reels and Stories, and handle automated, context-aware direct message and comment replies.

---

## Key Features

### 1. Automated Content Production & Continuous Posting
* **Dynamic Generation**: Generates motivational quotes, general knowledge facts, Hinglish observations, and short stories using LLM integration (Groq & OpenRouter).
* **Automated Video Compiler**: Automatically compiles dynamic background visual layers, stylized typography, and sound effects into standard limited-range `yuv420p` (`tv` range) H.264 video containers using FFmpeg.
* **Continuous Posting Cycle**: Runs a background autopilot loop that automatically generates and posts new Reels and Stories every 20 minutes.

### 2. Identical Reel + Story Pairing
* **Single-Pass Compilation**: Chooses a category and generates content once, rendering the video only once to save CPU and time.
* **Paired Drafts**: Automatically schedules and publishes a Reel and a Story sharing the exact same video file, caption text, and hashtags.

### 3. Bulletproof Auto-Recovery Loop
* **Crash & Timeout Protection**: If the server restarts or times out during the 30-second spacing delay between a Reel and a Story, a background scanner auto-detects the orphaned draft.
* **Reverse Chronological Recovery**: The bot automatically recovers and publishes outstanding drafts pair-by-pair on startup, ensuring that Reels and Stories are never left unmatched.

### 4. Relatable & Deduplicated AI Comments
* **Deduplication Filter**: Runs a 3-attempt validation check to ensure that generated lines do not match recently posted lines in the database memory history.
* **Unique AI Comments**: Injects dynamic variation seeds into the AI comment generator to prevent repetitive feedback.
* **Fallback Diversity**: Rotates between 35 different pre-written comments across 7 categories if the AI service is offline.

### 5. Smart Direct Message & Comment Replies
* **Context-Aware Simulation**: Auto-replies to comments and DMs in a conversational, anime-fan theme.
* **Safety & Spam Filtering**: Automatically filters and blocks spam, scam links, abuse, and inappropriate/adult content.

---

## Tech Stack
* **Backend**: Python, FastAPI, Uvicorn, SQLite/JSON database.
* **Media Rendering**: FFmpeg (video compilation), Pillow (image/frame manipulation).
* **APIs**: Meta Graph API (v20.0+), Instagram Graph API, Groq Cloud, OpenRouter.
* **Tunneling**: Cloudflare Tunnel (cloudflared) for local edge webhook processing.

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/adarshgokhe/-AutoWorkInstagram.git
   cd -AutoWorkInstagram
   ```

2. **Set up the virtual environment**:
   ```bash
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and configure your credentials:
   ```bash
   copy .env.example .env
   ```
   Edit the `.env` file and set:
   * `ADMIN_USERNAME` and `ADMIN_PASSWORD` (Dashboard Login)
   * `JWT_SECRET` (Secure token hash)
   * `META_ACCESS_TOKEN` (Your full, long-lived Meta Access Token)
   * `INSTAGRAM_USER_ID` (Your Instagram Business Account ID)
   * `GROQ_API_KEY` or `OPENROUTER_API_KEY` (AI model credentials)

4. **Run the Application**:
   Start the services using the persistent keep-alive manager:
   ```powershell
   cd ..
   powershell -ExecutionPolicy Bypass -File start_anime_nova.ps1
   ```
   Or launch the keep-alive watchdog script directly:
   ```bash
   python keep_alive.py
   ```

5. **Access the Dashboard**:
   Open your browser and navigate to:
   ```text
   http://127.0.0.1:8000/app
   ```

---

## Webhook Setup
To process direct messages and comment replies in real-time:
1. Register your tunnel callback URL in the **Meta App Dashboard**:
   `https://<your-cloudflare-subdomain>.trycloudflare.com/webhook/instagram`
2. Set the verify token to:
   `anime-nova-local-verify`
3. Subscribe to the `messages` and `comments` webhook fields under the **Instagram** product page.
4. On your Instagram mobile app, navigate to **Settings > Messages and story replies > Message controls > Connected tools**, and ensure **Allow access to messages** is toggled **ON**.

---

## License
This project is open-source and licensed under the MIT License.
