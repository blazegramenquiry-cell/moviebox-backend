from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging

# ---------- Import from moviebox-api v1 ----------
MOVIEBOX_AVAILABLE = False
session = None

try:
    from moviebox_api.v1.requests import Session
    from moviebox_api.v1.core import Search, Trending, MovieDetails, TVSeriesDetails
    from moviebox_api.v1.download import (
        DownloadableMovieFilesDetail,
        DownloadableTVSeriesFilesDetail,
    )
    MOVIEBOX_AVAILABLE = True
    print("✅ moviebox_api.v1 imported successfully")
except ImportError as e:
    print(f"❌ Could not import moviebox_api: {e}")

# ---------- FastAPI app ----------
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
    backdrop: Optional[str] = None
    type: str

class Episode(BaseModel):
    episode: int
    title: Optional[str] = None
    thumbnail: Optional[str] = None

class Season(BaseModel):
    season: int
    episodes: List[Episode]

class SeriesInfo(BaseModel):
    id: str
    title: str
    plot: Optional[str] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    seasons: List[Season]

class StreamResponse(BaseModel):
    url: str
    quality: Optional[str] = None
    subtitle_url: Optional[str] = None
    language: str = "en"

# ---------- Helper: Get session ----------
async def get_session():
    global session
    if session is None and MOVIEBOX_AVAILABLE:
        session = Session()
        try:
            await session.ensure_cookies_are_assigned()
            print("✅ Session initialized with cookies")
        except Exception as e:
            print(f"⚠️ Session init warning: {e}")
    return session

# ---------- Helper: Convert model to dict ----------
def to_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "dict"):
        return obj.dict()
    return obj

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE
    }

@app.get("/search", response_model=List[MediaItem])
async def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        search_obj = Search(session=sess, query=query, subject_type=0, page=1, per_page=24)
        results = await search_obj.get_content_model()
        
        items = []
        for item in results.items:
            d = to_dict(item)
            items.append(MediaItem(
                id=str(d.get("subjectId")),
                title=d.get("title"),
                year=d.get("releaseDate"),
                poster=d.get("cover"),
                backdrop=d.get("cover"),
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
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        try:
            tv = TVSeriesDetails(url_or_item=media_id, session=sess)
            info = await tv.get_content_model()
            subject = info.subject
            d = to_dict(subject)
            
            seasons_list = []
            for post in info.postList.items:
                episodes = []
                for ep in post.episodes:
                    episodes.append(Episode(
                        episode=ep.episode,
                        title=ep.title,
                        thumbnail=ep.cover
                    ))
                seasons_list.append(Season(season=post.season, episodes=episodes))
            
            return SeriesInfo(
                id=media_id,
                title=d.get("title"),
                plot=d.get("description"),
                poster=d.get("cover"),
                backdrop=d.get("cover"),
                seasons=seasons_list
            )
        except Exception:
            movie = MovieDetails(url_or_item=media_id, session=sess)
            info = await movie.get_content_model()
            subject = info.subject
            d = to_dict(subject)
            return {
                "id": media_id,
                "title": d.get("title"),
                "plot": d.get("description"),
                "poster": d.get("cover"),
                "backdrop": d.get("cover"),
                "type": "movie"
            }
    except Exception as e:
        raise HTTPException(404, f"Info error: {str(e)}")

@app.get("/stream/{media_id}")
async def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    lang: str = Query("en")
):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        item = None
        try:
            movie = MovieDetails(url_or_item=media_id, session=sess)
            info = await movie.get_content_model()
            item = info.subject
        except:
            tv = TVSeriesDetails(url_or_item=media_id, session=sess)
            info = await tv.get_content_model()
            item = info.subject
        
        if item is None:
            raise HTTPException(404, "Item not found")
        
        if season is not None and episode is not None:
            dl = DownloadableTVSeriesFilesDetail(session=sess, item=item)
            files = await dl.get_content_model(season=season, episode=episode)
        else:
            dl = DownloadableMovieFilesDetail(session=sess, item=item)
            files = await dl.get_content_model()
        
        if not files.downloads:
            raise HTTPException(404, "No stream available")
        
        best = files.best_media_file
        subtitle_url = None
        if files.english_subtitle_file:
            subtitle_url = str(files.english_subtitle_file.url)
        
        return StreamResponse(
            url=str(best.url),
            quality=f"{best.resolution}P",
            subtitle_url=subtitle_url,
            language=lang
        )
    except Exception as e:
        raise HTTPException(500, f"Stream error: {str(e)}")

@app.get("/trending")
async def trending(limit: int = 20):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        trending_obj = Trending(session=sess, page=0, per_page=limit)
        results = await trending_obj.get_content_model()
        
        items = []
        for item in results.subjectList:
            d = to_dict(item)
            items.append(MediaItem(
                id=str(d.get("subjectId")),
                title=d.get("title"),
                poster=d.get("cover"),
                type="series" if d.get("subjectType") == 2 else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Trending error: {str(e)}")
