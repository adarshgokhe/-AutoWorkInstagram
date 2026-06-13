import os
import hmac
import hashlib
import json
import math
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import jwt
import requests
from requests import RequestException
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Anime Nova Instagram Manager")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
CORS_ORIGINS = [item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()]
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
BRAND = os.getenv("BRAND_WATERMARK", "Anim.funzon")
AUTO_PUBLISH_ENABLED = os.getenv("AUTO_PUBLISH_ENABLED", "false").lower() == "true"
CONTINUOUS_POST_MODE = os.getenv("CONTINUOUS_POST_MODE", "false").lower() == "true"
CONTINUOUS_INTERVAL_MINUTES = int(os.getenv("CONTINUOUS_INTERVAL_MINUTES", "20"))
CONTINUOUS_PAIR_MODE = os.getenv("CONTINUOUS_PAIR_MODE", "true").lower() == "true"
AI_FIRST_COMMENT_ENABLED = os.getenv("AI_FIRST_COMMENT_ENABLED", "true").lower() == "true"

AUTO_REPLY_SEND_ENABLED = os.getenv("AUTO_REPLY_SEND_ENABLED", "true").lower() == "true"
INBOX_POLL_ENABLED = os.getenv("INBOX_POLL_ENABLED", "true").lower() == "true"
NOVA_REPLY_AI_ENABLED = os.getenv("NOVA_REPLY_AI_ENABLED", "true").lower() == "true"
NOVA_REPLY_PROVIDER_ORDER = [item.strip().lower() for item in os.getenv("NOVA_REPLY_PROVIDER_ORDER", "groq,openrouter").split(",") if item.strip()]
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "anime-nova-local-verify")
MIN_CONTENT_PER_DAY = int(os.getenv("MIN_CONTENT_PER_DAY", "3"))
MAX_CONTENT_PER_DAY = int(os.getenv("MAX_CONTENT_PER_DAY", "5"))
PUBLISH_MIN_INTERVAL_MINUTES = int(os.getenv("PUBLISH_MIN_INTERVAL_MINUTES", "120"))
DAILY_POST_SPACING_MINUTES = int(os.getenv("DAILY_POST_SPACING_MINUTES", "15"))
MEDIA_INPUT_DIR = Path(os.getenv("MEDIA_INPUT_DIR", "./media/input"))
MEDIA_OUTPUT_DIR = Path(os.getenv("MEDIA_OUTPUT_DIR", "./media/output"))
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", "").rstrip("/")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "anime-nova")
SAFE_SOURCE_MODE = os.getenv("SAFE_SOURCE_MODE", "ai_first_royalty_free_verified")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
PRODUCTIONCRATE_API_KEY = os.getenv("PRODUCTIONCRATE_API_KEY", "")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
PIKA_API_KEY = os.getenv("PIKA_API_KEY", "")
JSON2VIDEO_API_KEY = os.getenv("JSON2VIDEO_API_KEY", "")
CANVA_API_KEY = os.getenv("CANVA_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MEDIA_INPUT_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB = Path("anime_nova_data.json")
DB_LOCK = threading.RLock()
OPERATION_LOCK = threading.RLock()
SCHEDULER_STARTED = False
LOGIN_FAILURES = {}
LOGIN_MAX_FAILURES = 8
LOGIN_LOCK_SECONDS = 3 * 60
PUBLIC_WEBHOOK_STATUS_CACHE = {"time": 0.0, "value": None}

REQUIRED_ENV_KEYS = [
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "JWT_SECRET",
    "INSTAGRAM_USER_ID",
    "META_ACCESS_TOKEN",
    "PUBLIC_MEDIA_BASE_URL",
    "WEBHOOK_VERIFY_TOKEN",
]
STARTUP_SCAN_FILES = [
    "main.py",
    "app.html",
    "privacy.html",
    "data-deletion.html",
    "requirements.txt",
    ".env",
]

app = FastAPI(title=APP_NAME)
security = HTTPBearer(auto_error=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' https: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api") or request.url.path in ["/app", "/privacy", "/data-deletion"]:
        response.headers["Cache-Control"] = "no-store"
    return response

SAFE_ON = {
    "safe_autopilot": True,
    "approval_screen": False,
    "auto_generate_posts": True,
    "auto_generate_stories": True,
    "auto_generate_reels": True,
    "auto_reply_comments": True,
    "auto_reply_dm": True,
    "natural_safe_reply": True,
    "brand_transparent_reply": True,
    "auto_watermark": True,
    "watermark_anim_funzon": True,
    "nsfw_block": True,
    "spam_block": True,
    "scam_block": True,
    "abusive_block": True,
    "unknown_link_block": True,
    "duplicate_post_block": True,
    "activity_logs": True,
    "password_lock": True,
    "personal_info_protection": True,
    "ai_anime_content_brain": True,
    "auto_caption_generator": True,
    "auto_hashtag_generator": True,
    "daily_random_scheduler": True,
    "analytics_tracker": True,
    "business_creator_api_support": True,
    "growth_assistant": True,
    "followback_tracker": True,
    "growth_suggestions": True,
    "safe_engagement_analytics": True,
    "auto_highlight_planner": True,
    "auto_story_planner": True,
    "auto_reel_script_generator": True,
    "auto_reply_style_selector": True,
    "auto_bio_generator": True,
    "anime_trend_suggestions": True,
    "content_calendar": True,
    "post_frequency_planner": True,
    "safe_dm_reply_assistant": True,
    "comment_reply_assistant": True,
    "activity_heatmap": True,
    "best_posting_time_analytics": True,
    "dark_light_mode": True,
    "animated_cards": True,
    "analytics_charts": True,
    "mobile_responsive_layout": True,
    "live_status_indicators": True,
    "profile_rotation_planner": True,
    "auto_chat_reply": True,
}
BLOCKED = {
    "auto_follow": False,
    "auto_unfollow": False,
    "mass_comment": False,
    "mass_like": False,
    "fake_likes": False,
    "fake_engagement": False,
    "spam_dm": False,
    "detection_bypass": False,
    "pretend_human_mode": False,
    "scrape_other_creators": False,
    "download_copyright_anime": False,
    "adult_18_content": False,
    "hentai_nsfw_content": False,
}
ALL_SETTINGS = {**SAFE_ON, **BLOCKED}
BLOCKED_KEYS = list(BLOCKED.keys())

NSFW_WORDS = "18+ nsfw hentai nude naked sexual explicit adult porn xxx lewd erotic".split()
SPAM_WORDS = ["buy followers", "free followers", "otp", "password", "click this", "crypto profit", "investment", "telegram link"]
ABUSE_WORDS = ["kill yourself", "hate speech", "abuse", "slur"]
PRIVATE_WORDS = ["real name", "phone", "email", "location", "address", "password", "token", "api key", "owner number"]
HINGLISH_FILLERS = {
    "please": "",
    "pls": "",
    "plz": "",
    "mujhe": "",
    "mere liye": "",
    "kya tum": "",
    "tum": "",
    "chahiye": "",
    "chahie": "",
    "batao": "tell",
    "kaise": "how",
    "kesa": "how",
    "kya": "what",
    "reply do": "reply",
    "massage": "message",
    "massege": "message",
    "msg": "message",
    "reel banao": "make reel",
    "story dalo": "post story",
    "post dalo": "post",
    "achha": "good",
    "acha": "good",
    "mast": "great",
}

TOPICS = {
    "funny": [
        "When anime fans say one more episode at 2 AM",
        "Side character suddenly gets main character energy",
        "Anime food reaction that looks too serious",
        "Villain explains the plan for 20 minutes",
        "Quiet friend becomes final boss in group chat",
    ],
    "romantic": [
        "Rainy umbrella confession moment",
        "Sunset anime couple quote",
        "Wholesome blush scene idea",
        "City lights romantic story caption",
        "Long-distance anime love quote",
    ],
    "action": [
        "Training arc power-up reel",
        "Rival saves hero at the last second",
        "Sword clash freeze-frame post",
        "Hero unlocks hidden power",
        "Final boss entrance short reel",
    ],
    "adventure": [
        "Squad enters mysterious anime city",
        "Portal opens to fantasy kingdom",
        "Floating island adventure story",
        "Ancient map reveals hidden anime world",
        "Anime road trip with magical pet",
    ],
    "cute": [
        "Sleepy anime cat mascot morning story",
        "Cute chibi picnic moment",
        "Kawaii anime smile mood",
        "Soft anime cafe morning vibe",
        "Tiny dragon wants snacks",
    ],
    "emotional": [
        "Silent farewell at the station",
        "Hero keeps smiling after losing everything",
        "Old promise under cherry blossoms",
        "Letters never sent anime quote",
    ],
    "motivational": [
        "Training today, victory tomorrow",
        "Anime hero never gives up quote",
        "Weak start to strong comeback",
        "Discipline beats talent anime line",
    ],
    "quotes": [
        "Even small steps become a story",
        "Your arc is not over yet",
        "A calm heart can carry a storm",
        "Main character energy starts with discipline",
    ],
    "memes": [
        "Anime fan waiting for new season",
        "When opening song is better than the episode",
        "Me after finishing 12 episodes in one night",
        "POV: filler episode but you still watch",
    ],
    "comedy_line": [
        "My confidence has no proof, but full attitude.",
        "Today my brain opened in low battery mode.",
        "I was serious for five minutes, then life made a meme.",
        "Mood: acting busy, actually buffering.",
        "Some problems need solutions, mine need snacks.",
        "I came, I saw, I forgot why I came.",
        "My plan was simple, then reality added extra scenes.",
        "Overthinking is my cardio, but I still look calm.",
        "I am not late, I am arriving with suspense.",
        "Life gave me pressure, I gave it a status update.",
        "I don't ignore problems, I put them on silent.",
        "Main character energy, side character timing.",
    ],
    "love_line": [
        "Some names still feel soft even in a noisy day.",
        "Real love feels calm, not like a test.",
        "A small message from the right person changes everything.",
        "You don't need perfect words when the care is real.",
        "The right heart makes silence feel safe.",
        "Love is not loud; it stays when mood changes.",
        "I like the kind of love that feels peaceful.",
        "Some people become your favorite place without trying.",
        "Distance hurts less when effort is honest.",
        "A soft heart notices what others skip.",
        "If the vibe is real, even waiting feels sweet.",
        "Love should feel like rest, not confusion.",
    ],
    "motivation_line": [
        "Discipline is boring until the results start talking.",
        "Don't wait for energy; start and let energy follow.",
        "Your comeback is built on the days nobody claps.",
        "Small progress is still proof that you did not quit.",
        "Focus today, flex silently tomorrow.",
        "A strong future needs one honest step today.",
        "Do it tired, but don't leave it unfinished.",
        "Your best version is not lucky; it is trained.",
        "No noise, just work, then results.",
        "The next chapter needs consistency, not excuses.",
        "Wake up with pressure, sleep with progress.",
        "If you cannot run, walk, but don't stop.",
    ],
    "interesting_line": [
        "People notice your result, not the nights that made it.",
        "The quietest room often has the loudest thoughts.",
        "Your energy changes when you stop explaining yourself.",
        "Sometimes the plot twist is choosing peace.",
        "A new day is a blank screen with hidden power.",
        "Attention is expensive; spend it on what grows you.",
        "Some doors close because your standards finally opened.",
        "The mind gets sharper when the noise gets lower.",
        "Not every pause is weakness; sometimes it is aim.",
        "The deepest thoughts arrive when the world goes silent.",
        "Your pattern becomes your future before you notice.",
        "Growth is quiet until everyone calls it sudden.",
    ],
    "thought_line": [
        "Keep your heart soft and your standards sharp.",
        "Peace is a flex when the world wants reactions.",
        "Some days are not heavy, they are just asking for rest.",
        "Protect your mood like it protects your future.",
        "Not every delay is defeat; some delays redirect you.",
        "A calm mind wins battles nobody records.",
        "Let today be simple, but not wasted.",
        "Your circle should feel clean, not crowded.",
        "Some chapters need patience, not panic.",
        "Don't carry yesterday into every new morning.",
        "Stay kind, but stop shrinking yourself.",
        "A quiet life can still be powerful.",
    ],
    "general_knowledge": [
        "Honey never spoils; archaeologists found 3000-year-old honey still edible.",
        "Bananas are berries, but strawberries are not.",
        "A day on Venus is longer than a year on Venus.",
        "Wombat poop is cube-shaped, which stops it rolling away.",
        "Octopuses have three hearts and blue blood.",
        "The Eiffel Tower can be 15 cm taller during the summer.",
        "Water makes up about 60 percent of the human body.",
        "Sound travels about four times faster in water than in air.",
        "Some clouds can weigh more than a million pounds.",
        "Cleopatra lived closer in time to the Moon landing than to the Great Pyramid construction.",
        "There are more trees on Earth than stars in the Milky Way.",
        "Cowboys didn't actually wear cowboy hats until the late 1800s."
    ],
    "story_line": [
        "A king placed a boulder on a road. Only a peasant moved it, finding gold underneath.",
        "A boy cried wolf twice for fun. When the wolf actually came, no one believed him.",
        "An old man lost his horse. Neighbors said bad luck. The horse returned with wild horses.",
        "A girl found a cocoon and helped the butterfly by cutting it. It could never fly.",
        "Two friends walked in the desert. One slapped the other, who wrote it in sand. Later, he saved him, who wrote it in stone.",
        "A Zen master poured tea into a full cup, showing a student they must empty their mind first.",
        "A snake bit a saw in anger, only to hurt itself more. Anger hurts us most.",
        "A frog fell in a milk bucket and kept swimming until it churned into butter and climbed out.",
        "A father gave his son a bag of nails to hammer into the fence whenever he lost his temper. The holes remained.",
        "A star thrower threw washed-up starfish back. An observer said it doesn't matter. He said, 'It mattered to that one.'"
    ],
}

LINE_CATEGORIES = ["comedy_line", "love_line", "motivation_line", "interesting_line", "thought_line", "general_knowledge", "story_line"]
LINE_CATEGORY_LABELS = {
    "comedy_line": "Comedy Line",
    "love_line": "Love Line",
    "motivation_line": "Motivation Line",
    "interesting_line": "Interesting Line",
    "thought_line": "Thought Line",
    "general_knowledge": "General Knowledge",
    "story_line": "Story Line",
}
LINE_WALLPAPER_HEADINGS = {
    "comedy_line": "mood update",
    "love_line": "soft love",
    "motivation_line": "focus mode",
    "interesting_line": "mind spark",
    "thought_line": "quiet note",
    "general_knowledge": "knowledge note",
    "story_line": "quick story",
}

PUBLISHABLE_STATUSES = ["ready_to_publish", "publish_failed", "publish_rate_limited"]

REEL_TEMPLATES = {
    "glow_eye": {
        "label": "Glow Eye Edit",
        "beats": ["Eyes glow", "Power wakes up", "Clean aura burst", "Main character moment"],
        "vfx": "glow rings, aura pulses, sharp light streaks",
        "mood": "neon power-up cut",
    },
    "sad_quote": {
        "label": "Sad Anime Quote",
        "beats": ["Soft rain mood", "A quiet heart speaks", "Sad quote reveal", "Follow for daily anime feelings"],
        "vfx": "slow drift, rain-style lines, muted glow",
        "mood": "rainy cinematic loop",
    },
    "motivation": {
        "label": "Anime Motivation Short",
        "beats": ["Start weak", "Train daily", "Comeback arc", "Your story is still running"],
        "vfx": "speed lines, bright flares, rising energy",
        "mood": "fast transformation edit",
    },
    "lofi_loop": {
        "label": "Lo-fi Anime Loop",
        "beats": ["Night city vibe", "Soft study mood", "Clean anime loop", "Daily chill anime energy"],
        "vfx": "floating lights, soft grain, calm motion",
        "mood": "calm aesthetic loop",
    },
    "comedy_line": {
        "label": "Comedy Line Wallpaper",
        "beats": ["Funny line drop", "Quick smile beat", "Fresh wallpaper vibe", "Follow for daily lines"],
        "vfx": "bouncy text, bright cards, playful motion",
        "mood": "light comedy wallpaper edit",
    },
    "love_line": {
        "label": "Love Line Wallpaper",
        "beats": ["Soft intro", "Love line reveal", "Warm glow wallpaper", "Daily heart mood"],
        "vfx": "soft particles, warm gradient, slow zoom",
        "mood": "romantic wallpaper edit",
    },
    "motivation_line": {
        "label": "Motivation Line Wallpaper",
        "beats": ["Focus begins", "Motivation line hits", "Rise-up beat", "Save this mood"],
        "vfx": "speed lines, clean flash, strong typography",
        "mood": "power quote wallpaper edit",
    },
    "interesting_line": {
        "label": "Interesting Line Wallpaper",
        "beats": ["Curious start", "Thought line reveal", "Deep wallpaper motion", "Daily mind spark"],
        "vfx": "smooth parallax, light streaks, cinematic text",
        "mood": "interesting thought wallpaper edit",
    },
    "thought_line": {
        "label": "Thought Line Wallpaper",
        "beats": ["Calm opening", "Thought line appears", "Peaceful beat", "Keep this line"],
        "vfx": "slow drift, soft light, clean quote frame",
        "mood": "calm mood wallpaper edit",
    },
    "general_knowledge": {
        "label": "General Knowledge Wallpaper",
        "beats": ["Intriguing question", "Fact reveal", "Knowledge wave", "Follow for daily learning"],
        "vfx": "clean digital scan, bright highlights, info box animation",
        "mood": "modern smart wallpaper edit",
    },
    "story_line": {
        "label": "Story Line Wallpaper",
        "beats": ["Once upon a time", "Lesson drop", "Warm finish", "Share this story"],
        "vfx": "soft parchment scroll drift, warm ambient glow, steady focus",
        "mood": "inspirational narrative wallpaper edit",
    },
}



def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def is_today(value):
    try:
        return datetime.fromisoformat(str(value)).date() == datetime.now().date()
    except Exception:
        return False


def published_today_count(data):
    return sum(
        1 for draft in data.get("drafts", [])
        if draft.get("status") == "published" and is_today(draft.get("published_at") or draft.get("scheduled_time"))
    )


def is_weak_secret(value, kind="password"):
    text = str(value or "")
    weak_values = {
        "",
        "12345",
        "password",
        "admin",
        "admin123",
        "use_a_strong_private_password",
        "use_a_long_random_private_secret",
        "make_a_private_random_webhook_verify_token",
        "anime-nova-local-verify",
    }
    if text in weak_values:
        return True
    min_len = 16 if kind != "password" else 10
    return len(text) < min_len


def tomorrow_retry_time():
    tomorrow = datetime.now().date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time()).replace(hour=1).isoformat()


def pause_until_active(data):
    value = data.get("publish_paused_until")
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) > datetime.now()
    except Exception:
        return False


def is_meta_publish_limit(result):
    if not isinstance(result, dict):
        return False
    error = (result.get("response") or {}).get("error", {}) if isinstance(result.get("response"), dict) else {}
    if not error and isinstance(result.get("container_status"), dict):
        error = result.get("container_status", {}).get("error") or {}
    if not isinstance(error, dict):
        error = {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    msg = str(error.get("message", "")).lower()
    if code in [4, 9, 17, 32] or subcode in [2207042, 2207027, 1349210] or "request limit" in msg or "rate limit" in msg:
        return True
    return False


def status_after_publish_result(result):
    if result.get("published"):
        return "published"
    if is_meta_publish_limit(result):
        return "publish_rate_limited"
    return "publish_failed"


def record_publish_timing(data, result):
    if result.get("published") or is_meta_publish_limit(result):
        data["last_publish_attempt_at"] = now_iso()
    else:
        data["last_nonblocking_publish_failure_at"] = now_iso()


def latest_publish_error(data):
    for draft in data.get("drafts", []):
        result = draft.get("publish_result") or {}
        error = (result.get("response") or {}).get("error") if isinstance(result, dict) else None
        if error:
            return {
                "draft_id": draft.get("id"),
                "type": draft.get("type"),
                "status": draft.get("status"),
                "stage": result.get("stage"),
                "message": error.get("message"),
                "code": error.get("code"),
                "error_subcode": error.get("error_subcode"),
                "fbtrace_id": error.get("fbtrace_id"),
            }
        if result.get("stage") == "container_processing":
            return {
                "draft_id": draft.get("id"),
                "type": draft.get("type"),
                "status": draft.get("status"),
                "stage": "container_processing",
                "message": (result.get("container_status") or {}).get("status") or "Instagram media container did not finish processing.",
                "container_status": result.get("container_status"),
            }
    return {}


def seconds_until_publish_resume(data):
    value = data.get("publish_paused_until")
    if not value:
        return 0
    try:
        return max(0, int((datetime.fromisoformat(value) - datetime.now()).total_seconds()))
    except Exception:
        return 0


def recover_publish_rate_limits(data):
    changed = False
    if pause_until_active(data):
        return changed
    if data.get("publish_paused_until"):
        data["publish_paused_until"] = ""
        changed = True
    for draft in data.get("drafts", []):
        if draft.get("status") == "publish_rate_limited":
            draft["last_publish_limit_result"] = draft.get("publish_result")
            draft["publish_result"] = None
            draft["status"] = "ready_to_publish"
            changed = True
    return changed


def publish_interval_active(data):
    value = data.get("last_publish_attempt_at")
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) + timedelta(minutes=effective_publish_interval_minutes(data)) > datetime.now()
    except Exception:
        return False


def next_publish_attempt_at(data):
    value = data.get("last_publish_attempt_at")
    if not value:
        return ""
    try:
        return (datetime.fromisoformat(value) + timedelta(minutes=effective_publish_interval_minutes(data))).replace(microsecond=0).isoformat()
    except Exception:
        return ""


def effective_publish_interval_minutes(data):
    if published_today_count(data) < MAX_CONTENT_PER_DAY and datetime.now().hour >= 20:
        return min(PUBLISH_MIN_INTERVAL_MINUTES, 30)
    return PUBLISH_MIN_INTERVAL_MINUTES


def publish_candidate_sort_key(draft):
    priority = {
        "ready_to_publish": 0,
        "approved": 0,
        "publish_failed": 1,
        "publish_rate_limited": 2,
    }.get(draft.get("status"), 9)
    try:
        scheduled = datetime.fromisoformat(draft.get("scheduled_time") or "")
    except Exception:
        scheduled = datetime.max
    return (priority, scheduled, int(draft.get("id", 0)))


def inbox_empty_guidance():
    return [
        "Backend reply brain is working, but Meta returned zero Instagram conversations.",
        "If comments/messages are already subscribed, send a fresh new DM or comment from another Instagram account; old messages usually do not replay as webhooks.",
        "DM auto-reply can only run after Meta sends a webhook event or exposes a conversation through the Conversations API.",
        "Required Meta permissions: instagram_business_basic, instagram_business_manage_messages, and comment-management permission if comment replies are needed.",
        "In Meta app, verify this public callback URL, subscribe to Instagram messages/comments webhook fields, keep this Instagram account as Tester/Admin while unpublished, and accept any pending tester invite.",
        "In Instagram settings, allow message access for connected tools/business integrations if that toggle is available.",
    ]


