import os
import hmac
import json
import random
import re
import shutil
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import jwt
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Anime Nova Instagram Manager")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
BRAND = os.getenv("BRAND_WATERMARK", "Anim.funzon")
AUTO_PUBLISH_ENABLED = os.getenv("AUTO_PUBLISH_ENABLED", "false").lower() == "true"
MIN_CONTENT_PER_DAY = int(os.getenv("MIN_CONTENT_PER_DAY", "3"))
MAX_CONTENT_PER_DAY = int(os.getenv("MAX_CONTENT_PER_DAY", "5"))
MEDIA_INPUT_DIR = Path(os.getenv("MEDIA_INPUT_DIR", "./media/input"))
MEDIA_OUTPUT_DIR = Path(os.getenv("MEDIA_OUTPUT_DIR", "./media/output"))
MEDIA_INPUT_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB = Path("anime_nova_data.json")

app = FastAPI(title=APP_NAME)
security = HTTPBearer(auto_error=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
}


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


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
        "next_id": 1,
    }


def load_db():
    if not DB.exists():
        save_db(default_db())
    try:
        data = json.loads(DB.read_text(encoding="utf-8"))
    except Exception:
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
    DB.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def next_id(data):
    value = int(data.get("next_id", 1))
    data["next_id"] = value + 1
    return value


def add_log(event, message):
    data = load_db()
    data["logs"].insert(0, {"id": next_id(data), "event": event, "time": now_iso(), "message": str(message)})
    data["logs"] = data["logs"][:500]
    save_db(data)


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


def contains_any(text, words):
    lower = (text or "").lower()
    return any(w in lower for w in words)


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
    }.get(category, [])
    return base + extra


def random_schedule(slot):
    hour = {
        "Morning": random.randint(8, 10),
        "Afternoon": random.randint(13, 15),
        "Evening": random.randint(18, 20),
        "Night": random.randint(21, 23),
        "Extra": random.choice([11, 16, 19, 22]),
    }[slot]
    return datetime.now().replace(hour=hour, minute=random.choice([5, 12, 21, 35, 47, 55]), second=0, microsecond=0).isoformat()


def build_draft(slot, content_type, category):
    topic = random.choice(TOPICS[category])
    caption = (
        f"{topic}\n\n"
        f"Clean anime vibes only ✨\n"
        f"Follow {BRAND} for daily anime posts, stories and reels."
    )
    script = (
        f"{slot} {content_type.upper()} PLAN\n"
        f"Topic: {topic}\n"
        f"Visual direction: use original/owned anime-style image or video only.\n"
        f"Watermark: {BRAND} bottom center.\n"
        f"Caption: ready. Hashtags: ready. Safety: checked.\n"
        f"Music note: use only Instagram-approved audio inside Instagram, not downloaded copyrighted songs."
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
        "scheduled_time": random_schedule(slot),
        "status": "ready_to_publish" if not load_db()["settings"].get("approval_screen") else "waiting_approval",
        "public_media_url": "",
        "local_watermarked_file": "",
        "publish_result": None,
    }


def generate_daily_plan():
    data = load_db()
    plan = [
        ("Morning", "story", "cute"),
        ("Afternoon", "post", random.choice(["funny", "quotes", "memes"])),
        ("Evening", "reel", random.choice(["action", "adventure", "motivational"])),
        ("Night", "story", random.choice(["romantic", "emotional"])),
    ]
    if MAX_CONTENT_PER_DAY >= 5:
        plan.append(("Extra", random.choice(["post", "story", "reel"]), random.choice(list(TOPICS.keys()))))
    count = max(MIN_CONTENT_PER_DAY, min(MAX_CONTENT_PER_DAY, len(plan)))
    chosen = plan[:count]
    made = []
    for item in chosen:
        draft = build_draft(*item)
        draft["id"] = next_id(data)
        data["drafts"].insert(0, draft)
        made.append(draft)
    save_db(data)
    add_log("content", f"Generated {len(made)} fresh anime drafts.")
    return made


