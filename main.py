from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging

# ---------- Import from moviebox-api v2 ----------
try:
    from moviebox_api.v2 import Client
    MOVIEBOX_AVAILABLE = True
    print("✅ moviebox_api.v2 imported successfully")
except ImportError as e:
    print(f"❌ Could not import moviebox_api.v2: {e}")
    MOVIEBOX_AVAILABLE = False

app = FastAPI(title="MovieBox API", description="Backend for XiON Android app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------
class MediaItem(BaseModel):
    id: str
    title: str
    year: Optional[str] = None
    poster: Optional[str] = None
    type: str

class StreamResponse(BaseModel):
    url: str
    quality: Optional[str] = None
    subtitle_url: Optional[str] = None

# ---------- Global Client ----------
client = None

async def get_client():
    global client
    if client is None and MOVIEBOX_AVAILABLE:
        client = Client()  # This is the recommended way
    return client

# ---------- Endpoints ----------
@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE
    }

@app.get("/search", response_model=List[MediaItem])
async def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not available")
    
    cl = await get_client()
    try:
        results = await cl.search(query, page=1, per_page=20)
        
        items = []
        for item in results.get("items", []):
            items.append(MediaItem(
                id=str(item.get("subjectId")),
                title=item.get("title"),
                year=item.get("releaseDate"),
                poster=item.get("cover"),
                type="series" if item.get("subjectType") == 2 else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Search failed: {str(e)}")

@app.get("/info/{media_id}")
async def get_info(media_id: str):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not available")
    
    cl = await get_client()
    try:
        details = await cl.get_details(media_id)
        return details
    except Exception as e:
        raise HTTPException(404, f"Item not found: {str(e)}")

@app.get("/stream/{media_id}")
async def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None
):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not available")
    
    cl = await get_client()
    try:
        if season and episode:
            stream = await cl.get_series_stream(media_id, season, episode)
        else:
            stream = await cl.get_movie_stream(media_id)
        
        return StreamResponse(
            url=stream.get("url"),
            quality=stream.get("quality"),
            subtitle_url=stream.get("subtitle_url")
        )
    except Exception as e:
        raise HTTPException(500, f"Stream error: {str(e)}")