def current_webhook_url():
    if PUBLIC_MEDIA_BASE_URL.endswith("/api/media/output"):
        return PUBLIC_MEDIA_BASE_URL[: -len("/api/media/output")] + "/webhook/instagram"
    return ""


def trycloudflare_tunnel_active_for(url):
    match = re.search(r"https://([a-z0-9-]+\.trycloudflare\.com)", str(url or ""))
    if not match:
        return False
    host = match.group(1)
    try:
        text = Path("cloudflared.log").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    if host not in text or "Registered tunnel connection" not in text:
        return False
    try:
        tasklist = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "cloudflared.exe" in (tasklist.stdout or "").lower()
    except Exception:
        return True


def local_tunnel_self_check_fallback(url, exc, kind):
    if not trycloudflare_tunnel_active_for(url):
        return None
    return {
        "ok": True,
        "assumed_external_ok": True,
        "url": url,
        "message": (
            f"{kind} local self-check could not connect from this Windows network "
            f"({type(exc).__name__}), but the Cloudflare tunnel is running and registered. "
            "External services like Meta may still be able to fetch it."
        ),
        "warning": "For production reliability, use a stable named Cloudflare tunnel, Cloudinary, Supabase/Firebase Storage, or another permanent HTTPS host.",
    }


def check_public_webhook(timeout=25):
    webhook_url = current_webhook_url()
    if not webhook_url:
        return {"ok": False, "message": "PUBLIC_MEDIA_BASE_URL is missing or not in /api/media/output form."}
    try:
        response = requests.get(
            webhook_url,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": WEBHOOK_VERIFY_TOKEN,
                "hub.challenge": "anime_nova_ok",
            },
            timeout=timeout,
        )
    except RequestException as exc:
        fallback = local_tunnel_self_check_fallback(webhook_url, exc, "Webhook")
        if fallback:
            return fallback
        return {
            "ok": False,
            "url": webhook_url,
            "message": f"Public webhook unreachable: {type(exc).__name__}. Cloudflare tunnel/public HTTPS host is down, expired, blocked, or not pointing to this backend.",
            "fix": "Start a stable public HTTPS tunnel/host, then update PUBLIC_MEDIA_BASE_URL and Meta callback URL.",
        }
    return {
        "ok": response.status_code == 200 and response.text.strip() == "anime_nova_ok",
        "url": webhook_url,
        "status_code": response.status_code,
        "challenge_matched": response.text.strip() == "anime_nova_ok",
        "message": "Public webhook verify OK." if response.status_code == 200 and response.text.strip() == "anime_nova_ok" else "Public webhook verify failed.",
    }


def cached_public_webhook_status(timeout=3, ttl=45):
    now = time.time()
    cached = PUBLIC_WEBHOOK_STATUS_CACHE.get("value")
    if cached is not None and now - float(PUBLIC_WEBHOOK_STATUS_CACHE.get("time") or 0) < ttl:
        return cached
    value = check_public_webhook(timeout=timeout)
    PUBLIC_WEBHOOK_STATUS_CACHE["time"] = now
    PUBLIC_WEBHOOK_STATUS_CACHE["value"] = value
    return value


def check_public_media_url(url, timeout=25):
    if not str(url or "").startswith("https://"):
        return {"ok": False, "url": url, "message": "Missing public HTTPS media URL."}
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.close()
    except RequestException as exc:
        fallback = local_tunnel_self_check_fallback(url, exc, "Media URL")
        if fallback:
            fallback["content_type"] = "video/mp4" if str(url).lower().endswith((".mp4", ".mov")) else "image/jpeg"
            fallback["message"] += " The media file is served by this backend path."
            return fallback
        return {
            "ok": False,
            "url": url,
            "message": f"Public media unreachable: {type(exc).__name__}. Instagram cannot fetch local PC media unless the public HTTPS tunnel/host is live.",
            "fix": "Use a live Cloudflare tunnel, Cloudinary, Supabase/Firebase Storage, or another stable public HTTPS media host.",
        }
    content_type = response.headers.get("content-type", "")
    length = response.headers.get("content-length", "")
    ok = response.status_code in [200, 206] and (content_type.startswith("video/") or content_type.startswith("image/"))
    return {
        "ok": ok,
        "url": url,
        "status_code": response.status_code,
        "content_type": content_type,
        "content_length": length,
        "message": "Public media URL OK." if ok else "Public media URL is reachable but not a valid public image/video response.",
    }


def instagram_webhook_subscription_status():
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"ok": False, "message": "Instagram token is not connected.", "token_status": token_status}
    ig_user_id = token_status.get("id") or INSTAGRAM_USER_ID
    try:
        response = requests.get(
            f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_user_id}/subscribed_apps",
            params={"access_token": META_ACCESS_TOKEN},
            timeout=30,
        )
        result = response.json()
    except RequestException as exc:
        return {"ok": False, "message": f"Subscription check failed: {type(exc).__name__}"}
    except ValueError:
        return {"ok": False, "message": f"Subscription check returned non-JSON HTTP {response.status_code}"}
    fields = []
    for item in result.get("data", []) if isinstance(result, dict) else []:
        fields.extend(item.get("subscribed_fields") or [])
    fields = sorted(set(fields))
    required = {"comments", "messages"}
    return {
        "ok": isinstance(result, dict) and "error" not in result and required.issubset(set(fields)),
        "response": result,
        "subscribed_fields": fields,
        "missing_fields": sorted(required - set(fields)),
    }


def subscribe_instagram_webhook_fields():
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"ok": False, "message": "Instagram token is not connected.", "token_status": token_status}
    ig_user_id = token_status.get("id") or INSTAGRAM_USER_ID
    try:
        response = requests.post(
            f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_user_id}/subscribed_apps",
            data={"subscribed_fields": "comments,messages", "access_token": META_ACCESS_TOKEN},
            timeout=35,
        )
        result = response.json()
    except RequestException as exc:
        return {"ok": False, "message": f"Webhook subscription repair failed: {type(exc).__name__}"}
    except ValueError:
        return {"ok": False, "message": f"Webhook subscription repair returned non-JSON HTTP {response.status_code}"}
    status = instagram_webhook_subscription_status()
    return {
        "ok": bool(result.get("success")) and bool(status.get("ok")),
        "response": result,
        "subscription_status": status,
    }


def trim_active_line_queue(data):
    if CONTINUOUS_POST_MODE:
        return False
    changed = False
    max_active = max(0, MAX_CONTENT_PER_DAY - published_today_count(data))
    active = [
        draft for draft in data.get("drafts", [])
        if draft.get("status") in PUBLISHABLE_STATUSES and is_line_draft(draft)
    ]
    active.sort(key=lambda draft: int(draft.get("id", 0)), reverse=True)
    for draft in active[max_active:]:
        draft["status"] = "archived_previous_line_batch"
        draft["archive_reason"] = f"Only the remaining {max_active} daily line items stay active after today's published count."
        changed = True
    return changed


def prepare_publish_queue(data):
    if CONTINUOUS_POST_MODE:
        return load_db()
    changed = False
    if retire_legacy_ready_drafts(data):
        changed = True
    if trim_active_line_queue(data):
        changed = True
    if published_today_count(data) >= MAX_CONTENT_PER_DAY:
        for draft in data.get("drafts", []):
            if draft.get("status") in PUBLISHABLE_STATUSES and is_line_draft(draft):
                draft["status"] = "paused_daily_limit_reached"
                draft["archive_reason"] = f"Daily safe limit reached: {MAX_CONTENT_PER_DAY} posts."
                changed = True
        if changed:
            save_db(data)
        return load_db()
    remaining_today = max(0, MAX_CONTENT_PER_DAY - published_today_count(data))
    ready_count = len([d for d in data.get("drafts", []) if d.get("status") in PUBLISHABLE_STATUSES and is_line_draft(d)])
    if ready_count < remaining_today:
        generate_daily_plan_isolated()
        data = load_db()
        if trim_active_line_queue(data):
            changed = True
        changed = True
    if repair_interrupted_generation(data):
        changed = True
    for draft in data.get("drafts", [])[:MAX_CONTENT_PER_DAY * 4]:
        if draft.get("status") in PUBLISHABLE_STATUSES and is_line_draft(draft):
            if apply_public_media_url(draft):
                changed = True
            if not draft.get("public_media_url", "").startswith("https://") and cloudinary_ready():
                host_draft_media(draft)
                changed = True
            if draft.get("status") == "publish_rate_limited" and not pause_until_active(data):
                draft["status"] = "ready_to_publish"
                changed = True
    if changed:
        save_db(data)
    return load_db()


def publish_diagnostic():
    data = load_db()
    recover_publish_rate_limits(data)
    data = prepare_publish_queue(data)
    token_status = instagram_token_diagnostic()
    public_webhook = check_public_webhook()
    subscription = instagram_webhook_subscription_status()
    ready = [d for d in data.get("drafts", []) if d.get("status") in PUBLISHABLE_STATUSES and is_line_draft(d)]
    media_checks = []
    for draft in ready[:3]:
        media_checks.append({
            "draft_id": draft.get("id"),
            "type": draft.get("type"),
            "status": draft.get("status"),
            "topic": draft.get("topic"),
            "media": check_public_media_url(draft.get("public_media_url", "")),
        })
    paused = pause_until_active(data)
    interval_active = publish_interval_active(data)
    latest_error = latest_publish_error(data)
    blockers = []
    if not token_status.get("connected"):
        blockers.append("Instagram token is not connected.")
    if paused:
        blockers.append("Meta content publishing limit is active; queue will resume after pause time.")
    if interval_active:
        blockers.append("Safe publish pacing is active; the next queued item will be attempted later.")
    if not ready:
        blockers.append("No ready story/reel/post drafts are queued.")
    if media_checks and not any(item["media"].get("ok") for item in media_checks):
        blockers.append("Public media URLs are not reachable as valid public image/video responses.")
    if not public_webhook.get("ok"):
        blockers.append("Public webhook URL is not reachable; DM/comment webhooks cannot arrive.")
    if not subscription.get("ok"):
        blockers.append("Instagram messages/comments webhook fields are not subscribed.")
    message_reply_blocker = ""
    if public_webhook.get("ok") and subscription.get("ok"):
        data = load_db()
        webhook_status = webhook_reply_status(data)
        if webhook_status.get("status") != "webhook_received":
            message_reply_blocker = "No Meta webhook event has reached this backend yet, so there is no sender IGSID to reply to."
    return {
        "ok": True,
        "token": token_status,
        "public_webhook": public_webhook,
        "subscription": subscription,
        "publish_paused": paused,
        "publish_paused_until": data.get("publish_paused_until", ""),
        "retry_after_seconds": seconds_until_publish_resume(data),
        "publish_pacing_active": interval_active,
        "next_publish_attempt_at": next_publish_attempt_at(data),
        "queued_ready": len(ready),
        "published_today": published_today_count(data),
        "daily_limit": MAX_CONTENT_PER_DAY,
        "latest_error": latest_error,
        "media_checks": media_checks,
        "can_attempt_publish": bool(token_status.get("connected")) and not paused and not interval_active and bool(ready) and (not media_checks or any(item["media"].get("ok") for item in media_checks)),
        "message_reply_blocker": message_reply_blocker,
        "highlight_note": "Instagram API can publish stories, but it does not provide a supported endpoint to add stories into Highlights automatically.",
        "blockers": blockers,
    }


def default_db():
    return {
        "settings": ALL_SETTINGS.copy(),
        "logs": [],
        "drafts": [],
        "analytics": [],
        "growth": [],
        "suggestions": [],
        "highlights": [],
        "profiles": [],
        "reply_tests": [],
        "incoming_messages": [],
        "line_memory": [],
        "reply_memory": {},
        "last_reply_retry": {},
        "last_webhook_event": {},
        "webhook_events": [],
        "last_instagram_test": {},
        "startup_scan": {},
        "startup_scan_history": [],
        "publish_paused_until": "",
        "last_publish_attempt_at": "",
        "next_id": 1,
    }


def load_db():
    with DB_LOCK:
        if not DB.exists():
            save_db(default_db())
        try:
            data = json.loads(DB.read_text(encoding="utf-8"))
        except Exception:
            backup = DB.with_suffix(".json.bak")
            if backup.exists():
                try:
                    data = json.loads(backup.read_text(encoding="utf-8"))
                except Exception:
                    data = default_db()
            else:
                data = default_db()
        base = default_db()
        for k, v in base.items():
            data.setdefault(k, v)
        for k, v in ALL_SETTINGS.items():
            data["settings"].setdefault(k, v)
        for k in BLOCKED:
            data["settings"][k] = False
        return data


def save_db(data):
    with DB_LOCK:
        backup = DB.with_suffix(".json.bak")
        if DB.exists():
            try:
                shutil.copyfile(DB, backup)
            except Exception:
                pass
        tmp = DB.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(DB)


def next_id(data):
    value = int(data.get("next_id", 1))
    data["next_id"] = value + 1
    return value


def add_log(event, message):
    data = load_db()
    data["logs"].insert(0, {"id": next_id(data), "event": event, "time": now_iso(), "message": str(message)})
    data["logs"] = data["logs"][:500]
    save_db(data)


def read_env_keys():
    env_path = Path(".env")
    keys = []
    if not env_path.exists():
        return keys
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match:
            keys.append(match.group(1))
    return sorted(set(keys))


def file_fingerprint(filename):
    path = Path(filename)
    if not path.exists():
        return {"path": filename, "exists": False}
    data = path.read_bytes()
    return {
        "path": filename,
        "exists": True,
        "size": len(data),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat(),
        "sha256": hashlib.sha256(data).hexdigest()[:16],
    }


def build_startup_scan(previous=None):
    env_keys = read_env_keys()
    env_present = {key: bool(os.getenv(key, "")) for key in REQUIRED_ENV_KEYS}
    files = [file_fingerprint(name) for name in STARTUP_SCAN_FILES]
    previous_files = {item.get("path"): item.get("sha256") for item in (previous or {}).get("files", []) if item.get("exists")}
    changed_files = [
        item["path"] for item in files
        if item.get("exists") and previous_files.get(item["path"]) and previous_files.get(item["path"]) != item.get("sha256")
    ]
    missing_required = [key for key, present in env_present.items() if not present]
    warnings = []
    if missing_required:
        warnings.append("Missing required .env keys: " + ", ".join(missing_required))
    if PUBLIC_MEDIA_BASE_URL and not PUBLIC_MEDIA_BASE_URL.startswith("https://"):
        warnings.append("PUBLIC_MEDIA_BASE_URL must be HTTPS for Instagram publishing.")
    if not Path("app.html").exists():
        warnings.append("app.html missing.")
    if not Path("privacy.html").exists() or not Path("data-deletion.html").exists():
        warnings.append("Meta review pages missing.")
    if is_weak_secret(ADMIN_PASSWORD, "password"):
        warnings.append("ADMIN_PASSWORD is weak or default; change it before keeping the dashboard public.")
    if is_weak_secret(JWT_SECRET, "jwt"):
        warnings.append("JWT_SECRET is weak or default.")
    if is_weak_secret(WEBHOOK_VERIFY_TOKEN, "webhook"):
        warnings.append("WEBHOOK_VERIFY_TOKEN is weak/default; use a private random value for production.")
    if not CORS_ORIGINS:
        warnings.append("CORS_ORIGINS is empty; same-origin dashboard works, but cross-origin tools will be blocked.")
    if "*" in CORS_ORIGINS:
        warnings.append("CORS_ORIGINS contains wildcard; avoid this on a public server.")
    return {
        "time": now_iso(),
        "app": APP_NAME,
        "brand": BRAND,
        "env_file_present": Path(".env").exists(),
        "env_keys": env_keys,
        "required_env_present": env_present,
        "public_media_base_url_set": bool(PUBLIC_MEDIA_BASE_URL),
        "webhook_url": PUBLIC_MEDIA_BASE_URL[: -len("/api/media/output")] + "/webhook/instagram" if PUBLIC_MEDIA_BASE_URL.endswith("/api/media/output") else "",
        "auto_publish_enabled": AUTO_PUBLISH_ENABLED,
        "auto_reply_send_enabled": AUTO_REPLY_SEND_ENABLED,
        "inbox_poll_enabled": INBOX_POLL_ENABLED,
        "nova_reply_ai_enabled": NOVA_REPLY_AI_ENABLED,
        "media_input_dir": str(MEDIA_INPUT_DIR),
        "media_output_dir": str(MEDIA_OUTPUT_DIR),
        "files": files,
        "changed_files_since_last_start": changed_files,
        "warnings": warnings,
        "status": "warning" if warnings else "ok",
    }


def run_startup_self_scan():
    if not OPERATION_LOCK.acquire(timeout=5):
        data = load_db()
        previous = data.get("startup_scan") or {}
        scan = build_startup_scan(previous)
        scan["status"] = "busy"
        scan["warnings"] = list(scan.get("warnings", [])) + ["Another operation is running; deep repair scan skipped this time."]
        data["startup_scan"] = scan
        data.setdefault("startup_scan_history", []).insert(0, {
            "time": scan["time"],
            "status": scan["status"],
            "warnings": scan["warnings"],
            "changed_files": scan["changed_files_since_last_start"],
        })
        data["startup_scan_history"] = data["startup_scan_history"][:25]
        save_db(data)
        return scan
    try:
        data = load_db()
        repaired = repair_interrupted_generation(data)
        urls_refreshed = refresh_stale_public_media_urls(data)
        limit_recovered = recover_publish_rate_limits(data)
        previous = data.get("startup_scan") or {}
        scan = build_startup_scan(previous)
        if repaired:
            scan["repaired_interrupted_generation"] = True
        if limit_recovered:
            scan["recovered_publish_rate_limit"] = True
        if urls_refreshed:
            scan["refreshed_public_media_urls"] = True
        data["startup_scan"] = scan
        history_item = {
            "time": scan["time"],
            "status": scan["status"],
            "warnings": scan["warnings"],
            "changed_files": scan["changed_files_since_last_start"],
        }
        data.setdefault("startup_scan_history", []).insert(0, history_item)
        data["startup_scan_history"] = data["startup_scan_history"][:25]
        data["logs"].insert(0, {
            "id": next_id(data),
            "event": "startup_scan",
            "time": scan["time"],
            "message": f"Startup scan {scan['status']}. Changed: {', '.join(scan['changed_files_since_last_start']) or 'none'}",
        })
        data["logs"] = data["logs"][:500]
        save_db(data)
        return scan
    finally:
        OPERATION_LOCK.release()


def auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="JWT_SECRET must be set in .env")
    if not credentials:
        raise HTTPException(status_code=401, detail="Login required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def login_client_key(request: Request):
    cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare_ip:
        return cloudflare_ip
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def check_login_rate_limit(request: Request):
    key = login_client_key(request)
    item = LOGIN_FAILURES.get(key, {"count": 0, "locked_until": 0})
    if item.get("locked_until", 0) > time.time():
        raise HTTPException(429, "Too many failed login attempts. Try again later.")
    return key


def record_login_failure(key):
    item = LOGIN_FAILURES.get(key, {"count": 0, "locked_until": 0})
    item["count"] = int(item.get("count", 0)) + 1
    if item["count"] >= LOGIN_MAX_FAILURES:
        item["locked_until"] = time.time() + LOGIN_LOCK_SECONDS
    LOGIN_FAILURES[key] = item


def clear_login_failure(key):
    LOGIN_FAILURES.pop(key, None)


def contains_any(text, words):
    lower = (text or "").lower()
    return any(w in lower for w in words)


def nova_normalize_text(text):
    c = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    for before, after in HINGLISH_FILLERS.items():
        c = re.sub(r"(?<!\w)" + re.escape(before) + r"(?!\w)", after, c)
    return re.sub(r"\s+", " ", c).strip()


def redact_private_text(text):
    value = str(text or "")
    value = re.sub(r"[A-Za-z0-9_\-]{32,}", "[redacted-secret]", value)
    value = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "[redacted-email]", value)
    value = re.sub(r"\b(?:\+?\d[\d\s\-()]{7,}\d)\b", "[redacted-phone]", value)
    return value[:1200]


def safety_check(text):
    reasons = []
    if contains_any(text, NSFW_WORDS):
        reasons.append("NSFW / 18+ content blocked")
    if contains_any(text, SPAM_WORDS):
        reasons.append("Spam/scam content held")
    if contains_any(text, ABUSE_WORDS):
        reasons.append("Abusive content blocked")
    if re.search(r"https?://|www\.", text or "", re.I):
        reasons.append("Unknown link held for review")
    return {"safe": not reasons, "reasons": reasons}


def hashtags(category):
    if category in LINE_CATEGORIES:
        base = ["#dailyquotes", "#reelsindia", "#moodlines", "#quotereels", f"#{BRAND.replace('.', '').lower()}"]
    else:
        base = ["#anime", "#otaku", "#animeindia", "#animelovers", "#animevibes", f"#{BRAND.replace('.', '').lower()}"]
    extra = {
        "funny": ["#animememes", "#animefunny"],
        "romantic": ["#animeromance", "#animecouple"],
        "action": ["#animeaction", "#shonen"],
        "adventure": ["#animeadventure", "#isekai"],
        "cute": ["#kawaii", "#cuteanime"],
        "emotional": ["#animequotes", "#sadanime"],
        "motivational": ["#motivation", "#animequote"],
        "quotes": ["#quotes", "#animequote"],
        "memes": ["#memes", "#animememe"],
        "comedy_line": ["#funnyquotes", "#comedyreels", "#relatable"],
        "love_line": ["#lovelines", "#romanticquotes", "#heartfelt"],
        "motivation_line": ["#motivation", "#discipline", "#successmindset"],
        "interesting_line": ["#deepquotes", "#mindset", "#thoughts"],
        "thought_line": ["#lifequotes", "#peace", "#selfgrowth"],
    }.get(category, [])
    return base + extra


def safe_source_status():
    sources = [
        {"name": "AI-generated original visuals", "ready": True, "use": "Default video source"},
        {"name": "Pixabay royalty-free clips", "ready": bool(PIXABAY_API_KEY), "use": "Only clips whose license allows reuse/commercial posting"},
        {"name": "ProductionCrate VFX", "ready": bool(PRODUCTIONCRATE_API_KEY), "use": "Only licensed VFX/effects"},
        {"name": "Runway generation", "ready": bool(RUNWAY_API_KEY), "use": "Original generated scenes only"},
        {"name": "Pika generation", "ready": bool(PIKA_API_KEY), "use": "Original generated scenes only"},
        {"name": "JSON2Video editing", "ready": bool(JSON2VIDEO_API_KEY), "use": "Programmatic edits, captions, watermark, and render jobs"},
        {"name": "Canva/CapCut editing", "ready": bool(CANVA_API_KEY), "use": "Use as editing/export service only if official access is configured"},
    ]
    return {"mode": SAFE_SOURCE_MODE, "sources": sources}


def choose_generation_source():
    if RUNWAY_API_KEY:
        return "runway_ready_local_fallback"
    if PIKA_API_KEY:
        return "pika_ready_local_fallback"
    if JSON2VIDEO_API_KEY:
        return "json2video_ready_local_fallback"
    return "built_in_original_generator"


