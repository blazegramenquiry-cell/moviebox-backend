from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ---------- Correct Imports from moviebox-api v2 ----------
MOVIEBOX_AVAILABLE = False

try:
    from moviebox_api.v2.requests import Session
    from moviebox_api.v2.core import Search, MovieDetails, TVSeriesDetails, ItemDetails
    from moviebox_api.v2.download import DownloadableSingleFilesDetail, DownloadableTVSeriesFilesDetail
    MOVIEBOX_AVAILABLE = True
    print("✅ moviebox_api.v2 imported successfully")
except ImportError as e:
    print(f"❌ Import failed: {e}")

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

# ---------- Global Session ----------
session = None

async def get_session():
    global session
    if session is None and MOVIEBOX_AVAILABLE:
        session = Session()
        await session.ensure_cookies_are_assigned()
    return session

# ---------- Routes ----------
@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE
    }

@app.get("/search")
async def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    try:
        search_obj = Search(session=sess, query=query, subject_type=0, page=1, per_page=20)
        results = await search_obj.get_content_model()
        
        items = []
        for item in results.items:
            d = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            items.append(MediaItem(
                id=str(d.get("subjectId")),
                title=d.get("title"),
                year=d.get("releaseDate"),
                poster=d.get("cover"),
                type="series" if d.get("subjectType") == 2 else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Search error: {str(e)}")

@app.get("/info/{media_id}")
async def get_info(media_id: str):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    try:
        # Try as movie first, fallback to series
        try:
            details = await MovieDetails(url_or_item=media_id, session=sess).get_content_model()
            return details.subject.model_dump()
        except:
            details = await TVSeriesDetails(url_or_item=media_id, session=sess).get_content_model()
            return details.subject.model_dump()
    except Exception as e:
        raise HTTPException(404, f"Item not found: {str(e)}")

@app.get("/stream/{media_id}")
async def get_stream(media_id: str, season: Optional[int] = None, episode: Optional[int] = None):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    try:
        if season is not None and episode is not None:
            dl = DownloadableTVSeriesFilesDetail(session=sess, item=media_id)
            files = await dl.get_content_model(season=season, episode=episode)
        else:
            dl = DownloadableSingleFilesDetail(session=sess, item=media_id)
            files = await dl.get_content_model()
        
        best = files.best_media_file
        return StreamResponse(
            url=str(best.url),
            quality=f"{best.resolution}P",
            subtitle_url=str(files.english_subtitle_file.url) if files.english_subtitle_file else None
        )
    except Exception as e:
        raise HTTPException(500, f"Stream error: {str(e)}")