def make_reply(message, style="friendly"):
    safe = safety_check(message)
    if not safe["safe"]:
        return {"hold": True, "reply": "", "reasons": safe["reasons"]}
    lower = (message or "").lower()
    if contains_any(lower, PRIVATE_WORDS):
        answer = f"Ye {BRAND} ka official anime page hai. Personal details private rakhe jate hain ✨"
    elif "action" in lower:
        answer = "Action anime vibe 🔥 Next reel power-up, rival battle ya sword-clash style pe ho sakti hai."
    elif "romantic" in lower:
        answer = "Romantic anime vibe soft, clean and wholesome rahega 🌸"
    elif "cute" in lower:
        answer = "Cute anime mood unlocked ✨ Kawaii style story/post ready kar sakte hain."
    elif "hi" in lower or "hello" in lower:
        answer = f"Hey! Welcome to {BRAND} ✨ Funny, cute, action ya romantic anime me kya pasand hai?"
    else:
        answer = f"Thanks for messaging {BRAND}! Daily safe anime vibes ke liye follow karo ✨"
    if style == "funny":
        answer += " 😄 Anime energy high rakho!"
    if style == "professional":
        answer = answer.replace("✨", "").strip()
    if style == "anime fan style":
        answer += " Dattebayo vibes!"
    return {"hold": False, "reply": answer, "reasons": []}


def instagram_token_diagnostic():
    token = META_ACCESS_TOKEN.strip()
    if not INSTAGRAM_USER_ID:
        return {"connected": False, "stage": "env", "message": "INSTAGRAM_USER_ID missing in backend/.env"}
    if not token:
        return {"connected": False, "stage": "env", "message": "META_ACCESS_TOKEN missing in backend/.env"}
    if "*" in token or "xxxxxxxx" in token.lower() or token.startswith("PASTE") or len(token) < 80:
        return {
            "connected": False,
            "stage": "token_parse_check",
            "message": "Token is masked, placeholder, app secret, or incomplete. Use Generate token > Copy button, then paste full token in .env.",
            "token_length": len(token),
        }
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{INSTAGRAM_USER_ID}"
    try:
        response = requests.get(url, params={"fields": "id,username,account_type,media_count", "access_token": token}, timeout=25)
        result = response.json()
    except Exception as exc:
        return {"connected": False, "stage": "network", "message": str(exc)}
    if "error" in result:
        return {"connected": False, "stage": "instagram_user_check", "error": result["error"]}
    result["connected"] = True
    result["stage"] = "success"
    return result


def publish_to_instagram(draft):
    token_status = instagram_token_diagnostic()
    if not token_status.get("connected"):
        return {"published": False, "message": "Instagram token not connected.", "token_status": token_status}
    media_url = draft.get("public_media_url", "")
    if not media_url.startswith("https://"):
        return {"published": False, "message": "Instagram API needs public HTTPS media URL. Local PC file cannot be posted directly."}
    payload = {
        "caption": f"{draft.get('caption','')}\n\n{' '.join(draft.get('hashtags', []))}",
        "access_token": META_ACCESS_TOKEN,
    }
    if draft.get("type") == "reel":
        payload.update({"media_type": "REELS", "video_url": media_url})
    elif draft.get("type") == "story":
        # Instagram stories require media_type=STORIES and either image_url/video_url depending on media.
        payload.update({"media_type": "STORIES", "image_url": media_url})
    else:
        payload.update({"image_url": media_url})
    create = requests.post(f"https://graph.facebook.com/{META_GRAPH_VERSION}/{INSTAGRAM_USER_ID}/media", data=payload, timeout=40).json()
    if "id" not in create:
        return {"published": False, "stage": "create_container", "response": create}
    time.sleep(2)
    published = requests.post(
        f"https://graph.facebook.com/{META_GRAPH_VERSION}/{INSTAGRAM_USER_ID}/media_publish",
        data={"creation_id": create["id"], "access_token": META_ACCESS_TOKEN},
        timeout=40,
    ).json()
    return {"published": "id" in published, "stage": "media_publish", "response": published}


