# AutoWorkInstagram (AnimeNova)

**AutoWorkInstagram** (codenamed AnimeNova) is an end-to-end automated platform designed to generate, schedule, and post Instagram Reels, as well as intelligently auto-reply to Instagram Direct Messages (DMs) and Comments using AI.

## 🚀 Features

- **Automated Video Generation**: Automatically creates short-form video content (Reels) with AI-generated captions and assets.
- **Instagram Auto-Posting**: Integrates with the Meta Graph API to automatically publish Reels and Stories on schedule without manual intervention.
- **AI Auto-Responder**: Listens to incoming Instagram DMs and Comments via webhooks and automatically replies using a trained AI brain.
- **Safe Autopilot Mode**: Paces the posting schedule to keep the account active while avoiding Instagram rate limits and spam filters.
- **Cloudflare Tunnel Integration**: Automatically exposes the local backend to the internet securely using Cloudflare Tunnels, allowing Meta's webhooks to reach the local server.
- **Windows Watchdog System**: Includes robust PowerShell scripts to keep the server running continuously, auto-restarting on crashes, and configuring automatic startup on Windows boot.

## 📁 Project Structure

- `backend/`: The core FastAPI application that handles content generation, Meta API communication, webhook processing, and AI replies.
- `data/` & `media/`: Directories for storing video assets, generated drafts, and final mp4 renders.
- `anime_nova_data.json`: The local JSON database storing drafted posts, logs, and webhook status.
- `start_anime_nova.ps1`: The main launch script that starts the Python backend, the frontend, and the Cloudflare Tunnel.
- `watch_anime_nova.ps1` / `keep_alive.py`: Watchdog scripts ensuring high availability of the local servers.

## ⚙️ Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js (for the frontend)
- Meta Developer Account (with a registered Instagram App)
- Instagram Professional/Business Account linked to a Facebook Page

### 1. Environment Configuration
Create a `.env` file inside the `backend/` directory by copying `.env.example`.
Fill in your specific Meta API credentials:
```env
META_ACCESS_TOKEN=your_long_lived_token
INSTAGRAM_ACCOUNT_ID=your_ig_account_id
WEBHOOK_VERIFY_TOKEN=anime-nova-local-verify
```

### 2. Install Dependencies
Navigate to the backend directory and install the required Python packages:
```bash
cd backend
pip install -r requirements.txt
```

### 3. Run the Application
You can easily launch the entire system (Backend, Frontend, and Cloudflare Tunnel) using the provided PowerShell script on Windows:
```powershell
.\start_anime_nova.ps1
```

### 4. Configure Meta Webhooks
Once the server starts, it will generate a public Cloudflare Tunnel URL (e.g., `https://your-tunnel.trycloudflare.com`).
1. Go to the Meta Developer Dashboard.
2. Navigate to **Webhooks** -> **Instagram**.
3. Edit the Subscription and paste the new Tunnel URL followed by `/webhook/instagram`.
4. Use your `WEBHOOK_VERIFY_TOKEN` to verify and save.

## 🛠️ Usage
- **Autopilot**: Enable autopilot in the frontend dashboard to let the system automatically generate and queue daily posts.
- **Inbox/Replies**: Once webhooks are verified and your Instagram app's "Allow access to messages" setting is ON, the bot will automatically reply to incoming messages!

## 📜 License
This project is private and intended for personal use for automating the `@funzone_creator` Instagram account.