def groq_generate_line(category, data):
    if not GROQ_API_KEY and not OPENROUTER_API_KEY:
        return ""
    label = LINE_CATEGORY_LABELS.get(category, category.replace("_", " "))
    used = [item.get("text", "") for item in data.get("line_memory", [])[:100] if item.get("text")]
    
    if category == "general_knowledge":
        prompt = (
            "Write exactly one mind-blowing, highly fascinating, and surprising general knowledge fact. "
            "The fact must be complete, accurate, and fully understandable. "
            "Style: viral hook, educational, premium, clean, no hashtags, no emoji, no quotes. "
            "Use simple English or natural Roman Hinglish. Keep it under 35 words. "
            "Do not copy these recent lines: " + "; ".join(used[:35])
        )
    elif category == "story_line":
        prompt = (
            "Write exactly one short, deep, and highly inspiring story or life lesson (2-3 sentences max). "
            "Make sure the story has a complete beginning, middle, and end so it is fully understandable. "
            "Style: motivational, profound wisdom, clean, no hashtags, no emoji, no quotes. "
            "Use soft English or simple Roman Hinglish. Keep it under 55 words. "
            "Do not copy these recent lines: " + "; ".join(used[:35])
        )
    elif category == "comedy_line":
        prompt = (
            "Write exactly one highly relatable, slightly sarcastic, and funny GenZ/anime observation or joke. "
            "It must be a complete observation that makes perfect sense and is immediately shareable. "
            "Style: witty, clean, high-relatability format, no hashtags, no emoji, no quotes. "
            "Use punchy English or natural Roman Hinglish (e.g. 'Dost fail ho toh dukh hota hai, par jab top kare toh zyada dukh hota hai'). "
            "Keep it under 25 words. Do not copy these recent lines: " + "; ".join(used[:35])
        )
    elif category == "love_line":
        prompt = (
            "Write exactly one beautiful, romantic, and deep quote about love, longing, care, or soul connection. "
            "It must be a complete, heartfelt statement. "
            "Style: aesthetic, emotional, poetic, clean, no hashtags, no emoji, no quotes. "
            "Use soft, heartfelt English or emotional Roman Hinglish (e.g. 'Kuch log dur rehkar bhi dil ke sabse pass hote hain'). "
            "Keep it under 25 words. Do not copy these recent lines: " + "; ".join(used[:35])
        )
    elif category == "motivation_line":
        prompt = (
            "Write exactly one powerful, disciplined, and high-energy motivational quote (stoic or grindset theme). "
            "It must be a complete, high-impact cold truth or advice. "
            "Style: intense, elite mindset, clean, success mindset, no hashtags, no emoji, no quotes. "
            "Use strong English or powerful Roman Hinglish (e.g. 'Kamyabi shor machayegi, bas tum chupchaap mehnat karte raho'). "
            "Keep it under 25 words. Do not copy these recent lines: " + "; ".join(used[:35])
        )
    else:
        prompt = (
            "Write exactly one deep thought, mysterious anime protagonist-like observation, or life perspective. "
            "It must be a complete, thought-provoking sentence. "
            "Style: aesthetic, dark vibe, clean, no hashtags, no emoji, no quotes. "
            "Use English or simple Roman Hinglish. "
            "Keep it under 25 words. Do not copy these recent lines: " + "; ".join(used[:35])
        )
        
    try:
        text = call_groq_nova(prompt) if GROQ_API_KEY else None
        if not text:
            text = call_openrouter_nova(prompt)
    except Exception as exc:
        add_log("groq_line", f"AI line generation failed: {type(exc).__name__}")
        try:
            text = call_openrouter_nova(prompt)
        except Exception:
            return ""
            
    line = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip("'")
    line = re.sub(r"^[-*\d\.\s]+", "", line).strip()
    max_len = 380 if category in ["general_knowledge", "story_line"] else 180
    if not line or len(line) > max_len or re.search(r"[\u0900-\u097F]", line):
        return ""
    safe = safety_check(line)
    if not safe.get("safe"):
        return ""
    if line_key(line) in recent_line_keys(data, None):
        return ""
    return line


def create_original_soundtrack(draft, duration):
    """Generate a fresh original beat so reels are not silent or copyright-dependent."""
    sample_rate = 44100
    category = draft.get("category", "motivational")
    seed = f"{draft.get('id','')}-{draft.get('topic','')}-{now_iso()[:10]}"
    rng = random.Random(seed)
    profiles = {
        "comedy_line": {"bpm": 116, "root": 261.63, "scale": [0, 2, 4, 7, 9], "kick": 0.10, "hat": 0.018, "pluck": 0.085, "pad": 0.035},
        "love_line": {"bpm": 88, "root": 293.66, "scale": [0, 3, 5, 7, 10], "kick": 0.045, "hat": 0.006, "pluck": 0.048, "pad": 0.11},
        "motivation_line": {"bpm": 132, "root": 246.94, "scale": [0, 2, 4, 7, 9], "kick": 0.17, "hat": 0.018, "pluck": 0.080, "pad": 0.060},
        "interesting_line": {"bpm": 100, "root": 220.0, "scale": [0, 2, 5, 7, 11], "kick": 0.070, "hat": 0.010, "pluck": 0.060, "pad": 0.105},
        "thought_line": {"bpm": 82, "root": 196.0, "scale": [0, 3, 5, 7, 10], "kick": 0.040, "hat": 0.006, "pluck": 0.045, "pad": 0.115},
        "general_knowledge": {"bpm": 95, "root": 220.0, "scale": [0, 2, 4, 7, 9], "kick": 0.080, "hat": 0.012, "pluck": 0.070, "pad": 0.090},
        "story_line": {"bpm": 90, "root": 196.0, "scale": [0, 3, 5, 7, 10], "kick": 0.060, "hat": 0.008, "pluck": 0.055, "pad": 0.100},
    }
    profile = profiles.get(category, {"bpm": 120, "root": 220.0, "scale": [0, 2, 4, 7, 9], "kick": 0.14, "hat": 0.02, "pluck": 0.075, "pad": 0.05})
    bpm = profile["bpm"] + rng.choice([-4, -2, 0, 2, 4])
    root = profile["root"] * (2 ** (rng.choice([-2, 0, 2]) / 12.0))
    scale = profile["scale"]
    chords = [
        [0, 7, 12],
        [scale[1], scale[3], scale[-1]],
        [scale[2], scale[4], 12],
        [0, scale[2], scale[3]],
    ]
    out_path = MEDIA_OUTPUT_DIR / f"audio_{draft.get('id', int(time.time()))}_{int(time.time())}.wav"
    total_samples = int(duration * sample_rate)
    chunk = bytearray()
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for n in range(total_samples):
            t = n / sample_rate
            beat = (t * bpm / 60.0) % 1.0
            step = int(t * bpm / 60.0)
            bar = step // 4
            chord = chords[bar % len(chords)]
            lead_note = scale[(int(t * 2.0) + bar) % len(scale)]
            lead_freq = root * (2 ** (lead_note / 12.0))
            chord_sample = 0.0
            for idx, chord_note in enumerate(chord):
                freq = (root / 2.0) * (2 ** (chord_note / 12.0))
                chord_sample += math.sin(2 * math.pi * freq * t + idx * 0.4) / len(chord)
            pluck_env = max(0.0, 1.0 - beat * 5.0)
            lead = profile["pluck"] * math.sin(2 * math.pi * lead_freq * t) * pluck_env
            shimmer = profile["hat"] * math.sin(2 * math.pi * (5200 + 800 * math.sin(t * 0.9)) * t)
            if not (beat < 0.055 or 0.49 < beat < 0.545):
                shimmer *= 0.20
            kick_env = max(0.0, 1.0 - beat * 12.0)
            kick = profile["kick"] * math.sin(2 * math.pi * (58 - beat * 24) * t) * kick_env
            bass_note = chord[0]
            bass = 0.05 * math.sin(2 * math.pi * (root / 4.0) * (2 ** (bass_note / 12.0)) * t)
            pad = profile["pad"] * chord_sample * (0.72 + 0.28 * math.sin(2 * math.pi * 0.04 * t))
            noise_gate = 0.985 + 0.015 * math.sin(2 * math.pi * (0.07 + rng.random() * 0.02) * t)
            sample = max(-0.88, min(0.88, (pad + lead + kick + bass + shimmer) * noise_gate * 0.78))
            pan = 0.12 * math.sin(2 * math.pi * 0.035 * t)
            left = int(max(-0.92, min(0.92, sample * (1.0 - pan))) * 32767)
            right = int(max(-0.92, min(0.92, sample * (1.0 + pan))) * 32767)
            chunk.extend(struct.pack("<hh", left, right))
            if len(chunk) >= 8192:
                wav.writeframes(chunk)
                chunk.clear()
        if chunk:
            wav.writeframes(chunk)
    return out_path


def random_schedule(slot, offset_index=None):
    if offset_index is not None:
        return (datetime.now() + timedelta(minutes=DAILY_POST_SPACING_MINUTES * int(offset_index))).replace(microsecond=0).isoformat()
    hour = {
        "Morning": random.randint(8, 10),
        "Afternoon": random.randint(13, 15),
        "Evening": random.randint(18, 20),
        "Night": random.randint(21, 23),
        "Extra": random.choice([11, 16, 19, 22]),
    }[slot]
    return datetime.now().replace(hour=hour, minute=random.choice([5, 12, 21, 35, 47, 55]), second=0, microsecond=0).isoformat()