def recommend_best():
    data = load_db()
    if not data["analytics"]:
        return {"best_topic": "cute", "best_time": "Evening", "reason": "No analytics added yet. Default safe recommendation."}
    best = sorted(data["analytics"], key=lambda item: item.get("score", 0), reverse=True)[0]
    return {"best_topic": best.get("category"), "best_time": best.get("slot"), "reason": "Based on highest saved engagement score."}


def scheduler_loop():
    while True:
        try:
            data = load_db()
            changed = False
            for draft in data["drafts"]:
                status_ok = draft.get("status") in ["approved", "ready_to_publish"]
                if not status_ok:
                    continue
                try:
                    due = datetime.fromisoformat(draft.get("scheduled_time")) <= datetime.now()
                except Exception:
                    due = False
                if due and data["settings"].get("safe_autopilot") and data["settings"].get("daily_random_scheduler"):
                    if AUTO_PUBLISH_ENABLED:
                        result = publish_to_instagram(draft)
                        draft["publish_result"] = result
                        draft["status"] = "published" if result.get("published") else "publish_failed"
                    else:
                        draft["status"] = "ready_to_publish"
                    changed = True
            if changed:
                save_db(data)
        except Exception:
            pass
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


@app.get("/app")
def app_html():
    path = Path("app.html")
    if not path.exists():
        raise HTTPException(404, "app.html missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.post("/api/login")
def login(data: LoginIn):
    if not ADMIN_USERNAME or not ADMIN_PASSWORD or not JWT_SECRET:
        raise HTTPException(503, "ADMIN_USERNAME, ADMIN_PASSWORD, and JWT_SECRET must be set in .env")
    if not hmac.compare_digest(data.username, ADMIN_USERNAME) or not hmac.compare_digest(data.password, ADMIN_PASSWORD):
        raise HTTPException(401, "Wrong username or password")
    token = jwt.encode({"sub": data.username, "exp": datetime.utcnow() + timedelta(days=7)}, JWT_SECRET, algorithm="HS256")
    add_log("security", "Dashboard login success.")
    return {"token": token, "app": APP_NAME}


@app.get("/api/state")
def state(user=Depends(auth)):
    data = load_db()
    data["brand"] = BRAND
    data["auto_publish_enabled"] = AUTO_PUBLISH_ENABLED
    data["blocked_keys"] = BLOCKED_KEYS
    data["recommendation"] = recommend_best()
    data["token_present"] = bool(META_ACCESS_TOKEN and "*" not in META_ACCESS_TOKEN)
    return data


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


@app.post("/api/content/generate-daily")
def api_daily(user=Depends(auth)):
    return {"drafts": generate_daily_plan()}


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


@app.post("/api/content/publish-now")
def publish_now(item: DraftId, user=Depends(auth)):
    data = load_db()
    for draft in data["drafts"]:
        if draft["id"] == item.draft_id:
            if data["settings"].get("approval_screen") and draft.get("status") != "approved":
                raise HTTPException(400, "Approval required first")
            result = publish_to_instagram(draft)
            draft["publish_result"] = result
            draft["status"] = "published" if result.get("published") else "publish_failed"
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
        "bio": f"Daily clean anime vibes ✨\nFunny • Cute • Action • Quotes\nNo 18+ content. Watermark: {BRAND}",
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


@app.get("/api/media/output/{filename}")
def output_file(filename: str):
    path = MEDIA_OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@app.get("/api/instagram/test")
def instagram_test(user=Depends(auth)):
    result = instagram_token_diagnostic()
    add_log("instagram", f"Token test: {result.get('stage')}.")
    return result


threading.Thread(target=scheduler_loop, daemon=True).start()
