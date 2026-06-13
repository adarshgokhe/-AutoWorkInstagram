import os
import sys
import json
import shutil
import re
from pathlib import Path

# Add backend directory to path
BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(BASE, "backend")
sys.path.insert(0, BACKEND)

import main

def regenerate_all():
    print("=== REGENERATING UNPUBLISHED DRAFTS ===", flush=True)
    
    # Reload environment to ensure branding is funzone_creator
    main.load_dotenv()
    main.BRAND = os.getenv("BRAND_WATERMARK", "funzone_creator")
    print(f"Branding active: {main.BRAND}", flush=True)
    
    # Path to database
    db_path = os.path.join(BACKEND, "anime_nova_data.json")
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}", flush=True)
        return
        
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    drafts = data.get("drafts", [])
    print(f"Total drafts in database: {len(drafts)}", flush=True)
    
    # Filter drafts that are not published yet
    target_statuses = ["ready_to_publish", "publish_failed", "waiting_approval", "paused_daily_limit_reached"]
    
    regenerated_count = 0
    
    for draft in drafts:
        status = draft.get("status")
        dtype = draft.get("type")
        
        if status in target_statuses and dtype in ["reel", "story"]:
            d_id = draft.get("id")
            topic = draft.get("topic")
            old_file = draft.get("local_watermarked_file")
            
            print(f"\nRegenerating Draft #{d_id} ({dtype}) - Status: {status}", flush=True)
            print(f"Topic: {topic}", flush=True)
            
            # Delete old file if it exists to clean up space
            if old_file:
                old_file_path = os.path.join(BACKEND, "media", "output", old_file)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                        print(f"Deleted old file: {old_file}", flush=True)
                    except Exception as e:
                        print(f"Warning: Could not delete old file: {e}", flush=True)
            
            # Re-render the media using the updated layout and brand settings
            try:
                # Force update the caption to match the brand name just in case
                caption = draft.get("caption", "")
                
                # Replace watermark handle in caption
                caption = re_replace_brand(caption, main.BRAND)
                draft["caption"] = caption
                
                # Re-generate hashtags just in case
                draft["hashtags"] = main.hashtags(draft.get("category", "quotes"))
                
                # Regenerate video file
                print("Rendering video using FFMPEG...", flush=True)
                visual_name = main.create_original_reel_video(draft)
                if visual_name:
                    draft["local_watermarked_file"] = visual_name
                    draft["local_media_url"] = f"/api/media/output/{visual_name}"
                    if main.PUBLIC_MEDIA_BASE_URL:
                        draft["public_media_url"] = f"{main.PUBLIC_MEDIA_BASE_URL}/{visual_name}"
                    
                    # If it was failed or paused, make it ready to publish
                    if draft["status"] in ["publish_failed", "paused_daily_limit_reached"]:
                        draft["status"] = "ready_to_publish"
                        
                    draft["generated_at"] = main.now_iso()
                    regenerated_count += 1
                    print(f"SUCCESS: Rendered new file => {visual_name}", flush=True)
                    
                    # Save incremental progress to database immediately
                    with open(db_path, "w", encoding="utf-8") as f_save:
                        json.dump(data, f_save, indent=2, ensure_ascii=False)
                    print("Saved database update to disk.", flush=True)
                else:
                    print("ERROR: Render returned empty file name.", flush=True)
            except Exception as exc:
                print(f"ERROR: Generation failed: {exc}", flush=True)
                
    print(f"\nFinished regeneration run. Regenerated {regenerated_count} drafts.", flush=True)

def re_replace_brand(text, new_brand):
    # Replace any mention of old brands in caption with the new one
    text = re.sub(r'(?i)anim\.efunzone?', new_brand, text)
    text = re.sub(r'(?i)anim\.funzon', new_brand, text)
    return text

if __name__ == "__main__":
    regenerate_all()
