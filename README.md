# AnimeNova_FULL_WORKING_SAFE

This is the upgraded same project package. It runs from the backend only:

```powershell
cd C:\Users\coool\AnimeNova_FULL_WORKING_SAFE\backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

```text
http://127.0.0.1:8000/app
```

Before first run, create a private `.env` from `.env.example` and set your own login:

```text
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=use_a_strong_private_password
JWT_SECRET=use_a_long_random_private_secret
```

## Important token rule

Do not paste masked token, app secret, dots, or stars.
Use Meta Developers > Generate token > Copy button > paste full token:

```env
META_ACCESS_TOKEN=FULL_VALID_TOKEN_HERE
```

Then restart backend.

## What works in this safe version

- Nova-style ON/OFF dashboard
- Safe Autopilot settings
- Daily 3-5 anime post/story/reel drafts
- Caption + hashtags generator
- Reel script generator
- Story/post planner
- Auto highlight planner
- Profile/bio rotation planner
- Natural safe DM/comment/chat reply simulator
- Personal info protection
- NSFW/spam/scam/abuse/link blocking
- Anim.funzon watermark tool for uploaded images
- Growth assistant suggestions
- 7-day manual followback tracker
- Engagement analytics and best posting time recommendation
- Official Instagram token tester
- Official Instagram API publish helper with public HTTPS media URL
- Activity logs

## Safe limits

The app will not do fake likes, mass comments, detection bypass, auto follow/unfollow, scrape copyrighted anime reels, or post adult/18+ content. Those buttons are visible but blocked.

Instagram real publishing needs:

1. Business/Creator Instagram account
2. Connected Facebook Page
3. Correct Facebook Graph/Instagram permissions
4. Valid access token
5. Public HTTPS image/video URL

Local files cannot be posted directly by Instagram API until they are hosted as a public HTTPS URL.
