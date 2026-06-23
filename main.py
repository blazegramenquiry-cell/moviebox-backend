import asyncio
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ---------- Import moviebox_api ----------
MOVIEBOX_AVAILABLE = False
session = None

try:
    from moviebox_api.v1 import Session, Search, Trending, MovieDetails, TVSeriesDetails
    from moviebox_api.v1.download import DownloadableMovieFilesDetail, DownloadableTVSeriesFilesDetail
    MOVIEBOX_AVAILABLE = True
    print("✅ moviebox_api.v1 imported successfully")
except ImportError as e:
    print(f"❌ Could not import moviebox_api: {e}")

# ---------- FastAPI app ----------
app = FastAPI(title="MovieBox API")
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

# ---------- Helper: Get or create session ----------
async def get_session():
    global session
    if session is None and MOVIEBOX_AVAILABLE:
        session = Session()
        # Fetch app info to initialize cookies
        try:
            await session.get_moviebox_app_info()
            print("✅ Session initialized with cookies")
        except Exception as e:
            print(f"⚠️ Session init warning: {e}")
    return session

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE
    }

@app.get("/search", response_model=List[MediaItem])
async def search(query: str = Query(..., min_length=1, description="Search term")):
    """
    Search for movies or TV series.
    Example: /search?query=naruto
    """
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        search_obj = Search(session=sess, query=query)
        results = await search_obj.get_results()
        
        items = []
        for r in results:
            items.append(MediaItem(
                id=str(r.get("subjectId") or r.get("id")),
                title=r.get("title"),
                year=r.get("releaseDate"),
                poster=r.get("cover"),
                backdrop=r.get("cover"),
                type="series" if r.get("subjectType") == "tv" else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Search error: {str(e)}")

@app.get("/info/{media_id}")
async def get_info(media_id: str):
    """
    Get detailed info for a movie or TV series.
    Example: /info/12345
    """
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        # Try TV series first
        try:
            tv = TVSeriesDetails(session=sess, url_or_item=media_id)
            info = await tv.get_details()
            seasons_list = []
            for s in info.get("seasons", []):
                eps = [Episode(
                    episode=e.get("episode"),
                    title=e.get("title"),
                    thumbnail=e.get("thumbnail")
                ) for e in s.get("episodes", [])]
                seasons_list.append(Season(season=s.get("season"), episodes=eps))
            return SeriesInfo(
                id=media_id,
                title=info.get("title"),
                plot=info.get("description"),
                poster=info.get("cover"),
                backdrop=info.get("cover"),
                seasons=seasons_list
            )
        except Exception:
            # Fall back to movie
            movie = MovieDetails(session=sess, url_or_item=media_id)
            info = await movie.get_details()
            return {
                "id": media_id,
                "title": info.get("title"),
                "plot": info.get("description"),
                "poster": info.get("cover"),
                "backdrop": info.get("cover"),
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
    """
    Get streaming URL for a movie or TV episode.
    For movies: /stream/12345
    For TV: /stream/12345?season=1&episode=3&lang=en
    """
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        if season is not None and episode is not None:
            # TV series episode
            dl = DownloadableTVSeriesFilesDetail(
                session=sess,
                item=media_id,
                season=season,
                episode=episode
            )
            sources = await dl.get_downloadable_files()
        else:
            # Movie
            dl = DownloadableMovieFilesDetail(
                session=sess,
                item=media_id
            )
            sources = await dl.get_downloadable_files()
        
        if not sources:
            raise HTTPException(404, "No stream available")
        
        best = sources[0] if isinstance(sources, list) else sources
        url = best.get("url") or best.get("sniffUrl") or best.get("sourceUrl")
        
        return StreamResponse(
            url=url,
            quality=best.get("resolution") or best.get("quality") or "720p",
            subtitle_url=best.get("subtitle_url"),
            language=lang
        )
    except Exception as e:
        raise HTTPException(500, f"Stream error: {str(e)}")

@app.get("/trending")
async def trending(limit: int = 20):
    """
    Get trending movies and TV series.
    Example: /trending?limit=20
    """
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    
    sess = await get_session()
    if sess is None:
        raise HTTPException(503, "Could not create session")
    
    try:
        trending_obj = Trending(session=sess)
        results = await trending_obj.get_content()
        
        items = []
        for r in results:
            items.append(MediaItem(
                id=str(r.get("subjectId") or r.get("id")),
                title=r.get("title"),
                poster=r.get("cover"),
                type="series" if r.get("subjectType") == "tv" else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Trending error: {str(e)}")