def create_original_visual(draft):
    """Create an original safe line wallpaper card; no copyrighted character scraping."""
    is_story = draft.get("type") == "story"
    width, height = (1080, 1920) if is_story else (1080, 1350)
    palette = {
        "funny": ((255, 209, 102), (17, 138, 178), (7, 59, 76)),
        "romantic": ((255, 170, 200), (179, 136, 255), (55, 30, 80)),
        "action": ((255, 89, 94), (25, 130, 196), (10, 15, 35)),
        "adventure": ((6, 214, 160), (17, 138, 178), (10, 35, 45)),
        "cute": ((255, 202, 212), (181, 234, 215), (70, 55, 90)),
        "emotional": ((116, 140, 171), (237, 242, 244), (28, 37, 65)),
        "motivational": ((255, 183, 3), (33, 158, 188), (2, 48, 71)),
        "quotes": ((205, 180, 219), (162, 210, 255), (45, 39, 70)),
        "memes": ((255, 214, 10), (131, 56, 236), (35, 20, 55)),
        "comedy_line": ((255, 214, 10), (38, 166, 154), (24, 34, 48)),
        "love_line": ((255, 145, 164), (255, 214, 186), (54, 30, 58)),
        "motivation_line": ((255, 190, 11), (33, 158, 188), (7, 24, 39)),
        "interesting_line": ((120, 160, 255), (20, 210, 190), (24, 28, 54)),
        "thought_line": ((176, 196, 222), (119, 221, 211), (28, 37, 65)),
        "general_knowledge": ((72, 191, 227), (247, 127, 0), (10, 25, 47)),
        "story_line": ((233, 196, 106), (244, 162, 97), (38, 70, 83)),
    }.get(draft.get("category"), ((139, 92, 246), (6, 182, 212), (12, 14, 35)))
    a, b, ink = palette
    img = Image.new("RGB", (width, height), ink)
    px = img.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            wave = (x / width) * 0.18
            mix = min(1, max(0, t + wave))
            px[x, y] = tuple(int(a[i] * (1 - mix) + b[i] * mix) for i in range(3))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(16):
        r = random.randint(80, 260)
        x = random.randint(-120, width)
        y = random.randint(-120, height)
        color = (*random.choice([a, b, ink]), random.randint(28, 75))
        draw.ellipse((x, y, x + r, y + r), fill=color)
    draw.rounded_rectangle((70, 90, width - 70, height - 90), radius=42, fill=(0, 0, 0, 82), outline=(255, 255, 255, 90), width=3)
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 66 if is_story else 58)
        body_font = ImageFont.truetype("arial.ttf", 42 if is_story else 36)
        small_font = ImageFont.truetype("arialbd.ttf", 34)
    except Exception:
        title_font = body_font = small_font = ImageFont.load_default()

    def wrapped(text, font, max_width):
        words = str(text).split()
        lines, line = [], ""
        for word in words:
            test = f"{line} {word}".strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines[:7]

    y = 150
    label = LINE_CATEGORY_LABELS.get(draft.get("category"), str(draft.get("category", "daily")).replace("_", " ").title())
    draw.text((100, y), f"{label.upper()} {draft.get('type', 'post').upper()}", font=small_font, fill=(255, 255, 255, 215))
    y += 105
    for line in wrapped(draft.get("topic", "Daily fresh line"), title_font, width - 200):
        draw.text((100, y), line, font=title_font, fill=(255, 255, 255, 245))
        y += 78
    y += 40
    caption = "Fresh daily line with original wallpaper. No 18+ content. No copyrighted song or repost."
    for line in wrapped(caption, body_font, width - 200):
        draw.text((100, y), line, font=body_font, fill=(255, 255, 255, 205))
        y += 54
    footer = f"{BRAND} | Daily fresh lines"
    box = draw.textbbox((0, 0), footer, font=small_font)
    draw.rounded_rectangle((90, height - 180, width - 90, height - 105), radius=24, fill=(0, 0, 0, 120))
    draw.text(((width - (box[2] - box[0])) // 2, height - 164), footer, font=small_font, fill=(255, 255, 255, 235))
    final = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    name = f"auto_{draft.get('id', int(time.time()))}_{draft.get('type', 'post')}_{int(time.time())}.jpg"
    out_path = MEDIA_OUTPUT_DIR / name
    final.save(out_path, quality=92)
    return name


def create_black_line_wallpaper_video(draft):
    """Create a dark quote-wallpaper video with original audio and no copied media."""
    width, height = 720, 1280
    fps = 12
    duration = random.randint(20, 40)
    total_frames = fps * duration
    category = draft.get("category", "thought_line")
    topic = str(draft.get("topic", "Daily fresh line")).strip()
    label = LINE_CATEGORY_LABELS.get(category, "Daily Line")
    heading = LINE_WALLPAPER_HEADINGS.get(category, label.lower())
    style = {
        "comedy_line": {"accent": (12, 45, 22), "glow": (150, 255, 190), "layout": "typewriter"},
        "love_line": {"accent": (48, 5, 12), "glow": (255, 80, 95), "layout": "heart"},
        "motivation_line": {"accent": (30, 34, 24), "glow": (245, 245, 210), "layout": "bold_day"},
        "interesting_line": {"accent": (10, 18, 38), "glow": (180, 205, 255), "layout": "minimal"},
        "thought_line": {"accent": (24, 24, 24), "glow": (210, 210, 210), "layout": "quiet"},
        "general_knowledge": {"accent": (10, 30, 48), "glow": (150, 220, 255), "layout": "bold_day"},
        "story_line": {"accent": (35, 20, 10), "glow": (255, 210, 150), "layout": "quiet"},
    }.get(category, {"accent": (18, 18, 18), "glow": (220, 220, 220), "layout": "minimal"})

    def font(names, size):
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        return ImageFont.load_default()

    serif_big = font(["georgiab.ttf", "timesbd.ttf", "arialbd.ttf"], 82)
    serif_mid = font(["georgia.ttf", "times.ttf", "arial.ttf"], 48)
    bold_huge = font(["impact.ttf", "arialbd.ttf"], 96)
    bold_big = font(["arialbd.ttf", "impact.ttf"], 58)
    bold_big_scaled = font(["arialbd.ttf", "impact.ttf"], 42)
    mono = font(["courbd.ttf", "consolab.ttf", "arialbd.ttf"], 38)
    mono_scaled = font(["courbd.ttf", "consolab.ttf", "arialbd.ttf"], 28)
    mono_small = font(["cour.ttf", "consola.ttf", "arial.ttf"], 24)
    small = font(["arialbd.ttf", "segoeuib.ttf"], 26)

    frame_dir = MEDIA_OUTPUT_DIR / f"frames_{draft.get('id', int(time.time()))}_{int(time.time())}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    audio_path = None
    start_time = datetime.now()
    day = start_time.strftime("%A")

    words_count = len(topic.split())
    layout_bold_big_font = bold_big_scaled if words_count > 12 else bold_big
    layout_mono_font = mono_scaled if words_count > 15 else mono

    def wrapped(draw, text, font_obj, max_width, max_lines=5):
        words = str(text).split()
        lines, line = [], ""
        for word in words:
            test = f"{line} {word}".strip()
            if draw.textbbox((0, 0), test, font=font_obj)[2] <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines[:max_lines]

    def draw_center(draw, text, y, font_obj, fill):
        box = draw.textbbox((0, 0), text, font=font_obj)
        tx = (width - (box[2] - box[0])) // 2
        # Draw soft drop shadow for readability
        draw.text((tx + 2, y + 2), text, font=font_obj, fill=(0, 0, 0, 180))
        draw.text((tx, y), text, font=font_obj, fill=fill)

    def draw_bg(phase):
        # Create a beautiful deep gradient background based on the style's accent color (ultra-fast resize method)
        accent = style["accent"]
        base_color = (6, 6, 12)
        base_img = Image.new("RGB", (1, 2))
        base_img.putpixel((0, 0), base_color)
        base_img.putpixel((0, 1), accent)
        # Resize using Bilinear interpolation to stretch the gradient smoothly across the full height
        img = base_img.resize((width, height), Image.BILINEAR)
                
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        accent = style["accent"]
        glow = style["glow"]
        pulse = 0.5 + 0.5 * math.sin(phase * math.pi * 2)
        
        # Draw glowing slow-moving background blobs
        for idx in range(9):
            x = int((idx * 117 + phase * 80 * (idx % 3 + 1)) % (width + 360)) - 220
            y = int((idx * 173 + phase * 55 * (idx % 4 + 1)) % (height + 420)) - 240
            r = 220 + (idx % 4) * 90
            alpha = 18 + int(pulse * 16) + idx % 9
            draw.ellipse((x, y, x + r, y + r), fill=(*accent, alpha))
            
        # Draw delicate animated tech/cyber grid
        grid_spacing = 60
        grid_offset = int((phase * 40) % grid_spacing)
        for x_line in range(grid_offset, width, grid_spacing):
            draw.line([(x_line, 0), (x_line, height)], fill=(*glow, 8))
        for y_line in range(grid_offset, height, grid_spacing):
            draw.line([(0, y_line), (width, y_line)], fill=(*glow, 8))
            
        # Draw glowing specs/stars
        for idx in range(42):
            x = int((idx * 47 + phase * 30) % width)
            y = int((idx * 97 + phase * 110) % height)
            if idx % 3 == 0:
                draw.point((x, y), fill=(*glow, 30))
            else:
                draw.rectangle((x, y, x + 1, y + 1), fill=(255, 255, 255, 12))
                
        vignette = Image.new("RGBA", img.size, (0, 0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        for ring in range(8):
            alpha = 8 + ring * 13
            vd.rounded_rectangle((ring * 18, ring * 28, width - ring * 18, height - ring * 28), radius=28, outline=(0, 0, 0, alpha), width=34)
        return Image.alpha_composite(Image.alpha_composite(img.convert("RGBA"), overlay), vignette)

    def draw_heart(draw, cx, cy, scale, fill, shadow):
        r = int(60 * scale)
        draw.ellipse((cx - r - int(34 * scale), cy - r, cx + int(4 * scale), cy + r), fill=shadow)
        draw.ellipse((cx - int(4 * scale), cy - r, cx + r + int(34 * scale), cy + r), fill=shadow)
        draw.polygon([(cx - int(92 * scale), cy + int(5 * scale)), (cx + int(92 * scale), cy + int(5 * scale)), (cx, cy + int(128 * scale))], fill=shadow)
        draw.ellipse((cx - r - int(22 * scale), cy - r - int(12 * scale), cx + int(16 * scale), cy + r - int(12 * scale)), fill=fill)
        draw.ellipse((cx - int(16 * scale), cy - r - int(12 * scale), cx + r + int(22 * scale), cy + r - int(12 * scale)), fill=fill)
        draw.polygon([(cx - int(84 * scale), cy - int(2 * scale)), (cx + int(84 * scale), cy - int(2 * scale)), (cx, cy + int(115 * scale))], fill=fill)

    def draw_line_block(draw, x, y, max_width, font_obj, fill, gap=10, max_lines=8):
        lines = wrapped(draw, topic, font_obj, max_width, max_lines)
        if not lines:
            return y
        # Calculate total height of the text block
        total_h = 0
        line_heights = []
        for line in lines:
            h = draw.textbbox((0, 0), line, font=font_obj)[3]
            line_heights.append(h)
            total_h += h + gap
        total_h -= gap # remove last gap
        
        # Draw glassmorphic card behind the text
        pad_x = 24
        pad_y = 20
        glow = style["glow"]
        # Draw semi-transparent card background with glow border
        draw.rounded_rectangle(
            (x - pad_x, y - pad_y, x + max_width + pad_x, y + total_h + pad_y),
            radius=16,
            fill=(0, 0, 0, 110),
            outline=(glow[0], glow[1], glow[2], 65),
            width=2
        )
        
        # Draw lines of text
        curr_y = y
        for idx, line in enumerate(lines):
            # Draw soft drop shadow for readability
            draw.text((x + 2, curr_y + 2), line, font=font_obj, fill=(0, 0, 0, 180))
            draw.text((x, curr_y), line, font=font_obj, fill=fill)
            curr_y += line_heights[idx] + gap
        return curr_y

    def draw_layout(draw, phase, clock):
        layout = style["layout"]
        glow = style["glow"]
        white = (245, 248, 242, 245)
        dim = (210, 215, 210, 190)
        cursor_on = int(phase * 24) % 2 == 0

        if layout == "heart":
            words = topic.upper().split()
            big = " ".join(words[:4]) or topic.upper()
            draw.text((-22, 92), big, font=bold_huge, fill=white)
            if len(words) > 4:
                draw.text((-8, 185), " ".join(words[4:8]), font=bold_huge, fill=(255, 255, 255, 210))
            draw_center(draw, clock, 315, mono_small, (230, 230, 230, 185))
            draw_heart(draw, width // 2, 575, 0.62 + 0.04 * math.sin(phase * math.pi * 4), (*glow, 235), (70, 70, 70, 180))
            draw_line_block(draw, 64, 805, width - 128, layout_bold_big_font, white, max_lines=6)
        elif layout == "bold_day":
            draw_center(draw, day.upper(), 390, bold_big, white)
            draw_center(draw, clock, 472, mono_small, dim)
            draw_line_block(draw, 58, 675, width - 116, layout_bold_big_font, white, max_lines=7)
        elif layout == "typewriter":
            draw.text((94, 145), day, font=serif_big, fill=white)
            draw_center(draw, clock, 268, mono_small, dim)
            draw.text((58, 590), heading.title(), font=mono, fill=white)
            y = draw_line_block(draw, 58, 665, width - 116, layout_mono_font, white, max_lines=8)
            if cursor_on:
                draw.rectangle((58 + int((phase * 200) % 90), y + 2, 78 + int((phase * 200) % 90), y + 40), fill=(155, 165, 155, 180))
        elif layout == "quiet":
            draw.text((120, 355), heading, font=serif_mid, fill=white)
            draw.text((120, 417), clock, font=mono_small, fill=dim)
            draw.text((120, 455), day, font=serif_mid, fill=(230, 230, 230, 180))
            draw_line_block(draw, 120, 630, width - 190, layout_mono_font, white, max_lines=8)
        else:
            draw_center(draw, day.upper(), 190, small, dim)
            draw_center(draw, clock, 235, mono_small, (190, 195, 190, 165))
            draw_line_block(draw, 72, 500, width - 144, layout_bold_big_font, white, max_lines=7)

        footer = f"@{BRAND.lstrip('@')}"
        box = draw.textbbox((0, 0), footer, font=small)
        # Watermark border matching the theme glow color
        draw.rounded_rectangle(
            (width - (box[2] - box[0]) - 46, height - 102, width - 24, height - 54),
            radius=18,
            fill=(10, 10, 18, 225),
            outline=(glow[0], glow[1], glow[2], 90),
            width=2
        )
        draw.text((width - (box[2] - box[0]) - 35, height - 92), footer, font=small, fill=(245, 245, 245, 230))
        draw.text((34, height - 93), label, font=mono_small, fill=(205, 205, 205, 150))

    try:
        for i in range(total_frames):
            phase = i / max(1, total_frames - 1)
            frame = draw_bg(phase)
            draw = ImageDraw.Draw(frame, "RGBA")
            clock = (start_time + timedelta(seconds=int(i / fps))).strftime("%H : %M : %S")
            draw_layout(draw, phase, clock)
            if phase > 0.90:
                fade = int(195 * min(1, (phase - 0.90) / 0.10))
                end = Image.new("RGBA", (width, height), (0, 0, 0, fade))
                ed = ImageDraw.Draw(end)
                handle = f"@{BRAND.lstrip('@')}"
                glow = style["glow"]
                
                # Draw soft glowing center aura behind the text
                for r in range(120, 240, 30):
                    ed.ellipse(
                        (width // 2 - r, height // 2 - r, width // 2 + r, height // 2 + r),
                        outline=(glow[0], glow[1], glow[2], int(15 * (1 - (r-120)/120))),
                        width=3
                    )
                
                draw_center(ed, handle, height // 2 - 45, bold_big, (255, 255, 255, 245))
                draw_center(ed, "daily fresh lines", height // 2 + 35, mono_small, (glow[0], glow[1], glow[2], 215))
                frame = Image.alpha_composite(frame, end)
            frame.convert("RGB").save(frame_dir / f"frame_{i:04d}.jpg", quality=90)

        name = f"auto_{draft.get('id', int(time.time()))}_blackline_{int(time.time())}.mp4"
        out_path = MEDIA_OUTPUT_DIR / name
        audio_path = create_original_soundtrack(draft, duration)
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%04d.jpg"),
            "-i",
            str(audio_path),
            "-t",
            str(duration),
            "-shortest",
            "-vf",
            "fps=30,format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        return name
    except Exception as exc:
        add_log("reel", f"Black line wallpaper video generation failed: {type(exc).__name__}")
        return ""
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
        if audio_path:
            Path(audio_path).unlink(missing_ok=True)


def create_original_reel_video(draft):
    """Create a short original vertical line wallpaper reel, not copied footage."""
    if draft.get("category") in LINE_CATEGORIES:
        return create_black_line_wallpaper_video(draft)
    width, height = 720, 1280
    fps = 15
    duration = random.randint(20, 40)
    total_frames = fps * duration
    template_key = draft.get("template") or random.choice(list(REEL_TEMPLATES.keys()))
    template = REEL_TEMPLATES.get(template_key, REEL_TEMPLATES["lofi_loop"])
    palette = {
        "funny": ((255, 209, 102), (17, 138, 178), (7, 59, 76)),
        "romantic": ((255, 170, 200), (179, 136, 255), (55, 30, 80)),
        "action": ((255, 89, 94), (25, 130, 196), (10, 15, 35)),
        "adventure": ((6, 214, 160), (17, 138, 178), (10, 35, 45)),
        "cute": ((255, 202, 212), (181, 234, 215), (70, 55, 90)),
        "emotional": ((116, 140, 171), (237, 242, 244), (28, 37, 65)),
        "motivational": ((255, 183, 3), (33, 158, 188), (2, 48, 71)),
        "quotes": ((205, 180, 219), (162, 210, 255), (45, 39, 70)),
        "memes": ((255, 214, 10), (131, 56, 236), (35, 20, 55)),
        "comedy_line": ((255, 214, 10), (38, 166, 154), (24, 34, 48)),
        "love_line": ((255, 145, 164), (255, 214, 186), (54, 30, 58)),
        "motivation_line": ((255, 190, 11), (33, 158, 188), (7, 24, 39)),
        "interesting_line": ((120, 160, 255), (20, 210, 190), (24, 28, 54)),
        "thought_line": ((176, 196, 222), (119, 221, 211), (28, 37, 65)),
        "general_knowledge": ((72, 191, 227), (247, 127, 0), (10, 25, 47)),
        "story_line": ((233, 196, 106), (244, 162, 97), (38, 70, 83)),
    }.get(draft.get("category"), ((139, 92, 246), (6, 182, 212), (12, 14, 35)))
    a, b, ink = palette
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 48)
        body_font = ImageFont.truetype("arial.ttf", 34)
        small_font = ImageFont.truetype("arialbd.ttf", 26)
    except Exception:
        title_font = body_font = small_font = ImageFont.load_default()

    frame_dir = MEDIA_OUTPUT_DIR / f"frames_{draft.get('id', int(time.time()))}_{int(time.time())}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    audio_path = None
    topic = str(draft.get("topic", "Daily fresh line"))
    beats = [template["label"], topic, *template["beats"], f"@{BRAND.lstrip('@')}"]

    def draw_wrapped(draw, text, font, xy, max_width, fill, line_gap=8, max_lines=4):
        words = str(text).split()
        lines, line = [], ""
        for word in words:
            test = f"{line} {word}".strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        x, y = xy
        for line in lines[:max_lines]:
            draw.text((x, y), line, font=font, fill=fill)
            y += draw.textbbox((0, 0), line, font=font)[3] + line_gap

    def scene_gradient(phase):
        img = Image.new("RGB", (width, height), ink)
        base = Image.new("RGB", (1, height), ink)
        base_px = base.load()
        shot = int(phase * 6) % 6
        for y in range(height):
            mix = min(1, max(0, (y / height) + 0.18 * math.sin((phase * 6.28) + y / 125)))
            base_px[0, y] = tuple(int(a[c] * (1 - mix) + b[c] * mix) for c in range(3))
        img = base.resize((width, height))
        draw = ImageDraw.Draw(img, "RGBA")
        horizon = 770 + int(math.sin(phase * 6.28) * 28)
        if shot in [0, 3]:
            for idx in range(9):
                x = idx * 92 - int((phase * 160) % 92) - 40
                h = 190 + ((idx * 73) % 260)
                draw.rectangle((x, horizon - h, x + 64, horizon), fill=(5, 10, 24, 150))
                for wy in range(horizon - h + 25, horizon - 18, 45):
                    draw.rectangle((x + 14, wy, x + 22, wy + 12), fill=(*a, 70))
        elif shot in [1, 4]:
            for idx in range(13):
                x = idx * 65 - int((phase * 260) % 65)
                draw.polygon([(x, horizon), (x + 34, horizon - 360 - (idx % 3) * 55), (x + 74, horizon)], fill=(4, 20, 18, 130))
        else:
            for idx in range(7):
                x = idx * 130 - int((phase * 180) % 130)
                draw.polygon([(x, horizon), (x + 45, horizon - 250), (x + 95, horizon)], fill=(10, 14, 28, 155))
                draw.rectangle((x + 30, horizon - 70, x + 78, horizon), fill=(10, 14, 28, 150))
        draw.rectangle((0, horizon, width, height), fill=(0, 0, 0, 38))
        return img

    def draw_original_character(draw, phase):
        shot = int(phase * 6) % 6
        punch = abs(math.sin(phase * math.pi * 12))
        close = shot in [0, 5]
        cx = width // 2 + int(math.sin(phase * 12.56) * (42 if close else 22))
        cy = 590 + int(math.cos(phase * 8.28) * 22)
        scale = 1.7 if close else 1.0 + 0.12 * punch
        hair = (18, 22, 36, 245)
        skin = (255, 216, 183, 238)
        coat = (12, 20, 38, 238)
        trim = (*a, 210)
        aura = (*b, int(55 + 85 * punch))
        if shot == 5:
            draw.rectangle((0, 0, width, height), fill=(245, 245, 255, 210))
            hair = (8, 8, 10, 255)
            skin = (245, 245, 245, 255)
            coat = (10, 10, 12, 255)
            trim = (0, 0, 0, 255)
            aura = (0, 0, 0, 95)
        head_w = int(120 * scale)
        head_h = int(152 * scale)
        body_w = int(225 * scale)
        body_h = int(360 * scale)
        head_top = int(cy - 250 * scale)
        head_bottom = head_top + head_h
        body_top = head_bottom - int(18 * scale)
        body_bottom = body_top + body_h
        draw.ellipse((cx - int(170 * scale), cy - int(300 * scale), cx + int(170 * scale), cy + int(120 * scale)), fill=(0, 0, 0, 72))
        spikes = []
        for idx, angle in enumerate([-120, -88, -56, -26, 0, 26, 56, 88, 120]):
            rad = math.radians(angle)
            spikes.append((
                cx + int(math.sin(rad) * head_w * 0.72),
                head_top + int((0.55 - math.cos(rad) * 0.52) * head_h) - int((idx % 2) * 26 * scale),
            ))
        hair_poly = [(cx - head_w, head_top + int(head_h * 0.50)), *spikes, (cx + head_w, head_top + int(head_h * 0.50)), (cx + int(head_w * 0.72), head_top + int(head_h * 0.90)), (cx - int(head_w * 0.72), head_top + int(head_h * 0.90))]
        draw.polygon(hair_poly, fill=hair)
        draw.ellipse((cx - head_w // 2, head_top + int(head_h * 0.32), cx + head_w // 2, head_bottom), fill=skin, outline=(12, 13, 24, 190), width=max(2, int(3 * scale)))
        collar_y = body_top + int(70 * scale)
        draw.polygon([(cx - body_w, collar_y), (cx - int(80 * scale), body_top), (cx, body_top + int(85 * scale)), (cx + int(80 * scale), body_top), (cx + body_w, collar_y), (cx + int(175 * scale), body_bottom), (cx - int(175 * scale), body_bottom)], fill=coat)
        draw.polygon([(cx - int(110 * scale), body_top + int(5 * scale)), (cx, body_top + int(115 * scale)), (cx + int(110 * scale), body_top + int(5 * scale)), (cx + int(55 * scale), body_top + int(170 * scale)), (cx - int(55 * scale), body_top + int(170 * scale))], fill=(230, 235, 255, 215))
        draw.line((cx - int(170 * scale), collar_y, cx + int(170 * scale), collar_y), fill=trim, width=max(4, int(7 * scale)))
        eye_y = head_top + int(head_h * 0.63)
        eye_gap = int(38 * scale)
        eye_len = int(42 * scale)
        glow = int(130 + 90 * punch)
        eye_color = (*b, 255) if shot != 5 else (0, 0, 0, 255)
        draw.line((cx - eye_gap - eye_len, eye_y, cx - eye_gap + eye_len, eye_y - int(4 * scale)), fill=eye_color, width=max(4, int(6 * scale)))
        draw.line((cx + eye_gap - eye_len, eye_y - int(4 * scale), cx + eye_gap + eye_len, eye_y), fill=eye_color, width=max(4, int(6 * scale)))
        if template_key == "glow_eye" or shot in [0, 2]:
            draw.ellipse((cx - eye_gap - eye_len - 16, eye_y - 22, cx - eye_gap + eye_len + 16, eye_y + 22), outline=(*b, glow), width=max(3, int(5 * scale)))
            draw.ellipse((cx + eye_gap - eye_len - 16, eye_y - 22, cx + eye_gap + eye_len + 16, eye_y + 22), outline=(*b, glow), width=max(3, int(5 * scale)))
        mouth_y = eye_y + int(58 * scale)
        draw.line((cx - int(28 * scale), mouth_y, cx + int(28 * scale), mouth_y - int(3 * scale)), fill=(70, 26, 45, 200), width=max(2, int(3 * scale)))
        for ring in range(5):
            r = int((150 + ring * 68 + 24 * punch) * scale)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=aura, width=3)
        if close:
            draw.rectangle((0, height - 265, width, height), fill=(0, 0, 0, 85))
        else:
            draw.polygon([(cx - 130, body_top + 180), (cx - 330, body_top + 325), (cx - 300, body_top + 370), (cx - 115, body_top + 235)], fill=coat)
            draw.polygon([(cx + 130, body_top + 180), (cx + 330, body_top + 325), (cx + 300, body_top + 370), (cx + 115, body_top + 235)], fill=coat)

    def add_video_edit_vfx(draw, phase):
        shot = int(phase * 6) % 6
        flash = int(70 * max(0, math.sin(phase * math.pi * 22)))
        if flash:
            draw.rectangle((0, 0, width, height), fill=(255, 255, 255, flash))
        for slash in range(8):
            offset = int((phase * 920 + slash * 97) % (height + 260)) - 180
            draw.line((-80, offset, width + 80, offset - 190), fill=(255, 255, 255, 34 + (slash % 3) * 16), width=2 + slash % 4)
        if template_key == "sad_quote":
            for rain in range(34):
                rx = int((rain * 41 + phase * 520) % width)
                ry = int((rain * 83 + phase * 1200) % height)
                draw.line((rx, ry, rx - 22, ry + 95), fill=(255, 255, 255, 62), width=2)
        elif template_key == "motivation":
            for streak in range(28):
                sx = int((streak * 39 - phase * 760) % width)
                sy = int((streak * 67 + phase * 430) % height)
                draw.line((sx, sy, sx + 230, sy - 42), fill=(255, 255, 255, 70), width=5)
        elif template_key == "glow_eye":
            for ring in range(8):
                r = 160 + ring * 58 + int(18 * math.sin(phase * 6.28 + ring))
                draw.ellipse((width // 2 - r, 500 - r, width // 2 + r, 500 + r), outline=(*b, 42), width=4)
        else:
            for dot in range(38):
                dx = int((dot * 71 + phase * 180) % width)
                dy = int((dot * 109 + phase * 120) % height)
                draw.ellipse((dx, dy, dx + 8, dy + 8), fill=(255, 255, 255, 95))
        if shot == 5:
            for panel in range(4):
                x = panel * 190 - 50 + int(math.sin(phase * 9 + panel) * 18)
                draw.rectangle((x, 0, x + 10, height), fill=(0, 0, 0, 180))
            for ink_line in range(45):
                y = int((ink_line * 31 + phase * 260) % height)
                draw.line((0, y, width, y + random.randint(-12, 12)), fill=(0, 0, 0, 35), width=1)

    try:
        for i in range(total_frames):
            phase = i / max(1, total_frames - 1)
            img = scene_gradient(phase)
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            add_video_edit_vfx(draw, phase)
            panel_alpha = int(112 + 24 * math.sin(phase * math.pi * 2))
            draw.rounded_rectangle(
                (54, 175, width - 54, height - 315),
                radius=38,
                fill=(0, 0, 0, panel_alpha),
                outline=(255, 255, 255, 68),
                width=2,
            )
            for accent in range(5):
                ax = 92 + accent * 104 + int(math.sin(phase * 7 + accent) * 16)
                ay = 230 + int((phase * 230 + accent * 84) % 680)
                draw.line((ax, ay, ax + 170, ay - 36), fill=(255, 255, 255, 34), width=3)
            draw_wrapped(draw, topic, title_font, (90, 285), width - 180, (255, 255, 255, 248), line_gap=14, max_lines=5)
            draw_wrapped(
                draw,
                "Daily fresh line with a new wallpaper and original safe beat.",
                body_font,
                (90, 650),
                width - 180,
                (255, 255, 255, 210),
                line_gap=12,
                max_lines=3,
            )
            beat = beats[min(len(beats) - 1, int(phase * len(beats)))]
            draw.rectangle((0, 0, width, 90), fill=(0, 0, 0, 55))
            draw.text((36, 30), template["label"], font=small_font, fill=(255, 255, 255, 230))
            subtitle = beat
            sub_box = draw.textbbox((0, 0), subtitle, font=small_font)
            draw.rounded_rectangle((30, height - 235, width - 30, height - 160), radius=22, fill=(0, 0, 0, 178))
            draw.text(((width - (sub_box[2] - sub_box[0])) // 2, height - 215), subtitle, font=small_font, fill=(255, 255, 255, 245))
            brand_text = f"@{BRAND.lstrip('@')}"
            brand_box = draw.textbbox((0, 0), brand_text, font=small_font)
            draw.rounded_rectangle((width - 245, height - 126, width - 28, height - 78), radius=18, fill=(0, 0, 0, 185))
            draw.text((width - 230, height - 116), brand_text, font=small_font, fill=(255, 255, 255, 245))
            final = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            if phase > 0.90:
                end_overlay = Image.new("RGBA", (width, height), (0, 0, 0, int(170 * min(1, (phase - 0.90) / 0.10))))
                ed = ImageDraw.Draw(end_overlay)
                handle = f"@{BRAND.lstrip('@')}"
                try:
                    end_font = ImageFont.truetype("arialbd.ttf", 64)
                    tag_font = ImageFont.truetype("arial.ttf", 30)
                except Exception:
                    end_font = title_font
                    tag_font = small_font
                box = ed.textbbox((0, 0), handle, font=end_font)
                x = (width - (box[2] - box[0])) // 2
                y = height // 2 - 54
                ed.text((x + 3, y + 3), handle, font=end_font, fill=(0, 0, 0, 220))
                ed.text((x, y), handle, font=end_font, fill=(255, 255, 255, 255))
                sub = "daily fresh lines"
                sub_box = ed.textbbox((0, 0), sub, font=tag_font)
                ed.text(((width - (sub_box[2] - sub_box[0])) // 2, y + 84), sub, font=tag_font, fill=(255, 255, 255, 215))
                final = Image.alpha_composite(final.convert("RGBA"), end_overlay).convert("RGB")
            if draft.get("category") not in LINE_CATEGORIES:
                zoom = 1.06 + 0.05 * math.sin(phase * 6.28 * 3)
                zw, zh = int(width / zoom), int(height / zoom)
                ox = int((width - zw) / 2 + math.sin(phase * 6.28 * 7) * 8)
                oy = int((height - zh) / 2 + math.cos(phase * 6.28 * 5) * 8)
                final = final.crop((max(0, ox), max(0, oy), min(width, ox + zw), min(height, oy + zh))).resize((width, height))
            if i % (fps * 4) in [0, 1]:
                flash = Image.new("RGB", (width, height), (255, 255, 255))
                final = Image.blend(final, flash, 0.28)
            final.save(frame_dir / f"frame_{i:04d}.jpg", quality=88)

        name = f"auto_{draft.get('id', int(time.time()))}_reel_{int(time.time())}.mp4"
        out_path = MEDIA_OUTPUT_DIR / name
        audio_path = create_original_soundtrack(draft, duration)
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%04d.jpg"),
            "-i",
            str(audio_path),
            "-t",
            str(duration),
            "-shortest",
            "-vf",
            "fps=30,format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        return name
    except Exception as exc:
        add_log("reel", f"Original reel video generation failed: {type(exc).__name__}")
        return ""
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
        if audio_path:
            Path(audio_path).unlink(missing_ok=True)


def cloudinary_ready():
    return bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)


def upload_to_cloudinary(filename):
    if not cloudinary_ready():
        return {"uploaded": False, "message": "Cloudinary env missing: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"}
    path = MEDIA_OUTPUT_DIR / filename
    if not path.exists():
        return {"uploaded": False, "message": "Local media file not found"}
    timestamp = str(int(time.time()))
    suffix = path.suffix.lower()
    is_video = suffix in [".mp4", ".mov", ".m4v", ".webm"]
    resource_type = "video" if is_video else "image"
    mime = "video/mp4" if is_video else "image/jpeg"
    params = {
        "folder": CLOUDINARY_FOLDER,
        "timestamp": timestamp,
    }
    sign_base = "&".join(f"{key}={params[key]}" for key in sorted(params)) + CLOUDINARY_API_SECRET
    signature = hashlib.sha1(sign_base.encode("utf-8")).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"
    try:
        with path.open("rb") as media:
            response = requests.post(
                url,
                data={
                    "api_key": CLOUDINARY_API_KEY,
                    "timestamp": timestamp,
                    "folder": CLOUDINARY_FOLDER,
                    "signature": signature,
                },
                files={"file": (filename, media, mime)},
                timeout=60,
            )
        result = response.json()
    except RequestException as exc:
        return {"uploaded": False, "message": f"Cloudinary upload failed: {type(exc).__name__}"}
    except ValueError:
        return {"uploaded": False, "message": f"Cloudinary returned non-JSON HTTP {response.status_code}"}
    if "secure_url" not in result:
        return {"uploaded": False, "message": "Cloudinary rejected upload", "response": result}
    return {"uploaded": True, "secure_url": result["secure_url"], "public_id": result.get("public_id")}


def host_draft_media(draft):
    if draft.get("public_media_url", "").startswith("https://") and not public_media_url_is_stale(draft.get("public_media_url", "")):
        return {"uploaded": True, "secure_url": draft["public_media_url"], "already_hosted": True}
    filename = draft.get("local_watermarked_file")
    if not filename:
        return {"uploaded": False, "message": "No generated local media to host"}
    result = upload_to_cloudinary(filename)
    if result.get("uploaded"):
        draft["public_media_url"] = result["secure_url"]
        draft["hosting"] = {"provider": "cloudinary", "public_id": result.get("public_id"), "hosted_at": now_iso()}
    return result


def public_media_url_is_stale(url):
    if not url or not PUBLIC_MEDIA_BASE_URL:
        return False
    return "/api/media/output/" in url and not url.startswith(PUBLIC_MEDIA_BASE_URL + "/")


def apply_public_media_url(draft):
    current_url = draft.get("public_media_url", "")
    if current_url.startswith("https://") and not public_media_url_is_stale(current_url):
        return True
    filename = draft.get("local_watermarked_file") or Path(draft.get("local_media_url", "")).name
    if PUBLIC_MEDIA_BASE_URL and filename:
        draft["public_media_url"] = f"{PUBLIC_MEDIA_BASE_URL}/{filename}"
        return True
    return False


def refresh_stale_public_media_urls(data):
    changed = False
    for draft in data.get("drafts", []):
        if public_media_url_is_stale(draft.get("public_media_url", "")):
            changed = apply_public_media_url(draft) or changed
    return changed


def restore_safe_autopilot_settings(data):
    for key in SAFE_ON:
        data["settings"][key] = True
    for key in BLOCKED:
        data["settings"][key] = False
    data["settings"]["approval_screen"] = False
    for draft in data["drafts"]:
        if draft.get("status") == "waiting_approval":
            draft["status"] = "ready_to_publish"


def repair_interrupted_generation(data):
    changed = False
    for draft in data.get("drafts", []):
        if draft.get("status") != "generating":
            continue
        filename = draft.get("local_watermarked_file") or Path(draft.get("local_media_url", "")).name
        if filename and (MEDIA_OUTPUT_DIR / filename).exists():
            apply_public_media_url(draft)
            draft["status"] = draft.get("target_status_after_generation") or "ready_to_publish"
            draft["generation_recovered_at"] = now_iso()
        else:
            draft["status"] = "generation_failed"
            draft["generation_failed_at"] = now_iso()
        changed = True
    return changed


def is_line_draft(draft):
    return draft.get("category") in LINE_CATEGORIES


def line_key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def recent_line_keys(data, category=None):
    keys = {
        line_key(item.get("topic", ""))
        for item in data.get("drafts", [])
        if item.get("topic") and (category is None or item.get("category") == category)
    }
    for item in data.get("line_memory", []):
        if category is None or item.get("category") == category:
            key = line_key(item.get("text", ""))
            if key:
                keys.add(key)
    return {key for key in keys if key}


def remember_line_memory(data, draft):
    topic = str(draft.get("topic", "")).strip()
    if not topic:
        return
    memory = data.setdefault("line_memory", [])
    key = line_key(topic)
    memory[:] = [item for item in memory if line_key(item.get("text", "")) != key]
    memory.insert(0, {
        "text": topic,
        "category": draft.get("category", ""),
        "type": draft.get("type", ""),
        "created_at": now_iso(),
    })
    data["line_memory"] = memory[:10000]


def choose_fresh_line(category, data):
    used = recent_line_keys(data, None)
    
    # Try generating a fresh unique line up to 3 times
    for attempt in range(3):
        ai_line = groq_generate_line(category, data)
        if ai_line:
            key = line_key(ai_line)
            if key not in used:
                return ai_line
            else:
                add_log("continuous_post", f"Duplicate AI line detected on attempt {attempt+1}: {ai_line[:40]}... Regenerating.")
                
    options = TOPICS.get(category, TOPICS["thought_line"])
    fresh = [line for line in options if line_key(line) not in used]
    if fresh:
        return random.choice(fresh)
    generators = {
        "comedy_line": [
            ("My {} is {}, but my {} is still {}.", [
                ["plan", "vibe", "schedule", "routine", "mindset"],
                ["sleepy", "confused", "lazy", "broken", "offline"],
                ["attitude", "energy", "hustle", "style", "focus"],
                ["premium", "unlocked", "active", "full", "stoic"]
            ]),
            ("I came for {}, stayed for {}.", [
                ["peace", "fun", "clarity", "chill vibes", "learning"],
                ["the drama", "the snacks", "the memes", "the plot twist", "the chaotic energy"]
            ]),
            ("Today's mood: {} outside, {} inside.", [
                ["normal", "sleeping", "calm", "active", "busy"],
                ["full loading", "buffering", "grinding", "daydreaming", "overthinking"]
            ]),
            ("Life gave me {}, I replied with {}.", [
                ["pressure", "deadlines", "problems", "options", "questions"],
                ["a joke", "a meme", "no response", "silent grind", "music"]
            ]),
        ],
        "love_line": [
            ("Some hearts feel like {} even from {}.", [
                ["home", "peace", "warmth", "magic", "light"],
                ["far away", "a distance", "the crowd", "another city", "the silence"]
            ]),
            ("The best love is {}, not {}.", [
                ["peaceful", "honest", "simple", "calm", "safe"],
                ["confusing", "exhausting", "loud", "a test", "dramatic"]
            ]),
            ("One honest message can fix a whole {}.", [
                ["mood", "day", "week", "night", "mindset"]
            ]),
            ("If the care is real, even silence feels {}.", [
                ["warm", "safe", "peaceful", "beautiful", "enough"]
            ]),
        ],
        "motivation_line": [
            ("Build in silence until your {} becomes the answer.", [
                ["progress", "results", "success", "comeback", "growth"]
            ]),
            ("Your future needs {}, not another excuse.", [
                ["consistency", "action", "discipline", "focus", "grind"]
            ]),
            ("Start small, stay sharp, finish {}.", [
                ["strong", "first", "clean", "outstanding", "stoic"]
            ]),
            ("Pressure becomes power when you keep {}.", [
                ["moving", "grinding", "focused", "learning", "climbing"]
            ]),
        ],
        "interesting_line": [
            ("The quietest people often carry the {} thoughts.", [
                ["deepest", "loudest", "wildest", "most beautiful", "sharpest"]
            ]),
            ("Your attention is expensive; spend it on {}.", [
                ["growth", "yourself", "peace", "your goals", "what matters"]
            ]),
            ("Sometimes peace is the most powerful {}.", [
                ["reply", "flex", "answer", "move", "choice"]
            ]),
            ("The plot changes when your standards get {}.", [
                ["higher", "clearer", "sharper", "stronger", "different"]
            ]),
        ],
        "thought_line": [
            ("A calm mind can win what noise keeps {}.", [
                ["losing", "blocking", "wasting", "breaking", "confusing"]
            ]),
            ("Protect your peace like it protects your {}.", [
                ["future", "energy", "focus", "sanity", "dreams"]
            ]),
            ("Not every pause is defeat; sometimes it is {}.", [
                ["direction", "preparation", "rest", "clarity", "aim"]
            ]),
            ("Stay kind, but stop making yourself {}.", [
                ["small", "available", "exhausted", "powerless", "second"]
            ]),
        ],
    }
    pool = generators.get(category, generators["interesting_line"])
    all_used = recent_line_keys(data)
    for _ in range(40):
        template, words = random.choice(pool)
        candidate_words = []
        for slot in words:
            if isinstance(slot, list):
                candidate_words.append(random.choice(slot))
            else:
                candidate_words.append(slot)
        candidate = template.format(*candidate_words)
        if line_key(candidate) not in all_used:
            return candidate
    return random.choice(options)


def retire_legacy_ready_drafts(data):
    changed = False
    for draft in data.get("drafts", []):
        if draft.get("status") in PUBLISHABLE_STATUSES and not is_line_draft(draft):
            draft["status"] = "archived_legacy"
            draft["archive_reason"] = "User switched autopilot to daily line wallpaper posts only."
            changed = True
    return changed


def archive_existing_line_queue(data):
    changed = False
    for draft in data.get("drafts", []):
        if draft.get("status") in PUBLISHABLE_STATUSES and is_line_draft(draft):
            draft["status"] = "archived_previous_line_batch"
            draft["archive_reason"] = "A newer daily 5-line batch was generated."
            changed = True
    return changed


def build_draft(slot, content_type, category, scheduled_time=None):
    data = load_db()
    topic = choose_fresh_line(category, data) if category in LINE_CATEGORIES else random.choice(TOPICS[category])
    template_key = category if category in LINE_CATEGORIES else (random.choice(list(REEL_TEMPLATES.keys())) if content_type == "reel" else "")
    template = REEL_TEMPLATES.get(template_key, {})
    label = LINE_CATEGORY_LABELS.get(category, category.replace("_", " ").title())
    caption = (
        f"{topic}\n\n"
        f"Daily {label.lower()} with a fresh wallpaper and original safe beat.\n"
        f"Follow {BRAND} for 5 fresh daily lines."
    )
    script = (
        f"{slot} {content_type.upper()} PLAN\n"
        f"Line: {topic}\n"
        f"Template: {template.get('label', 'Original line wallpaper')}\n"
        f"Visual direction: animated original wallpaper with clean typography, no copied clips.\n"
        f"Source mode: AI-first, royalty-free verified, user-owned licensed media only.\n"
        f"VFX: {template.get('vfx', 'soft motion, clean typography, branded finish')}.\n"
        f"Watermark/end card: @{BRAND.lstrip('@')} in stylized text.\n"
        f"Caption/subtitles: ready. Hashtags: ready. Safety: checked.\n"
        f"Music note: a new original generated safe beat is added; no copyrighted random song."
    )
    full = f"{topic}\n{caption}\n{script}"
    safe = safety_check(full)
    return {
        "slot": slot,
        "type": content_type,
        "category": category,
        "topic": topic,
        "caption": caption,
        "hashtags": hashtags(category),
        "script": script,
        "safe": safe["safe"],
        "safety_reasons": safe["reasons"],
        "scheduled_time": scheduled_time or random_schedule(slot),
        "status": "ready_to_publish" if not load_db()["settings"].get("approval_screen") else "waiting_approval",
        "public_media_url": "",
        "local_media_url": "",
        "local_watermarked_file": "",
        "template": template_key,
        "source_mode": SAFE_SOURCE_MODE,
        "audio_policy": "royalty_free_original_or_instagram_approved_only",
        "publish_result": None,
        "generation_source": choose_generation_source(),
    }


def generate_daily_plan():
    data = load_db()
    retire_legacy_ready_drafts(data)
    archive_existing_line_queue(data)
    save_db(data)
    extra_cycle = ["comedy_line", "love_line", "motivation_line", "interesting_line"]
    extra_category = extra_cycle[datetime.now().timetuple().tm_yday % len(extra_cycle)]
    plan = [
        ("Morning", "story", "comedy_line"),
        ("Afternoon", "reel", "love_line"),
        ("Evening", "reel", "motivation_line"),
        ("Night", "story", "interesting_line"),
        ("Extra", "reel", extra_category),
    ]
    count = max(MIN_CONTENT_PER_DAY, min(MAX_CONTENT_PER_DAY, len(plan)))
    chosen = plan[:count]
    made = []
    for idx, item in enumerate(chosen, start=1):
        draft = build_draft(*item, scheduled_time=random_schedule(item[0], idx))
        draft["id"] = next_id(data)
        target_status = draft["status"]
        draft["target_status_after_generation"] = target_status
        draft["status"] = "generating"
        draft["created_at"] = now_iso()
        data["drafts"].insert(0, draft)
        remember_line_memory(data, draft)
        save_db(data)
        visual_name = create_original_reel_video(draft) if draft["type"] in ["reel", "story"] else create_original_visual(draft)
        if not visual_name:
            visual_name = create_original_visual(draft)
        data = load_db()
        current = next((item for item in data["drafts"] if item.get("id") == draft["id"]), draft)
        draft["local_watermarked_file"] = visual_name
        draft["local_media_url"] = f"/api/media/output/{visual_name}"
        if PUBLIC_MEDIA_BASE_URL and draft["type"] in ["post", "story", "reel"]:
            draft["public_media_url"] = f"{PUBLIC_MEDIA_BASE_URL}/{visual_name}"
        elif cloudinary_ready() and draft["type"] in ["post", "story", "reel"]:
            host_draft_media(draft)
        draft["status"] = target_status if visual_name else "generation_failed"
        draft["generated_at"] = now_iso()
        current.update(draft)
        made.append(current)
        save_db(data)
    save_db(data)
    add_log("content", f"Generated {len(made)} fresh daily line drafts.")
    return made


def generate_daily_plan_isolated():
    """Render daily videos in a child process so the web server stays responsive."""
    script = (
        "import json, main; "
        "items = main.generate_daily_plan(); "
        "print(json.dumps([item.get('id') for item in items]))"
    )
    env = os.environ.copy()
    env["ANIME_NOVA_GENERATION_CHILD"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=1200,
            env=env,
        )
        if result.returncode != 0:
            add_log("content", f"Isolated daily generation failed: {result.stderr[-500:]}")
            return []
        last_line = (result.stdout.strip().splitlines() or ["[]"])[-1]
        ids = set(json.loads(last_line))
        data = load_db()
        return [item for item in data.get("drafts", []) if item.get("id") in ids]
    except Exception as exc:
        add_log("content", f"Isolated daily generation failed: {type(exc).__name__}")
        return []


def reply_memory_note(sender_id):
    if not sender_id:
        return ""
    data = load_db()
    profile = data.get("reply_memory", {}).get(str(sender_id), {})
    recent = profile.get("recent", [])[:3]
    if not recent:
        return ""
    parts = []
    for item in recent:
        user_text = redact_private_text(item.get("message", ""))[:120]
        bot_text = redact_private_text(item.get("reply", ""))[:120]
        if user_text or bot_text:
            parts.append(f"user: {user_text} | last reply: {bot_text}")
    return " ; ".join(parts)[:500]


def remember_reply_memory(data, sender_id, message, reply, source):
    if not sender_id:
        return
    memory = data.setdefault("reply_memory", {})
    profile = memory.setdefault(str(sender_id), {"recent": [], "first_seen": now_iso(), "message_count": 0})
    profile["message_count"] = int(profile.get("message_count", 0)) + 1
    profile["last_seen"] = now_iso()
    recent = profile.setdefault("recent", [])
    recent.insert(0, {
        "message": redact_private_text(message),
        "reply": redact_private_text(reply),
        "source": source,
        "at": now_iso(),
    })
    profile["recent"] = recent[:8]
    if len(memory) > 500:
        keep = sorted(memory.items(), key=lambda item: item[1].get("last_seen", ""), reverse=True)[:500]
        data["reply_memory"] = dict(keep)


def nova_reply_prompt(message, source, memory_note=""):
    brand_handle = f"@{BRAND.lstrip('@')}"
    memory_line = f" Recent safe memory for this sender: {memory_note}. " if memory_note else " "
    limit = "under 160 characters" if str(source).startswith("comment") else "1-2 short friendly lines"
    return (
        f"You are Nova Reply Brain for Instagram anime page {brand_handle}. "
        "Reply naturally in the user's language style, usually Hinglish if the user uses Hinglish. "
        "Use Roman Hinglish / Latin letters only; never use Devanagari, Hindi script, or other non-Latin scripts. "
        "Use the recent safe memory only to avoid repeating the exact same reply; do not reveal that memory exists. "
        f"Keep it {limit}. Be warm, clear, and anime-fan friendly. "
        "Do not ask for private details, OTP, password, phone, email, token, or address. "
        "Do not mention unsafe automation, fake engagement, scraping, adult content, or copyrighted reposting. "
        "If they ask for clips/posts/reels, steer to clean original anime-style edits, royalty-free media, safe captions, and official Instagram audio. "
        "Do not ask them for copyrighted anime character or series clips; offer an original vibe/concept instead. "
        "Do not claim you already posted/replied/DM'd unless the app says it did. "
        + memory_line +
        f"Incoming {source}: {redact_private_text(message)}"
    )


def call_groq_nova(prompt):
    if not GROQ_API_KEY:
        return None
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.55,
            "max_tokens": 140,
        },
        timeout=18,
    )
    data = response.json()
    if response.status_code >= 400:
        raise RuntimeError(data.get("error", {}).get("message", "Groq API error"))
    return data["choices"][0]["message"]["content"].strip()


def call_openrouter_nova(prompt):
    if not OPENROUTER_API_KEY:
        return None
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": APP_NAME,
        },
        json={
            "model": "meta-llama/llama-3.1-8b-instruct:free",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.55,
            "max_tokens": 140,
        },
        timeout=18,
    )
    data = response.json()
    if response.status_code >= 400:
        raise RuntimeError(data.get("error", {}).get("message", "OpenRouter API error"))
    return data["choices"][0]["message"]["content"].strip()


def clean_nova_reply(reply, source):
    text = re.sub(r"\s+", " ", str(reply or "")).strip().strip('"')
    blocked_phrases = ["as an ai", "i am an ai", "i'm an ai", "as a bot", "i am a bot"]
    lower = text.lower()
    if any(phrase in lower for phrase in blocked_phrases):
        return ""
    if re.search(r"[\u0900-\u097F]", text):
        return ""
    limit = 180 if str(source).startswith("comment") else 520
    if len(text) > limit:
        text = text[: limit - 3].rsplit(" ", 1)[0].strip() + "..."
    return text


def nova_should_use_ai(message, source):
    if not NOVA_REPLY_AI_ENABLED:
        return False
    if GROQ_API_KEY:
        return True
    c = nova_normalize_text(message)
    if len(c) > 55 or "?" in str(message):
        return True
    hard_words = ["recommend", "suggest", "collab", "business", "promo", "copyright", "music", "song", "reel", "story", "anime", "edit", "kaise", "what", "how", "why"]
    if any(word in c for word in hard_words):
        return True
    return str(source).startswith("dm") and len(c.split()) >= 5


def nova_ai_reply(message, source, memory_note=""):
    if not nova_should_use_ai(message, source):
        return None
    providers = {
        "groq": call_groq_nova,
        "openrouter": call_openrouter_nova,
    }
    errors = []
    prompt = nova_reply_prompt(message, source, memory_note)
    for provider in NOVA_REPLY_PROVIDER_ORDER:
        fn = providers.get(provider)
        if not fn:
            continue
        try:
            reply = clean_nova_reply(fn(prompt), source)
            if reply:
                return {"reply": reply, "provider": provider}
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}")
    if errors:
        add_log("nova_reply", "Nova provider fallback: " + "; ".join(errors[-2:]))
    return None


def make_reply(message, style="friendly", source="dm", sender_id=None):
    safe = safety_check(message)
    if not safe["safe"]:
        return {"hold": True, "reply": "", "reasons": safe["reasons"]}
    memory_note = reply_memory_note(sender_id)
    ai = nova_ai_reply(message, source, memory_note)
    if ai:
        return {"hold": False, "reply": ai["reply"], "reasons": [], "assistant": "nova_ai_reply_brain", "provider": ai["provider"]}
    lower = nova_normalize_text(message)
    brand_handle = f"@{BRAND.lstrip('@')}"
    anime_options = "funny, cute, action, romantic, sad quote, motivation aur glow-eye edits"
    if contains_any(lower, PRIVATE_WORDS):
        answer = f"Ye {brand_handle} ka official anime page hai. Personal details private rakhe jate hain, but anime edits aur post updates yahin milenge."
    elif any(word in lower for word in ["price", "paid", "promotion", "collab", "business", "promo"]):
        answer = f"Collab/promo ke liye short details bhej do. {brand_handle} clean anime audience ke hisaab se review karega."
    elif any(word in lower for word in ["recommend", "suggest", "anime bata", "anime chahiye", "kya dekhu"]):
        answer = f"Aaj ke mood ke hisaab se {anime_options} me se koi vibe choose karo, main us style ki clean anime recommendation de dunga."
    elif any(word in lower for word in ["reel", "edit", "velocity", "glow"]):
        answer = "Reel edit vibe ready hai: glow, speed lines, clean subtitles, original beat aur safe watermark ke saath."
    elif any(word in lower for word in ["story", "status"]):
        answer = "Story ke liye clean anime mood, short caption, quote aur matching visual ready ho sakta hai."
    elif any(word in lower for word in ["song", "music", "audio"]):
        answer = "Audio ke liye original safe beat, royalty-free sound, ya Instagram-approved audio hi use hoga."
    elif "action" in lower:
        answer = "Action anime vibe: power-up, rival energy, speed lines aur glow effect best rahega."
    elif "romantic" in lower:
        answer = "Romantic anime vibe soft, clean aur wholesome rahega."
    elif "cute" in lower:
        answer = "Cute anime mood unlocked. Kawaii style story ya reel clean tarike se ready ho sakti hai."
    elif any(word in lower for word in ["thanks", "thank you", "nice", "good", "best"]):
        answer = f"Thank you! {brand_handle} par daily fresh lines aur clean quote reels aate rahenge."
    elif any(word in lower for word in ["hi", "hello", "hey", "hii", "bro"]):
        if memory_note:
            answer = f"Hey, welcome back! {brand_handle} par aaj fresh line reels ready hain. Tumhe comedy, love, motivation ya interesting vibe chahiye?"
        else:
            answer = f"Hey! Welcome to {brand_handle}. Tumhe comedy, love, motivation ya interesting line vibe me se kya pasand hai?"
    else:
        answer = f"Thanks for messaging {brand_handle}! Daily safe anime vibes ke liye follow karo. Tumhe kaunsi anime vibe chahiye?"
    if style == "funny":
        answer += " Anime energy high rakho!"
    if style == "professional":
        answer = answer.strip()
    if style == "anime fan style":
        answer += " Anime mode on."
    if str(source).startswith("comment") and len(answer) > 180:
        answer = answer[:177].rsplit(" ", 1)[0].strip() + "..."
    return {"hold": False, "reply": answer, "reasons": [], "assistant": "nova_local_reply_brain"}


def send_instagram_message(recipient_id, text):
    if not recipient_id:
        return {"sent": False, "message": "Missing Instagram recipient id"}
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"sent": False, "message": "Instagram token not connected.", "token_status": token_status}
    payload = {
        "recipient": {"id": str(recipient_id)},
        "message": {"text": text[:950]},
    }
    if token_status.get("token_type") == "instagram_login":
        url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/me/messages"
        params = {}
        headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    else:
        ig_user_id = token_status.get("id") or INSTAGRAM_USER_ID
        url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{ig_user_id}/messages"
        params = {"access_token": META_ACCESS_TOKEN}
        headers = {}
    try:
        response = requests.post(
            url,
            params=params,
            json=payload,
            headers=headers,
            timeout=35,
        )
        result = response.json()
    except RequestException as exc:
        return {"sent": False, "message": f"Instagram send failed: {type(exc).__name__}"}
    except ValueError:
        return {"sent": False, "message": f"Instagram returned non-JSON HTTP {response.status_code}"}
    return {"sent": "message_id" in result or "recipient_id" in result, "endpoint": url, "response": result}


def send_instagram_comment_reply(comment_id, text):
    if not comment_id:
        return {"sent": False, "message": "Missing Instagram comment id"}
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"sent": False, "message": "Instagram token not connected.", "token_status": token_status}
    graph_host = "graph.instagram.com" if token_status.get("token_type") == "instagram_login" else "graph.facebook.com"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"} if token_status.get("token_type") == "instagram_login" else {}
    data = {"message": text[:950]}
    if token_status.get("token_type") != "instagram_login":
        data["access_token"] = META_ACCESS_TOKEN
    try:
        response = requests.post(
            f"https://{graph_host}/{META_GRAPH_VERSION}/{comment_id}/replies",
            data=data,
            headers=headers,
            timeout=35,
        )
        result = response.json()
    except RequestException as exc:
        return {"sent": False, "message": f"Instagram comment reply failed: {type(exc).__name__}"}
    except ValueError:
        return {"sent": False, "message": f"Instagram returned non-JSON HTTP {response.status_code}"}
    return {"sent": "id" in result, "response": result}


def first_comment_text(draft):
    category = draft.get("category", "")
    prompts = {
        "comedy_line": [
            "Too real or too personal? Drop \"same\" if it hit.",
            "Honestly, this is so relatable it hurts. Tag a friend.",
            "Who else does this? Comment below!",
            "Tell me I'm not the only one who feels this way.",
            "Tag that one friend who is always like this."
        ],
        "love_line": [
            "Soft kind of love, quiet and real. Save this one.",
            "True connection doesn't need to be loud. It's just peaceful.",
            "Long distance or close by, true love stays the same.",
            "Share this with someone who is always on your mind.",
            "Save this if you feel this connection in your life."
        ],
        "motivation_line": [
            "Keep moving quietly. Your next version is watching.",
            "Discipline is what builds champions. Stay focused.",
            "Work in silence, let your results do the talking.",
            "Don't stop when you are tired. Stop when you are done.",
            "Grind now, celebrate later. Stay stoic."
        ],
        "interesting_line": [
            "Plot twist or truth? Tell me which one this feels like.",
            "Mind-blowing or just weird? What do you think?",
            "Save this to read it again when you need a perspective shift.",
            "Honestly, this makes so much sense if you think about it.",
            "Which side of the debate are you on? Comment below."
        ],
        "thought_line": [
            "Some lines stay in the mind longer than expected.",
            "Read that again. It hits different the second time.",
            "A simple thought, but a deep truth.",
            "Deep thoughts for quiet nights.",
            "Save this to remind yourself of this reality."
        ],
        "general_knowledge": [
            "Did you know this before? Save for later.",
            "Science or history, nature never fails to surprise.",
            "Share this fact with a friend who loves trivia.",
            "Did this blow your mind? Comment below!",
            "Save this fact to share at your next dinner conversation."
        ],
        "story_line": [
            "A short story with a deep lesson. Follow for more.",
            "The best lessons are hidden in the simplest stories.",
            "Save this story. Read it when you need a gentle reminder.",
            "Wisdom in three sentences. Share this message.",
            "What did you learn from this story? Drop a comment."
        ],
    }
    options = prompts.get(category, [
        "Which vibe next: comedy, love, motivation, or interesting?",
        "What do you think of this vibe? Comment below.",
        "Drop a like if this content hits the spot.",
        "Follow for more original daily quotes and facts."
    ])
    fallback = random.choice(options)
    
    if AI_FIRST_COMMENT_ENABLED:
        prompt = (
            "Write a highly engaging, relatable, and short first comment for an Instagram reel/post. "
            f"Post category: {category.replace('_', ' ')}. "
            f"Post content: \"{draft.get('topic', '')}\". "
            "Make it a cool, natural conversation starter or a relatable reaction. "
            "Use modern Latin English or simple Roman Hinglish. "
            f"Random variation seed: {random.randint(1000, 9999)}. Make sure it sounds unique and distinct from common templates. "
            "Keep it under 110 characters. Do NOT use any hashtags, do NOT use quotes, do NOT use emojis."
        )
        try:
            comment = call_groq_nova(prompt) or call_openrouter_nova(prompt)
            if comment:
                cleaned = clean_nova_reply(comment, "comment")
                if cleaned:
                    return cleaned
        except Exception:
            pass
    return fallback


def add_first_comment_to_media(media_id, draft):
    if not media_id:
        return {"sent": False, "message": "Missing published media id."}
    if draft.get("type") == "story":
        return {"sent": False, "skipped": True, "message": "Stories do not support a normal feed/reel first comment through the Instagram API."}
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"sent": False, "message": "Instagram token not connected.", "token_status": token_status}
    text = first_comment_text(draft)
    graph_host = "graph.instagram.com" if token_status.get("token_type") == "instagram_login" else "graph.facebook.com"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"} if token_status.get("token_type") == "instagram_login" else {}
    data = {"message": text[:950]}
    if token_status.get("token_type") != "instagram_login":
        data["access_token"] = META_ACCESS_TOKEN
    try:
        response = requests.post(
            f"https://{graph_host}/{META_GRAPH_VERSION}/{media_id}/comments",
            data=data,
            headers=headers,
            timeout=35,
        )
        result = response.json()
    except RequestException as exc:
        return {"sent": False, "message": f"Instagram first comment failed: {type(exc).__name__}"}
    except ValueError:
        return {"sent": False, "message": f"Instagram returned non-JSON HTTP {response.status_code}"}
    return {"sent": "id" in result, "comment": text, "response": result}


def after_successful_publish(draft, result):
    draft["published_at"] = now_iso()
    media_id = (result.get("response") or {}).get("id")
    if media_id:
        draft["instagram_media_id"] = media_id
    if draft.get("type") in ["reel", "post"] and not draft.get("first_comment_result"):
        draft["first_comment_result"] = add_first_comment_to_media(media_id, draft)


def send_instagram_auto_reply(target_id, text, source):
    if str(source).startswith("comment"):
        return send_instagram_comment_reply(target_id, text)
    return send_instagram_message(target_id, text)


def already_seen_message(data, message_id):
    if not message_id:
        return False
    return any(str(row.get("message_id", "")) == str(message_id) for row in data.get("incoming_messages", []))


def handle_incoming_instagram_message(sender_id, text, source="dm", raw=None, reply_target_id=None, message_id=None):
    data = load_db()
    if already_seen_message(data, message_id):
        return {"status": "duplicate", "message_id": message_id}
    reply = make_reply(text, "anime fan style", source, sender_id=sender_id)
    target_id = str(reply_target_id or sender_id or "")
    row = {
        "id": next_id(data),
        "message_id": str(message_id or ""),
        "time": now_iso(),
        "source": source,
        "sender_id": str(sender_id or ""),
        "reply_target_id": target_id,
        "message": text,
        "reply": reply.get("reply", ""),
        "hold": reply.get("hold", False),
        "reasons": reply.get("reasons", []),
        "send_result": None,
        "raw": raw or {},
    }
    setting_key = "auto_reply_comments" if str(source).startswith("comment") else "auto_reply_dm"
    can_send = AUTO_REPLY_SEND_ENABLED and data["settings"].get(setting_key) and not row["hold"] and bool(row["reply"])
    if can_send:
        row["send_result"] = send_instagram_auto_reply(target_id, row["reply"], source)
        row["status"] = "sent" if row["send_result"].get("sent") else "send_failed"
    else:
        row["status"] = "held" if row["hold"] else "drafted"
    data["incoming_messages"].insert(0, row)
    data["incoming_messages"] = data["incoming_messages"][:200]
    remember_reply_memory(data, sender_id or target_id, text, row["reply"], source)
    save_db(data)
    add_log("instagram_reply", f"Incoming {source} from {sender_id}: {row['status']}")
    return row


def retry_failed_replies(limit=10):
    data = load_db()
    candidates = [
        row for row in data.get("incoming_messages", [])
        if row.get("status") in ["send_failed", "drafted"]
        and not row.get("hold")
        and row.get("reply")
        and (row.get("reply_target_id") or row.get("sender_id"))
    ][:limit]
    if not candidates:
        return {"ok": True, "attempted": 0, "sent": 0, "message": "No failed reply drafts waiting."}
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        data["last_reply_retry"] = {
            "time": now_iso(),
            "attempted": 0,
            "sent": 0,
            "blocked": True,
            "message": "Instagram token not connected; keeping replies queued.",
            "token_status": {
                "connected": False,
                "stage": token_status.get("stage"),
                "message": token_status.get("message"),
            },
        }
        save_db(data)
        return {"ok": False, "attempted": 0, "sent": 0, "message": "Instagram token not connected; replies remain queued.", "token_status": token_status}
    attempted = 0
    sent_count = 0
    for row in candidates:
        attempted += 1
        target_id = str(row.get("reply_target_id") or row.get("sender_id") or "")
        result = send_instagram_auto_reply(target_id, row["reply"], row.get("source") or "dm")
        row["send_result"] = result
        row["retried_at"] = now_iso()
        if result.get("sent"):
            row["status"] = "sent"
            sent_count += 1
        else:
            row["status"] = "send_failed"
    data["last_reply_retry"] = {
        "time": now_iso(),
        "attempted": attempted,
        "sent": sent_count,
        "blocked": False,
    }
    save_db(data)
    add_log("instagram_reply", f"Retried replies: {sent_count}/{attempted} sent.")
    return {"ok": True, "attempted": attempted, "sent": sent_count}


def is_own_instagram_message(msg, token_status):
    sender = msg.get("from") or {}
    sender_id = str(sender.get("id") or "")
    sender_username = str(sender.get("username") or "").lower()
    own_ids = {str(INSTAGRAM_USER_ID), str(token_status.get("id") or "")}
    own_names = {str(token_status.get("username") or "").lower(), BRAND.lstrip("@").lower()}
    return bool(sender_id and sender_id in own_ids) or bool(sender_username and sender_username in own_names)


def poll_instagram_inbox(limit=8):
    if not INBOX_POLL_ENABLED:
        return {"ok": False, "message": "Inbox polling is off."}
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"ok": False, "message": "Instagram token not connected.", "token_status": token_status}
    fields = "id,updated_time,messages.limit(5){id,message,from,to,created_time}"
    ig_user_id = token_status.get("id") or INSTAGRAM_USER_ID
    if token_status.get("token_type") == "instagram_login":
        candidates = [
            {
                "name": "instagram_login_me",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/me/conversations",
                "params": {"fields": fields, "limit": str(limit)},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
            {
                "name": "instagram_login_me_platform",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/me/conversations",
                "params": {"fields": fields, "limit": str(limit), "platform": "instagram"},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
            {
                "name": "instagram_login_requests",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/me/conversations",
                "params": {"fields": fields, "limit": str(limit), "folder": "requests"},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
            {
                "name": "instagram_login_id",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_user_id}/conversations",
                "params": {"fields": fields, "limit": str(limit)},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
            {
                "name": "instagram_login_id_platform",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_user_id}/conversations",
                "params": {"fields": fields, "limit": str(limit), "platform": "instagram"},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
        ]
    else:
        candidates = [
            {
                "name": "facebook_graph_instagram",
                "url": f"https://graph.facebook.com/{META_GRAPH_VERSION}/{ig_user_id}/conversations",
                "params": {"platform": "instagram", "fields": fields, "limit": str(limit), "access_token": META_ACCESS_TOKEN},
                "headers": {},
            },
            {
                "name": "instagram_graph_id",
                "url": f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_user_id}/conversations",
                "params": {"fields": fields, "limit": str(limit)},
                "headers": {"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            },
        ]
    diagnostics = []
    result = None
    url = ""
    for candidate in candidates:
        try:
            response = requests.get(candidate["url"], params=candidate["params"], headers=candidate["headers"], timeout=35)
            candidate_result = response.json()
        except RequestException as exc:
            diagnostics.append({"name": candidate["name"], "endpoint": candidate["url"], "ok": False, "message": type(exc).__name__})
            continue
        except ValueError:
            diagnostics.append({"name": candidate["name"], "endpoint": candidate["url"], "ok": False, "message": f"Non-JSON HTTP {response.status_code}"})
            continue
        count = len(candidate_result.get("data", [])) if isinstance(candidate_result, dict) else 0
        item = {"name": candidate["name"], "endpoint": candidate["url"], "ok": "error" not in candidate_result, "conversations": count}
        if isinstance(candidate_result, dict) and "error" in candidate_result:
            item["error"] = {
                "message": candidate_result["error"].get("message"),
                "type": candidate_result["error"].get("type"),
                "code": candidate_result["error"].get("code"),
            }
        diagnostics.append(item)
        if isinstance(candidate_result, dict) and "error" not in candidate_result:
            if result is None or count > len(result.get("data", [])):
                result = candidate_result
                url = candidate["url"]
            if count > 0:
                break
    if result is None:
        disabled_msg = None
        for diag in diagnostics:
            err = diag.get("error", {})
            if isinstance(err, dict) and "disabled access to Instagram Direct Messaging" in str(err.get("message", "")):
                disabled_msg = err.get("message")
                break
        if disabled_msg:
            add_log("instagram_reply", "Inbox poll failed: Direct Messaging access is disabled in Instagram settings.")
            data = load_db()
            data["last_inbox_poll"] = now_iso()
            data["last_inbox_poll_result"] = {
                "ok": False,
                "message": "Direct Messaging access is disabled in your Instagram app settings.",
                "disabled_access": True,
                "diagnostics": diagnostics,
            }
            save_db(data)
            return {
                "ok": False,
                "message": "Direct Messaging access is disabled. Go to Instagram App > Settings > Messages and story replies > Message controls > Connected Tools > Allow Access to Messages and toggle it ON.",
                "disabled_access": True,
                "diagnostics": diagnostics,
            }
        add_log("instagram_reply", "Inbox poll failed: no Meta conversation endpoint returned usable data.")
        return {"ok": False, "message": "No Meta conversation endpoint returned usable data.", "diagnostics": diagnostics}
    if "error" in result:
        add_log("instagram_reply", f"Inbox poll rejected: {result['error'].get('message', 'Meta error')}")
        return {"ok": False, "stage": "conversations", "response": result, "diagnostics": diagnostics}
    data = load_db()
    seen_ids = {str(row.get("message_id", "")) for row in data.get("incoming_messages", []) if row.get("message_id")}
    handled = []
    for conversation in result.get("data", []):
        messages = (conversation.get("messages") or {}).get("data", [])
        for msg in reversed(messages):
            message_id = str(msg.get("id") or "")
            text = msg.get("message") or ""
            sender = msg.get("from") or {}
            sender_id = sender.get("id")
            if not text or not sender_id or not message_id or message_id in seen_ids:
                continue
            if is_own_instagram_message(msg, token_status):
                continue
            row = handle_incoming_instagram_message(sender_id, text, "dm_poll", msg, message_id=message_id)
            handled.append(row)
            seen_ids.add(message_id)
    conversation_count = len(result.get("data", []))
    data = load_db()
    data["last_inbox_poll"] = now_iso()
    data["last_inbox_poll_result"] = {
        "ok": True,
        "handled": len(handled),
        "conversations": conversation_count,
        "needs_meta_setup": conversation_count == 0,
        "guidance": inbox_empty_guidance() if conversation_count == 0 else [],
        "diagnostics": diagnostics,
    }
    save_db(data)
    return {
        "ok": True,
        "handled": len(handled),
        "conversations": conversation_count,
        "endpoint": url,
        "needs_meta_setup": conversation_count == 0,
        "guidance": inbox_empty_guidance() if conversation_count == 0 else [],
        "diagnostics": diagnostics,
    }


def extract_event_text(obj):
    if not isinstance(obj, dict):
        return ""
    message = obj.get("message")
    if isinstance(message, dict):
        for key in ["text", "message", "body"]:
            if isinstance(message.get(key), str) and message.get(key).strip():
                return message[key].strip()
        reaction = message.get("reaction")
        if isinstance(reaction, dict):
            emoji = reaction.get("emoji") or reaction.get("reaction")
            return f"Reacted to story/message: {emoji}" if emoji else "Reacted to story/message"
        attachments = message.get("attachments")
        if attachments:
            return "Shared or reacted to an Instagram story/media"
    if isinstance(message, str) and message.strip():
        return message.strip()
    reaction = obj.get("reaction")
    if isinstance(reaction, dict):
        emoji = reaction.get("emoji") or reaction.get("reaction")
        return f"Reacted to story/message: {emoji}" if emoji else "Reacted to story/message"
    comment = obj.get("comment")
    if isinstance(comment, dict):
        for key in ["text", "message", "body"]:
            if isinstance(comment.get(key), str) and comment.get(key).strip():
                return comment[key].strip()
    for key in ["text", "comment_text", "body", "caption"]:
        if isinstance(obj.get(key), str) and obj.get(key).strip():
            return obj[key].strip()
    return ""


def extract_sender_id(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ["sender", "from", "user"]:
        value = obj.get(key)
        if isinstance(value, dict) and value.get("id"):
            return str(value["id"])
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ["sender_id", "from_id", "user_id", "ig_sid"]:
        if obj.get(key):
            return str(obj[key])
    message = obj.get("message")
    if isinstance(message, dict):
        nested = extract_sender_id(message)
        if nested:
            return nested
    comment = obj.get("comment")
    if isinstance(comment, dict):
        nested = extract_sender_id(comment)
        if nested:
            return nested
    return ""


def extract_message_id(obj):
    if not isinstance(obj, dict):
        return ""
    message = obj.get("message")
    if isinstance(message, dict):
        for key in ["mid", "id", "message_id"]:
            if message.get(key):
                return str(message[key])
    comment = obj.get("comment")
    if isinstance(comment, dict):
        for key in ["id", "comment_id", "mid"]:
            if comment.get(key):
                return str(comment[key])
    for key in ["mid", "id", "message_id", "comment_id"]:
        if obj.get(key):
            return str(obj[key])
    return ""


def extract_comment_target_id(obj):
    if not isinstance(obj, dict):
        return ""
    comment = obj.get("comment")
    if isinstance(comment, dict):
        for key in ["id", "comment_id"]:
            if comment.get(key):
                return str(comment[key])
    for key in ["comment_id", "id"]:
        if obj.get(key):
            return str(obj[key])
    return ""


def nested_instagram_objects(obj):
    if not isinstance(obj, dict):
        return []
    found = []
    for key in ["messages", "comments", "replies"]:
        value = obj.get(key)
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, list):
                found.extend(item for item in data if isinstance(item, dict))
        elif isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict))
    return found


def extract_instagram_webhook_items(payload):
    items = []
    seen = set()

    def add(source, obj):
        text = extract_event_text(obj)
        sender_id = extract_sender_id(obj)
        message_id = extract_message_id(obj)
        reply_target_id = extract_comment_target_id(obj) if source.startswith("comment") else sender_id
        if not text or not (sender_id or reply_target_id):
            return
        key = (source, message_id, sender_id, reply_target_id, text)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "source": source,
            "sender_id": sender_id,
            "text": text,
            "message_id": message_id,
            "reply_target_id": reply_target_id,
            "raw": obj,
        })

    for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
        for event in entry.get("messaging", []) or []:
            if not isinstance(event, dict):
                continue
            message = event.get("message", {})
            if isinstance(message, dict) and message.get("is_echo"):
                continue
            add("dm_webhook", event)
            for nested in nested_instagram_objects(event):
                add("dm_webhook", nested)
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            field = str(change.get("field", "")).lower()
            source = "comment_webhook" if "comment" in field else "dm_webhook"
            add(source, value)
            for nested in nested_instagram_objects(value):
                add(source, nested)
    return items


def summarize_webhook_payload(payload, handled):
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    entry_count = len(entries) if isinstance(entries, list) else 0
    messaging_count = 0
    change_count = 0
    fields = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        messaging = entry.get("messaging", []) or []
        changes = entry.get("changes", []) or []
        if isinstance(messaging, list):
            messaging_count += len(messaging)
        if isinstance(changes, list):
            change_count += len(changes)
            for change in changes:
                if isinstance(change, dict) and change.get("field"):
                    fields.append(str(change.get("field")))
    raw = redact_private_text(json.dumps(payload, ensure_ascii=False, default=str))
    return {
        "time": now_iso(),
        "object": payload.get("object") if isinstance(payload, dict) else "",
        "entry_count": entry_count,
        "messaging_count": messaging_count,
        "change_count": change_count,
        "fields": sorted(set(fields)),
        "handled": handled,
        "raw_preview": raw[:2400],
    }


def remember_webhook_event(payload, handled):
    data = load_db()
    item = summarize_webhook_payload(payload, handled)
    data["last_webhook_event"] = item
    data.setdefault("webhook_events", []).insert(0, item)
    data["webhook_events"] = data["webhook_events"][:25]
    save_db(data)
    if handled:
        add_log("instagram_webhook", f"Webhook received and handled {handled} item(s).")
    else:
        add_log("instagram_webhook", "Webhook received, but no supported message/comment text was found.")
    return item


def webhook_reply_status(data):
    last = data.get("last_webhook_event") or {}
    if not last:
        return {
            "status": "no_webhook_event_yet",
            "message": "No Instagram webhook event has reached this backend yet.",
        }
    if int(last.get("handled") or 0) <= 0:
        return {
            "status": "webhook_received_no_replyable_text",
            "message": "Meta reached the webhook, but the payload had no supported DM/comment text for auto reply.",
            "last_event": last,
        }
    return {
        "status": "webhook_received",
        "message": f"Last webhook handled {last.get('handled')} replyable item(s).",
        "last_event": last,
    }


def instagram_token_diagnostic():
    token = META_ACCESS_TOKEN.strip()
    if not token:
        return {"connected": False, "stage": "env", "message": "META_ACCESS_TOKEN missing in backend/.env"}
    if "*" in token or "xxxxxxxx" in token.lower() or token.startswith("PASTE") or len(token) < 80:
        return {
            "connected": False,
            "stage": "token_parse_check",
            "message": "Token is masked, placeholder, app secret, or incomplete. Use Generate token > Copy button, then paste full token in .env.",
            "token_length": len(token),
        }
    if not INSTAGRAM_USER_ID:
        return {"connected": False, "stage": "env", "message": "INSTAGRAM_USER_ID missing in backend/.env"}
    token_hint = "instagram_login_like" if token.startswith("IG") else "facebook_graph_like"
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{INSTAGRAM_USER_ID}"
    try:
        response = requests.get(url, params={"fields": "id,username,account_type,media_count", "access_token": token}, timeout=25)
        result = response.json()
    except RequestException as exc:
        message = str(exc)
        if "WinError 10013" in message:
            message = "Windows blocked this backend process from opening an HTTPS connection to graph.facebook.com. Restart the backend from your normal Windows user/session and allow Python through firewall/security prompts."
        elif "Max retries exceeded" in message:
            message = "Could not reach graph.facebook.com. Check internet access, firewall, VPN/proxy, or security software for this Python process."
        return {"connected": False, "stage": "network", "message": message}
    except ValueError:
        return {"connected": False, "stage": "network", "message": f"Meta returned a non-JSON response with HTTP {response.status_code}."}
    if "error" in result:
        error = result["error"]
        if error.get("code") == 190:
            instagram_login = instagram_login_token_diagnostic(token)
            if instagram_login.get("connected"):
                return instagram_login
            instagram_error = instagram_login.get("meta_error") or {"message": instagram_login.get("message"), "stage": instagram_login.get("stage")}
            if token_hint == "instagram_login_like" and instagram_error.get("code") == 200:
                return {
                    "connected": False,
                    "stage": "instagram_api_blocked",
                    "token_hint": token_hint,
                    "message": "Saved token looks like an Instagram Login token, but Meta says API access is blocked for this app/account/token.",
                    "facebook_graph_error": {
                        "message": error.get("message"),
                        "type": error.get("type"),
                        "code": error.get("code"),
                        "fbtrace_id": error.get("fbtrace_id"),
                    },
                    "instagram_login_error": instagram_error,
                    "fix": "Create a fresh token from the Instagram Business use case after required permissions/tester role/app access are active, then replace META_ACCESS_TOKEN in backend/.env and restart backend.",
                    "fix_steps": [
                        "Use Meta app's Instagram Business setup token generator, not an app secret/API key/masked token.",
                        "Make sure the Instagram account is added as Instagram Tester/Admin and the invite is accepted while app is unpublished.",
                        "Make sure instagram_business_basic and instagram_business_manage_messages are approved/active for DM replies.",
                        "Copy the full generated access token again into backend/.env as META_ACCESS_TOKEN, then restart backend.",
                    ],
                }
            return {
                "connected": False,
                "stage": "token_invalid",
                "token_hint": token_hint,
                "message": "Meta rejected the saved META_ACCESS_TOKEN. It is expired, revoked, copied incorrectly, or not an Instagram Business Login/Page token.",
                "facebook_graph_error": {
                    "message": error.get("message"),
                    "type": error.get("type"),
                    "code": error.get("code"),
                    "fbtrace_id": error.get("fbtrace_id"),
                },
                "instagram_login_error": instagram_error,
                "fix": "Generate a fresh token from the Instagram Business use-case page, then replace META_ACCESS_TOKEN in backend/.env and restart backend.",
            }
        return {"connected": False, "stage": "instagram_user_check", "error": error}
    result["connected"] = True
    result["stage"] = "success"
    result["token_type"] = "facebook_page"
    return result


def instagram_login_token_diagnostic(token):
    url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/me"
    try:
        response = requests.get(url, params={"fields": "id,username,account_type,media_count", "access_token": token}, timeout=25)
        result = response.json()
    except RequestException as exc:
        message = str(exc)
        if "WinError 10013" in message:
            message = "Windows blocked this backend process from opening an HTTPS connection to graph.instagram.com."
        elif "Max retries exceeded" in message:
            message = "Could not reach graph.instagram.com. Check internet access, firewall, VPN/proxy, or security software."
        return {"connected": False, "stage": "network", "message": message}
    except ValueError:
        return {"connected": False, "stage": "network", "message": f"Meta returned a non-JSON Instagram response with HTTP {response.status_code}."}
    if "error" in result:
        error = result["error"]
        stage = "instagram_api_blocked" if error.get("code") == 200 and "blocked" in str(error.get("message", "")).lower() else "token_invalid"
        return {
            "connected": False,
            "stage": stage,
            "message": "Meta rejected META_ACCESS_TOKEN for the Instagram Login path too.",
            "meta_error": {
                "message": error.get("message"),
                "type": error.get("type"),
                "code": error.get("code"),
                "fbtrace_id": error.get("fbtrace_id"),
            },
        }
    result["connected"] = True
    result["stage"] = "success"
    result["token_type"] = "instagram_login"
    return result


def publish_to_instagram(draft):
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"published": False, "message": "Instagram token not connected.", "token_status": token_status}
    media_url = draft.get("public_media_url", "")
    if not media_url.startswith("https://"):
        return {"published": False, "message": "Instagram API needs a public HTTPS media URL. The app generated a local original visual, but local PC files cannot be posted directly."}
    if draft.get("type") == "reel" and not media_url.lower().endswith((".mp4", ".mov")):
        return {"published": False, "message": "Reels require a public HTTPS video URL. The app can create reel scripts/covers, but cannot publish an image as a reel."}
    payload = {
        "caption": f"{draft.get('caption','')}\n\n{' '.join(draft.get('hashtags', []))}",
        "access_token": META_ACCESS_TOKEN,
    }
    if draft.get("type") == "reel":
        payload.update({"media_type": "REELS", "video_url": media_url})
    elif draft.get("type") == "story":
        # Instagram stories require media_type=STORIES and either image_url/video_url depending on media.
        if media_url.lower().endswith((".mp4", ".mov")):
            payload.update({"media_type": "STORIES", "video_url": media_url})
        else:
            payload.update({"media_type": "STORIES", "image_url": media_url})
    else:
        payload.update({"image_url": media_url})
    graph_host = "graph.instagram.com" if token_status.get("token_type") == "instagram_login" else "graph.facebook.com"
    ig_user_id = token_status.get("id") or INSTAGRAM_USER_ID

    max_attempts = 3
    last_create = {}
    last_ready = {}
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            add_log("publish_retry", f"Retrying container creation & wait (Attempt {attempt}/{max_attempts}) for Draft #{draft.get('id')}...")
            time.sleep(15)
        create = requests.post(f"https://{graph_host}/{META_GRAPH_VERSION}/{ig_user_id}/media", data=payload, timeout=40).json()
        if "id" not in create:
            return {"published": False, "stage": "create_container", "response": create}
        
        last_create = create
        ready = wait_for_media_container(graph_host, create["id"], draft.get("type"))
        last_ready = ready
        if ready.get("ready"):
            break
        else:
            add_log("publish_retry", f"Attempt {attempt}/{max_attempts} container status check failed: {ready}")

    if not last_ready.get("ready"):
        return {"published": False, "stage": "container_processing", "response": last_create, "container_status": last_ready}

    published = requests.post(
        f"https://{graph_host}/{META_GRAPH_VERSION}/{ig_user_id}/media_publish",
        data={"creation_id": last_create["id"], "access_token": META_ACCESS_TOKEN},
        timeout=40,
    ).json()
    return {"published": "id" in published, "stage": "media_publish", "response": published}


def wait_for_media_container(graph_host, creation_id, content_type):
    if content_type not in ["reel", "story"]:
        time.sleep(2)
        return {"ready": True, "status_code": "SKIPPED_FAST_IMAGE_WAIT"}
    last = {}
    for _ in range(8):
        time.sleep(15)
        try:
            last = requests.get(
                f"https://{graph_host}/{META_GRAPH_VERSION}/{creation_id}",
                params={"fields": "status_code,status", "access_token": META_ACCESS_TOKEN},
                timeout=25,
            ).json()
        except RequestException as exc:
            last = {"error": f"{type(exc).__name__}"}
        status_code = str(last.get("status_code", "")).upper()
        if status_code in ["FINISHED", "PUBLISHED"]:
            return {"ready": True, **last}
        if status_code in ["ERROR", "EXPIRED"]:
            return {"ready": False, **last}
    return {"ready": False, **last}


def recommend_best():
    data = load_db()
    if not data["analytics"]:
        return {"best_topic": "cute", "best_time": "Evening", "reason": "No analytics added yet. Default safe recommendation."}
    best = sorted(data["analytics"], key=lambda item: item.get("score", 0), reverse=True)[0]
    return {"best_topic": best.get("category"), "best_time": best.get("slot"), "reason": "Based on highest saved engagement score."}


def generate_draft_media(draft, data):
    draft["id"] = next_id(data)
    draft["status"] = "generating"
    draft["created_at"] = now_iso()
    data["drafts"].insert(0, draft)
    remember_line_memory(data, draft)
    save_db(data)
    
    visual_name = create_original_reel_video(draft) if draft["type"] in ["reel", "story"] else create_original_visual(draft)
    if not visual_name:
        visual_name = create_original_visual(draft)
        
    data = load_db()
    current = next((item for item in data["drafts"] if item.get("id") == draft["id"]), draft)
    current["local_watermarked_file"] = visual_name
    current["local_media_url"] = f"/api/media/output/{visual_name}"
    
    if visual_name:
        if PUBLIC_MEDIA_BASE_URL and draft["type"] in ["post", "story", "reel"]:
            current["public_media_url"] = f"{PUBLIC_MEDIA_BASE_URL}/{visual_name}"
        elif cloudinary_ready() and draft["type"] in ["post", "story", "reel"]:
            host_draft_media(current)
        current["status"] = "ready_to_publish"
    else:
        current["status"] = "generation_failed"
        
    current["generated_at"] = now_iso()
    save_db(data)
    return current


def continuous_post_cycle():
    """Generate and publish a reel + story pair together without limits, using the exact same content/video."""
    add_log("continuous_post", "Starting continuous post cycle (Reel + Story)")
    try:
        data = load_db()
        categories = ["comedy_line", "love_line", "motivation_line", "interesting_line", "general_knowledge", "story_line"]
        category = random.choice(categories)
        add_log("continuous_post", f"Selected category: {category}")
        
        # Bypass approval screen temporarily for these drafts
        original_approval = data.get("settings", {}).get("approval_screen", False)
        data["settings"]["approval_screen"] = False
        save_db(data)
        
        # Build Reel draft first
        reel_draft = build_draft("Continuous", "reel", category, scheduled_time=now_iso())
        
        # Restore original settings
        data = load_db()
        data["settings"]["approval_screen"] = original_approval
        save_db(data)
        
        # Generate Reel media
        add_log("continuous_post", f"Generating Reel for category {category}...")
        generated_reel = generate_draft_media(reel_draft, load_db())
        if not generated_reel or generated_reel.get("status") != "ready_to_publish":
            add_log("continuous_post", "Reel generation failed, aborting cycle.")
            return
            
        apply_public_media_url(generated_reel)
        if not generated_reel.get("public_media_url", "").startswith("https://") and cloudinary_ready():
            host_draft_media(generated_reel)
            
        # Now create Story draft from the exact same Reel details
        story_draft = {
            "slot": "Continuous",
            "type": "story",
            "category": generated_reel["category"],
            "topic": generated_reel["topic"],
            "caption": generated_reel["caption"],
            "hashtags": generated_reel["hashtags"],
            "script": f"Continuous STORY PLAN (Identical to Reel #{generated_reel['id']})",
            "safe": generated_reel["safe"],
            "safety_reasons": generated_reel["safety_reasons"],
            "scheduled_time": generated_reel["scheduled_time"],
            "status": "ready_to_publish",
            "local_media_url": generated_reel["local_media_url"],
            "local_watermarked_file": generated_reel["local_watermarked_file"],
            "public_media_url": generated_reel.get("public_media_url", ""),
            "template": generated_reel.get("template", ""),
            "source_mode": generated_reel.get("source_mode", ""),
            "audio_policy": generated_reel.get("audio_policy", ""),
            "generation_source": generated_reel.get("generation_source", ""),
            "id": next_id(load_db()),
            "created_at": now_iso(),
            "generated_at": now_iso()
        }
        
        # Save Story in DB
        data = load_db()
        data["drafts"].insert(0, story_draft)
        remember_line_memory(data, story_draft) # Save line memory
        save_db(data)
        
        # Publish Reel
        add_log("continuous_post", "Publishing Reel...")
        result_reel = publish_to_instagram(generated_reel)
        generated_reel["publish_result"] = result_reel
        generated_reel["status"] = status_after_publish_result(result_reel)
        data = load_db()
        record_publish_timing(data, result_reel)
        if result_reel.get("published"):
            after_successful_publish(generated_reel, result_reel)
            add_log("continuous_post", "Reel published successfully!")
        else:
            add_log("continuous_post", f"Reel publish failed: {result_reel.get('message') or result_reel.get('response')}")
            if is_meta_publish_limit(result_reel):
                data = load_db()
                data["publish_paused_until"] = tomorrow_retry_time()
                save_db(data)
                
        # Save updated reel draft in DB
        data = load_db()
        for idx, d in enumerate(data.get("drafts", [])):
            if d.get("id") == generated_reel.get("id"):
                data["drafts"][idx] = generated_reel
                break
        save_db(data)
        
        # Publish Story (using the exact same media details)
        add_log("continuous_post", "Waiting 30 seconds before publishing Story to prevent concurrent download congestion...")
        time.sleep(30)
        add_log("continuous_post", "Publishing Story...")
        result_story = publish_to_instagram(story_draft)
        story_draft["publish_result"] = result_story
        story_draft["status"] = status_after_publish_result(result_story)
        data = load_db()
        record_publish_timing(data, result_story)
        if result_story.get("published"):
            after_successful_publish(story_draft, result_story)
            add_log("continuous_post", "Story published successfully!")
        else:
            add_log("continuous_post", f"Story publish failed: {result_story.get('message') or result_story.get('response')}")
            if is_meta_publish_limit(result_story):
                data = load_db()
                data["publish_paused_until"] = tomorrow_retry_time()
                save_db(data)
                
        # Save updated story draft in DB
        data = load_db()
        for idx, d in enumerate(data.get("drafts", [])):
            if d.get("id") == story_draft.get("id"):
                data["drafts"][idx] = story_draft
                break
        save_db(data)
        
    except Exception as exc:
        add_log("continuous_post", f"Continuous cycle failed: {type(exc).__name__}")


def recover_continuous_drafts():
    """Find any continuous drafts that are ready to publish and attempt to publish them."""
    data = load_db()
    if pause_until_active(data):
        return
        
    # Get all continuous drafts
    continuous_drafts = [d for d in data.get("drafts", []) if d.get("slot") == "Continuous"]
    if not continuous_drafts:
        return
        
    # Group drafts by local_watermarked_file to identify pairs
    by_file = {}
    for d in continuous_drafts:
        f = d.get("local_watermarked_file")
        if f:
            by_file.setdefault(f, []).append(d)
            
    # Sort files by the max ID of the drafts in that group descending
    sorted_files = sorted(by_file.keys(), key=lambda f: max(d.get("id", 0) for d in by_file[f]), reverse=True)
    
    # Loop through each pair (newest first)
    for latest_file in sorted_files:
        pair = by_file[latest_file]
        ready_drafts = [d for d in pair if d.get("status") == "ready_to_publish"]
        if not ready_drafts:
            continue
            
        add_log("continuous_post", f"Recovery: Found {len(ready_drafts)} ready draft(s) for media {latest_file}. Attempting to publish...")
        
        # Sort so that Reel is published before Story if both are ready
        ready_drafts.sort(key=lambda d: 0 if d.get("type") == "reel" else 1)
        
        for idx, draft in enumerate(ready_drafts):
            if idx > 0:
                add_log("continuous_post", "Waiting 30 seconds before publishing counterpart to prevent concurrent download congestion...")
                time.sleep(30)
                
            add_log("continuous_post", f"Recovery: Publishing {draft.get('type')} (Draft #{draft.get('id')})...")
            result = publish_to_instagram(draft)
            draft["publish_result"] = result
            draft["status"] = status_after_publish_result(result)
            
            # Save after each publish
            data = load_db()
            record_publish_timing(data, result)
            if result.get("published"):
                after_successful_publish(draft, result)
                add_log("continuous_post", f"Recovery: {draft.get('type').capitalize()} published successfully!")
            else:
                add_log("continuous_post", f"Recovery: {draft.get('type').capitalize()} publish failed: {result.get('message') or result.get('response')}")
                if is_meta_publish_limit(result):
                    data = load_db()
                    data["publish_paused_until"] = tomorrow_retry_time()
                    save_db(data)
                    
            # Save updated draft in DB
            data = load_db()
            for i, d in enumerate(data.get("drafts", [])):
                if d.get("id") == draft.get("id"):
                    data["drafts"][i] = draft
                    break
            save_db(data)
            
            if not result.get("published"):
                # If one fails, don't proceed with the next one in this pair to avoid rate limit spamming
                break
                
        # We only recover one pair per scheduler loop run to prevent spamming
        break


LOCK_FILE = Path("scheduler.lock")

def is_pid_running(pid):
    try:
        import subprocess
        res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5)
        return str(pid) in res.stdout
    except Exception:
        return False

def acquire_scheduler_lock():
    try:
        if LOCK_FILE.exists():
            try:
                content = LOCK_FILE.read_text(encoding="utf-8").strip()
                if content.isdigit():
                    pid = int(content)
                    if pid == os.getpid():
                        return True
                    if is_pid_running(pid):
                        return False
            except Exception:
                pass
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                return False
        
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return False

def release_scheduler_lock():
    try:
        if LOCK_FILE.exists():
            content = LOCK_FILE.read_text(encoding="utf-8").strip()
            if content.isdigit() and int(content) == os.getpid():
                LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def scheduler_loop():
    while True:
        if not acquire_scheduler_lock():
            time.sleep(15)
            continue
        locked = OPERATION_LOCK.acquire(blocking=False)
        if not locked:
            time.sleep(60)
            continue
        try:
            data = load_db()
            changed = False
            
            if CONTINUOUS_POST_MODE:
                # 1. Recover rate limits if any
                if recover_publish_rate_limits(data):
                    changed = True
                
                # Run recovery for continuous drafts
                recover_continuous_drafts()
                data = load_db()

                
                # 2. Check if we should generate and post a new reel + story
                if pause_until_active(data):
                    should_post = False
                else:
                    last_time_str = data.get("last_continuous_post_time", "")
                    should_post = False
                    if not last_time_str:
                        should_post = True
                    else:
                        try:
                            last_time = datetime.fromisoformat(last_time_str)
                            if datetime.now() >= last_time + timedelta(minutes=CONTINUOUS_INTERVAL_MINUTES):
                                should_post = True
                        except Exception:
                            should_post = True
                
                if should_post:
                    # Run the continuous cycle
                    continuous_post_cycle()
                    data = load_db()
                    data["last_continuous_post_time"] = datetime.now().isoformat()
                    changed = True
                
                # 3. Handle Auto-Reply polling (always poll inbox in continuous mode, throttled to 10 min)
                if INBOX_POLL_ENABLED:
                    last_poll_str = data.get("last_inbox_poll", "")
                    should_poll = False
                    if not last_poll_str:
                        should_poll = True
                    else:
                        try:
                            last_poll = datetime.fromisoformat(last_poll_str)
                            if datetime.now() >= last_poll + timedelta(minutes=10):
                                should_poll = True
                        except Exception:
                            should_poll = True
                    if should_poll:
                        poll_instagram_inbox()
                        retry_failed_replies()
                    
            else:
                # Original Scheduler Logic
                if recover_publish_rate_limits(data):
                    changed = True
                if data["settings"].get("safe_autopilot"):
                    before_settings = json.dumps(data.get("settings", {}), sort_keys=True)
                    before_waiting = sum(1 for item in data.get("drafts", []) if item.get("status") == "waiting_approval")
                    restore_safe_autopilot_settings(data)
                    if before_settings != json.dumps(data.get("settings", {}), sort_keys=True) or before_waiting:
                        changed = True
                today = datetime.now().date().isoformat()
                daily_limit_reached = published_today_count(data) >= MAX_CONTENT_PER_DAY
                if data["settings"].get("safe_autopilot") and data["settings"].get("daily_random_scheduler") and not daily_limit_reached:
                    if data.get("last_auto_generation_date") != today:
                        generate_daily_plan_isolated()
                        data = load_db()
                        data["last_auto_generation_date"] = today
                        changed = True
                if retire_legacy_ready_drafts(data):
                    changed = True
                if trim_active_line_queue(data):
                    changed = True
                for draft in sorted(data["drafts"], key=publish_candidate_sort_key):
                    if (
                        is_line_draft(draft)
                        and draft.get("type") in ["post", "story", "reel"]
                        and (not draft.get("public_media_url") or public_media_url_is_stale(draft.get("public_media_url", "")))
                    ):
                        if apply_public_media_url(draft):
                            changed = True
                        elif cloudinary_ready():
                            host = host_draft_media(draft)
                            changed = changed or bool(host.get("uploaded"))
                    status_ok = draft.get("status") in PUBLISHABLE_STATUSES and is_line_draft(draft)
                    if not status_ok:
                        continue
                    try:
                        due = datetime.fromisoformat(draft.get("scheduled_time")) <= datetime.now()
                    except Exception:
                        due = False
                    if daily_limit_reached:
                        draft["status"] = "paused_daily_limit_reached"
                        draft["archive_reason"] = f"Daily safe limit reached: {MAX_CONTENT_PER_DAY} posts."
                        changed = True
                        continue
                    if due and data["settings"].get("safe_autopilot") and data["settings"].get("daily_random_scheduler"):
                        if AUTO_PUBLISH_ENABLED and not pause_until_active(data) and not publish_interval_active(data):
                            result = publish_to_instagram(draft)
                            draft["publish_result"] = result
                            draft["status"] = status_after_publish_result(result)
                            record_publish_timing(data, result)
                            if result.get("published"):
                                after_successful_publish(draft, result)
                            if is_meta_publish_limit(result):
                                data["publish_paused_until"] = tomorrow_retry_time()
                            changed = True
                            break
                        else:
                            draft["status"] = "ready_to_publish"
                        changed = True
                if INBOX_POLL_ENABLED and data["settings"].get("safe_autopilot") and data["settings"].get("auto_reply_dm"):
                    last_poll_str = data.get("last_inbox_poll", "")
                    should_poll = False
                    if not last_poll_str:
                        should_poll = True
                    else:
                        try:
                            last_poll = datetime.fromisoformat(last_poll_str)
                            if datetime.now() >= last_poll + timedelta(minutes=10):
                                should_poll = True
                        except Exception:
                            should_poll = True
                    if should_poll:
                        poll_instagram_inbox()
                        retry_failed_replies()
            
            if changed:
                save_db(data)
        except Exception:
            pass
        finally:
            OPERATION_LOCK.release()
        time.sleep(60)


class LoginIn(BaseModel):
    username: str
    password: str


class SettingIn(BaseModel):
    key: str
    value: bool


class DraftId(BaseModel):
    draft_id: int


class PublicUrlIn(BaseModel):
    draft_id: int
    public_media_url: str


class ReplyIn(BaseModel):
    message: str
    style: str = "friendly"


class SendReplyIn(BaseModel):
    recipient_id: str
    message: str


class GrowthTrackIn(BaseModel):
    username: str


class GrowthBackIn(BaseModel):
    account_id: int
    followed_back: bool


class AnalyticsIn(BaseModel):
    category: str
    content_type: str
    slot: str
    likes: int = 0
    comments: int = 0
    saves: int = 0
    shares: int = 0


class ProfilePlanIn(BaseModel):
    period: str = "1_month"


@app.get("/")
def root():
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/app"><a href="/app">Open Anime Nova</a>')


@app.head("/")
def root_head():
    return PlainTextResponse("")


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": APP_NAME,
        "webhook_url": current_webhook_url(),
        "auto_reply_enabled": AUTO_REPLY_SEND_ENABLED,
        "auto_publish_enabled": AUTO_PUBLISH_ENABLED,
        "public_media_base_url_set": bool(PUBLIC_MEDIA_BASE_URL),
    }


@app.head("/health")
def health_head():
    return PlainTextResponse("")


@app.head("/app")
def app_html_head():
    return PlainTextResponse("")


@app.get("/app")
def app_html():
    path = Path("app.html")
    if not path.exists():
        raise HTTPException(404, "app.html missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/privacy")
@app.get("/privacy.html")
def privacy_html():
    path = Path("privacy.html")
    if not path.exists():
        raise HTTPException(404, "privacy.html missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/data-deletion")
@app.get("/data-deletion.html")
def data_deletion_html():
    path = Path("data-deletion.html")
    if not path.exists():
        raise HTTPException(404, "data-deletion.html missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.post("/api/login")
def login(data: LoginIn, request: Request):
    if not ADMIN_USERNAME or not ADMIN_PASSWORD or not JWT_SECRET:
        raise HTTPException(503, "ADMIN_USERNAME, ADMIN_PASSWORD, and JWT_SECRET must be set in .env")
    client_key = check_login_rate_limit(request)
    username = data.username.strip()
    password = data.password.strip()
    if not hmac.compare_digest(username, ADMIN_USERNAME) or not hmac.compare_digest(password, ADMIN_PASSWORD):
        record_login_failure(client_key)
        raise HTTPException(401, "Wrong username or password")
    clear_login_failure(client_key)
    token = jwt.encode({"sub": username, "exp": datetime.utcnow() + timedelta(days=7)}, JWT_SECRET, algorithm="HS256")
    add_log("security", "Dashboard login success.")
    return {"token": token, "app": APP_NAME}


@app.get("/api/state")
def state(user=Depends(auth)):
    data = load_db()
    data["brand"] = BRAND
    data["auto_publish_enabled"] = AUTO_PUBLISH_ENABLED
    data["auto_reply_send_enabled"] = AUTO_REPLY_SEND_ENABLED
    data["inbox_poll_enabled"] = INBOX_POLL_ENABLED
    data["nova_assistant"] = {
        "enabled": True,
        "engine": "nova_ai_reply_brain" if NOVA_REPLY_AI_ENABLED else "nova_local_reply_brain",
        "mode": "safe anime brand replies",
        "provider_order": NOVA_REPLY_PROVIDER_ORDER,
        "selective": True,
    }
    data["cloudinary_ready"] = cloudinary_ready()
    data["webhook_verify_token_set"] = bool(WEBHOOK_VERIFY_TOKEN)
    data["webhook_verify_token"] = WEBHOOK_VERIFY_TOKEN
    data["blocked_keys"] = BLOCKED_KEYS
    data["recommendation"] = recommend_best()
    data["token_present"] = bool(META_ACCESS_TOKEN and "*" not in META_ACCESS_TOKEN)
    data["instagram_connection"] = data.get("last_instagram_test") or {
        "connected": None,
        "stage": "not_checked",
        "message": "Click Check Instagram ID to test the saved Meta token.",
    }
    data["public_media_base_url_set"] = bool(PUBLIC_MEDIA_BASE_URL)
    data["webhook_url"] = current_webhook_url()
    data["public_webhook_status"] = cached_public_webhook_status(timeout=3) if PUBLIC_MEDIA_BASE_URL else {
        "ok": False,
        "message": "PUBLIC_MEDIA_BASE_URL missing in backend/.env.",
    }
    data["reply_status"] = webhook_reply_status(data)
    data["safe_source_status"] = safe_source_status()
    return data


@app.get("/api/diagnostics/startup")
def startup_diagnostic(user=Depends(auth)):
    return load_db().get("startup_scan", {})


@app.post("/api/diagnostics/rescan")
def startup_rescan(user=Depends(auth)):
    return run_startup_self_scan()


@app.post("/api/settings")
def update_setting(item: SettingIn, user=Depends(auth)):
    data = load_db()
    if item.key not in ALL_SETTINGS:
        raise HTTPException(404, "Unknown setting")
    if item.key in BLOCKED:
        data["settings"][item.key] = False
        save_db(data)
        add_log("blocked", f"{item.key} was requested but blocked for safety.")
        return {"key": item.key, "value": False, "blocked": True, "message": "Blocked for safety."}
    data["settings"][item.key] = bool(item.value)
    save_db(data)
    add_log("settings", f"{item.key} changed to {bool(item.value)}")
    return {"key": item.key, "value": bool(item.value)}


@app.post("/api/settings/enable-safe-autopilot")
def enable_safe_autopilot(user=Depends(auth)):
    data = load_db()
    restore_safe_autopilot_settings(data)
    save_db(data)
    add_log("settings", "Safe autopilot restored: safe tools ON, approval screen OFF, risky tools locked.")
    return {"settings": data["settings"], "message": "Safe autopilot restored"}


@app.post("/api/autopilot/run-now")
@app.post("/api/autopilot/run-niow")
def autopilot_run_now(user=Depends(auth)):
    with OPERATION_LOCK:
        data = load_db()
        recover_publish_rate_limits(data)
        data = prepare_publish_queue(data)
        restore_safe_autopilot_settings(data)
        if pause_until_active(data):
            save_db(data)
            return {
                "ok": True,
                "published": 0,
                "publish_paused": True,
                "publish_paused_until": data.get("publish_paused_until"),
                "retry_after_seconds": seconds_until_publish_resume(data),
                "message": "Meta publishing limit is active. Autopilot will not retry until the pause time.",
                "diagnostic": publish_diagnostic(),
                "results": [],
            }
        if publish_interval_active(data):
            save_db(data)
            return {
                "ok": True,
                "published": 0,
                "publish_pacing_active": True,
                "next_publish_attempt_at": next_publish_attempt_at(data),
                "message": "Safe publish pacing is active. The next queued item will be attempted later.",
                "results": [],
            }
        already_published = published_today_count(data)
        remaining = max(0, MAX_CONTENT_PER_DAY - already_published)
        if remaining <= 0:
            save_db(data)
            return {
                "ok": True,
                "published": 0,
                "daily_limit_reached": True,
                "message": f"Daily safe limit reached: {already_published}/{MAX_CONTENT_PER_DAY} items already published today.",
                "results": [],
            }
        ready = sorted(
            [d for d in data["drafts"] if d.get("status") in ["ready_to_publish", "publish_failed"] and is_line_draft(d)],
            key=publish_candidate_sort_key,
        )
        if not ready:
            save_db(data)
            generate_daily_plan_isolated()
            data = load_db()
            restore_safe_autopilot_settings(data)
            ready = sorted(
                [d for d in data["drafts"] if d.get("status") in ["ready_to_publish", "publish_failed"] and is_line_draft(d)],
                key=publish_candidate_sort_key,
            )
        results = []
        for draft in ready[:1]:
            if draft.get("status") == "published":
                continue
            apply_public_media_url(draft)
            if not draft.get("public_media_url", "").startswith("https://") and cloudinary_ready():
                host_draft_media(draft)
            result = publish_to_instagram(draft)
            draft["publish_result"] = result
            draft["status"] = status_after_publish_result(result)
            record_publish_timing(data, result)
            if result.get("published"):
                after_successful_publish(draft, result)
            results.append({"id": draft.get("id"), "type": draft.get("type"), "status": draft["status"], "result": result})
            if is_meta_publish_limit(result):
                data["publish_paused_until"] = tomorrow_retry_time()
                break
        save_db(data)
    add_log("autopilot", f"Autopilot run finished. Published {sum(1 for r in results if r['status'] == 'published')} of {len(results)}.")
    return {"ok": True, "results": results, "published": sum(1 for r in results if r["status"] == "published")}


@app.get("/api/publish/diagnostic")
def api_publish_diagnostic(user=Depends(auth)):
    return publish_diagnostic()


@app.post("/api/autopilot/prepare-queue")
def api_prepare_queue(user=Depends(auth)):
    with OPERATION_LOCK:
        data = load_db()
        restore_safe_autopilot_settings(data)
        data = prepare_publish_queue(data)
        save_db(data)
    add_log("autopilot", "Prepared safe publish queue and refreshed public media URLs.")
    return publish_diagnostic()


@app.post("/api/content/generate-daily")
def api_daily(user=Depends(auth)):
    with OPERATION_LOCK:
        return {"drafts": generate_daily_plan_isolated()}


@app.post("/api/content/approve")
def approve(item: DraftId, user=Depends(auth)):
    data = load_db()
    for draft in data["drafts"]:
        if draft["id"] == item.draft_id:
            draft["status"] = "approved"
            save_db(data)
            add_log("approval", f"Draft #{item.draft_id} approved.")
            return draft
    raise HTTPException(404, "Draft not found")


@app.post("/api/content/public-url")
def save_public_url(item: PublicUrlIn, user=Depends(auth)):
    data = load_db()
    for draft in data["drafts"]:
        if draft["id"] == item.draft_id:
            draft["public_media_url"] = item.public_media_url.strip()
            save_db(data)
            add_log("media", f"Public media URL saved for draft #{item.draft_id}.")
            return draft
    raise HTTPException(404, "Draft not found")


@app.post("/api/content/host-media")
def host_media(item: DraftId, user=Depends(auth)):
    data = load_db()
    for draft in data["drafts"]:
        if draft["id"] == item.draft_id:
            apply_public_media_url(draft)
            result = host_draft_media(draft)
            save_db(data)
            add_log("media", f"Host media draft #{item.draft_id}: {result.get('message', result.get('secure_url', 'done'))}")
            return {"draft": draft, "result": result}
    raise HTTPException(404, "Draft not found")


@app.post("/api/content/publish-now")
def publish_now(item: DraftId, user=Depends(auth)):
    data = load_db()
    for draft in data["drafts"]:
        if draft["id"] == item.draft_id:
            if not CONTINUOUS_POST_MODE and published_today_count(data) >= MAX_CONTENT_PER_DAY and draft.get("status") != "published":
                raise HTTPException(429, f"Daily safe limit reached: {MAX_CONTENT_PER_DAY} posts already published today.")
            if data["settings"].get("approval_screen") and draft.get("status") != "approved":
                raise HTTPException(400, "Approval required first")
            apply_public_media_url(draft)
            result = publish_to_instagram(draft)
            draft["publish_result"] = result
            draft["status"] = status_after_publish_result(result)
            record_publish_timing(data, result)
            if result.get("published"):
                after_successful_publish(draft, result)
            if is_meta_publish_limit(result):
                data["publish_paused_until"] = tomorrow_retry_time()
            save_db(data)
            add_log("instagram", f"Publish Now draft #{item.draft_id}: {result.get('stage', result.get('message'))}")
            return result
    raise HTTPException(404, "Draft not found")


@app.post("/api/reply")
def reply(item: ReplyIn, user=Depends(auth)):
    result = make_reply(item.message, item.style)
    data = load_db()
    result_row = {"id": next_id(data), "time": now_iso(), "message": item.message, "style": item.style, **result}
    data["reply_tests"].insert(0, result_row)
    data["reply_tests"] = data["reply_tests"][:100]
    save_db(data)
    add_log("reply", "Safe reply generated or held.")
    return result


@app.get("/webhook/instagram")
def instagram_webhook_verify(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if not mode and not token and not challenge:
        return HTMLResponse(
            "<!doctype html><html><head><meta charset='utf-8'><title>Instagram Webhook Ready</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;background:#071827;color:#f7f7ff;padding:32px}"
            "code{display:block;background:#111827;border:1px solid #334155;border-radius:10px;padding:12px;margin:8px 0}"
            ".ok{color:#86efac}</style></head><body>"
            "<h1 class='ok'>Instagram webhook is live</h1>"
            "<p>This URL is only the callback endpoint. Direct browser open will not verify Meta by itself.</p>"
            "<p>In Meta Developer Webhooks, use:</p>"
            "<p>Callback URL</p><code>"
            + str(request.url).split("?")[0]
            + "</code><p>Verify token is shown inside the secure admin dashboard.</p>"
            "<p>Meta will send hub.mode, hub.verify_token, and hub.challenge automatically when you click Verify.</p>"
            "</body></html>"
        )
    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        return PlainTextResponse(str(challenge or ""))
    raise HTTPException(403, "Webhook verify token mismatch")


@app.head("/webhook/instagram")
def instagram_webhook_head():
    return PlainTextResponse("")


@app.post("/webhook/instagram")
async def instagram_webhook_receive(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    handled = []
    for item in extract_instagram_webhook_items(payload):
        handled.append(handle_incoming_instagram_message(
            item.get("sender_id"),
            item.get("text"),
            item.get("source"),
            item.get("raw"),
            reply_target_id=item.get("reply_target_id"),
            message_id=item.get("message_id"),
        ))
    event = remember_webhook_event(payload, len(handled))
    return {"ok": True, "handled": len(handled), "event": {k: v for k, v in event.items() if k != "raw_preview"}}


@app.post("/api/reply/send")
def send_reply(item: SendReplyIn, user=Depends(auth)):
    result = make_reply(item.message, "anime fan style")
    if result.get("hold"):
        return {"sent": False, "held": True, "reasons": result.get("reasons", [])}
    sent = send_instagram_message(item.recipient_id, result["reply"])
    data = load_db()
    row = {
        "id": next_id(data),
        "time": now_iso(),
        "source": "manual_send",
        "sender_id": item.recipient_id,
        "message": item.message,
        "reply": result["reply"],
        "hold": False,
        "reasons": [],
        "send_result": sent,
        "status": "sent" if sent.get("sent") else "send_failed",
    }
    data["incoming_messages"].insert(0, row)
    data["incoming_messages"] = data["incoming_messages"][:200]
    save_db(data)
    add_log("instagram_reply", f"Manual reply send to {item.recipient_id}: {row['status']}")
    return row


@app.post("/api/reply/check-inbox")
def check_inbox(user=Depends(auth)):
    result = poll_instagram_inbox()
    retry = retry_failed_replies()
    add_log("instagram_reply", f"Manual inbox check: {result.get('handled', 0)} handled.")
    result["retry_failed_replies"] = retry
    return result


@app.post("/api/reply/retry-failed")
def retry_replies(user=Depends(auth)):
    return retry_failed_replies()


@app.get("/api/instagram/messaging-diagnostic")
def messaging_diagnostic(user=Depends(auth)):
    token_status = instagram_token_diagnostic()
    inbox = poll_instagram_inbox()
    data = load_db()
    webhook_url = current_webhook_url()
    public_webhook = check_public_webhook()
    subscription = instagram_webhook_subscription_status()
    can_auto_reply = bool(token_status.get("connected")) and bool(inbox.get("conversations", 0) or inbox.get("handled", 0))
    webhook_status = webhook_reply_status(data)
    if webhook_status.get("status") == "webhook_received":
        can_auto_reply = True
    external_blocker = ""
    if inbox.get("disabled_access"):
        external_blocker = (
            "Instagram Direct Messaging Access is DISABLED. "
            "To fix this, open your Instagram phone app, go to Settings & Activity -> "
            "Messages and story replies -> Message controls -> Connected Tools, "
            "and toggle 'Allow access to messages' to ON."
        )
    elif token_status.get("connected") and public_webhook.get("ok") and subscription.get("ok") and not can_auto_reply:
        external_blocker = (
            "Token, public webhook, and messages/comments subscription are OK, but Meta still returned zero conversations "
            "and has not delivered any webhook POST. This usually means the sender is not allowed while the Meta app is unpublished, "
            "the app is not Live/App-Review-approved for messaging, or Instagram message access for connected tools is off."
        )
    return {
        "ok": True,
        "instagram_connected": bool(token_status.get("connected")),
        "username": token_status.get("username"),
        "account_type": token_status.get("account_type"),
        "token_type": token_status.get("token_type"),
        "reply_brain_ready": True,
        "auto_reply_send_enabled": AUTO_REPLY_SEND_ENABLED,
        "webhook_url": webhook_url,
        "verify_token": WEBHOOK_VERIFY_TOKEN,
        "public_webhook": public_webhook,
        "subscription": subscription,
        "required_permissions": ["instagram_business_basic", "instagram_business_manage_messages", "instagram_business_manage_comments"],
        "settings": {
            "safe_autopilot": data.get("settings", {}).get("safe_autopilot"),
            "auto_reply_dm": data.get("settings", {}).get("auto_reply_dm"),
            "auto_reply_comments": data.get("settings", {}).get("auto_reply_comments"),
            "auto_chat_reply": data.get("settings", {}).get("auto_chat_reply"),
        },
        "webhook_status": webhook_status,
        "conversation_count": inbox.get("conversations", 0),
        "handled": inbox.get("handled", 0),
        "can_auto_reply_now": can_auto_reply,
        "blocker": "" if can_auto_reply else (external_blocker or "Meta is returning zero Instagram conversations and no replyable webhook event has reached this app, so there is no recipient IGSID to reply to."),
        "inbox_result": inbox,
        "next_actions": (
            [
                "CRITICAL: Turn ON 'Allow access to messages' in your Instagram phone app settings (Settings & Activity -> Messages and story replies -> Message controls -> Connected Tools -> Allow Access to Messages -> Toggle ON).",
                "After enabling, send a fresh new DM from another Instagram account to test."
            ]
            if inbox.get("disabled_access")
            else (inbox_empty_guidance() if not can_auto_reply else ["Auto reply is ready. Send a new message and check Incoming Replies."])
        ),
    }


@app.get("/api/instagram/webhook-diagnostic")
def webhook_diagnostic(user=Depends(auth)):
    data = load_db()
    inbox = poll_instagram_inbox()
    return {
        "ok": True,
        "token": instagram_token_diagnostic(),
        "public_webhook": check_public_webhook(),
        "subscription": instagram_webhook_subscription_status(),
        "webhook_status": webhook_reply_status(data),
        "conversation_count": inbox.get("conversations", 0),
        "handled": inbox.get("handled", 0),
        "manual_send_note": "Instagram Direct thread URL number is not a valid API recipient id. The API needs sender IGSID from webhook/conversation.",
        "next_actions": inbox_empty_guidance() if inbox.get("conversations", 0) == 0 and inbox.get("handled", 0) == 0 else [],
    }


@app.post("/api/instagram/repair-webhook-subscription")
def repair_webhook_subscription(user=Depends(auth)):
    result = subscribe_instagram_webhook_fields()
    add_log("instagram_webhook", "Webhook subscription repair: " + ("ok" if result.get("ok") else "failed"))
    return result


@app.get("/api/growth/suggestions")
def growth_suggestions(user=Depends(auth)):
    names = ["anime_daily_vibes", "kawaii_scene_hub", "shonen_power_zone", "romantic_anime_quotes", "otaku_meme_corner", "action_arc_world"]
    data = load_db()
    data["suggestions"] = [
        {"id": next_id(data), "username": n, "reason": random.choice(["Similar anime theme", "Good engagement topic match", "Safe niche account idea"]), "created_at": now_iso()}
        for n in names
    ]
    save_db(data)
    add_log("growth", "Growth suggestions refreshed.")
    return {"suggestions": data["suggestions"]}


@app.post("/api/growth/track")
def growth_track(item: GrowthTrackIn, user=Depends(auth)):
    username = item.username.strip().lstrip("@")
    if not username:
        raise HTTPException(400, "Username required")
    data = load_db()
    row = {"id": next_id(data), "username": username, "followed_on": now_iso(), "followed_back": False, "status": "tracking_manual", "notes": "Manual safe reminder only. No auto follow/unfollow."}
    data["growth"].insert(0, row)
    save_db(data)
    add_log("growth", f"Added @{username} to 7-day followback tracker.")
    return row


@app.post("/api/growth/followback")
def growth_followback(item: GrowthBackIn, user=Depends(auth)):
    data = load_db()
    for row in data["growth"]:
        if row["id"] == item.account_id:
            row["followed_back"] = item.followed_back
            row["status"] = "keep" if item.followed_back else "still_tracking"
            save_db(data)
            add_log("growth", f"Followback status updated for @{row['username']}.")
            return row
    raise HTTPException(404, "Account not found")


@app.get("/api/growth/7-day-report")
def seven_day_report(user=Depends(auth)):
    data = load_db()
    report = []
    for row in data["growth"]:
        try:
            days = (datetime.now() - datetime.fromisoformat(row["followed_on"])).days
        except Exception:
            days = 0
        if days >= 7 and not row.get("followed_back"):
            report.append({**row, "days": days, "reminder": "7 din se follow-back nahi diya. Manual review."})
    return {"report": report}


@app.post("/api/analytics/add")
def analytics_add(item: AnalyticsIn, user=Depends(auth)):
    data = load_db()
    score = item.likes + item.comments * 3 + item.saves * 4 + item.shares * 5
    row = item.dict()
    row.update({"id": next_id(data), "score": score, "created_at": now_iso()})
    data["analytics"].insert(0, row)
    save_db(data)
    add_log("analytics", f"Analytics saved: {item.category}/{item.content_type}, score {score}.")
    return row


@app.get("/api/analytics/recommendation")
def analytics_recommendation(user=Depends(auth)):
    return recommend_best()


@app.post("/api/highlight/generate")
def highlight_generate(user=Depends(auth)):
    data = load_db()
    category = random.choice(["Funny Anime", "Cute Anime", "Action Anime", "Romantic Anime", "Adventure Anime", "Quotes"])
    row = {
        "id": next_id(data),
        "created_at": now_iso(),
        "category": category,
        "title": category,
        "cover_text": category.replace(" Anime", ""),
        "story_ideas": [random.choice(TOPICS[random.choice(list(TOPICS.keys()))]) for _ in range(5)],
    }
    data["highlights"].insert(0, row)
    save_db(data)
    add_log("highlight", f"Highlight plan created: {category}.")
    return row


@app.post("/api/profile/plan")
def profile_plan(item: ProfilePlanIn, user=Depends(auth)):
    data = load_db()
    row = {
        "id": next_id(data),
        "created_at": now_iso(),
        "period": item.period,
        "bio": f"Daily fresh lines\nFunny • Love • Motivation • Thoughts\nNo 18+ content. Watermark: {BRAND}",
        "profile_picture_note": "Use your own uploaded/owned image only.",
        "highlight_cover_style": random.choice(["neon anime", "cute pastel", "dark action", "romantic soft glow"]),
        "theme_color": random.choice(["Anime neon", "Dark purple", "Blue cyber", "Pink kawaii"]),
        "intro_text": f"Welcome to {BRAND} — daily safe anime content.",
        "next_change": (datetime.now() + timedelta(days=random.choice([10, 20, 30, 60, 150, 365]))).date().isoformat(),
    }
    data["profiles"].insert(0, row)
    save_db(data)
    add_log("profile", f"Profile rotation plan created for {item.period}.")
    return row


@app.post("/api/watermark")
def watermark(file: UploadFile = File(...), user=Depends(auth)):
    ext = Path(file.filename).suffix.lower() or ".png"
    if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
        raise HTTPException(400, "Upload image only: png, jpg, jpeg, webp")
    in_path = MEDIA_INPUT_DIR / f"input_{int(time.time())}{ext}"
    with in_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    img = Image.open(in_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = max(24, img.width // 28)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    text = BRAND
    box = draw.textbbox((0, 0), text, font=font)
    w = box[2] - box[0]
    h = box[3] - box[1]
    x = (img.width - w) // 2
    y = img.height - h - max(25, img.height // 20)
    pad = 14
    draw.rounded_rectangle((x - pad, y - pad, x + w + pad, y + h + pad), radius=18, fill=(0, 0, 0, 130))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))
    out = Image.alpha_composite(img, overlay).convert("RGB")
    out_name = f"watermarked_{int(time.time())}.jpg"
    out_path = MEDIA_OUTPUT_DIR / out_name
    out.save(out_path, quality=92)
    add_log("watermark", f"Watermark added: {out_name}")
    return {"file": out_name, "download_url": f"/api/media/output/{out_name}"}


@app.api_route("/api/media/output/{filename}", methods=["GET", "HEAD"])
def output_file(filename: str):
    if filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid file name")
    base = MEDIA_OUTPUT_DIR.resolve()
    path = (MEDIA_OUTPUT_DIR / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(400, "Invalid file path")
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@app.get("/api/instagram/test")
def instagram_test(user=Depends(auth)):
    result = instagram_token_diagnostic()
    data = load_db()
    data["last_instagram_test"] = {
        "time": now_iso(),
        "connected": bool(result.get("connected")),
        "stage": result.get("stage"),
        "username": result.get("username"),
        "account_type": result.get("account_type"),
        "token_type": result.get("token_type"),
        "message": result.get("message") or ("Connected" if result.get("connected") else "Not connected"),
        "fix": result.get("fix", ""),
        "fix_steps": result.get("fix_steps", []),
    }
    save_db(data)
    add_log("instagram", f"Token test: {result.get('stage')}.")
    return result


@app.on_event("startup")
def startup_tasks():
    global SCHEDULER_STARTED
    run_startup_self_scan()
    if not SCHEDULER_STARTED:
        threading.Thread(target=scheduler_loop, daemon=True).start()
        SCHEDULER_STARTED = True
