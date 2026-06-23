import asyncio
import json
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

# ---------- Helper: Get session ----------
async def get_session():
    global session
    if session is None and MOVIEBOX_AVAILABLE:
        session = Session()
        try:
            await session.get_moviebox_app_info()
            print("✅ Session initialized")
        except Exception as e:
            print(f"⚠️ Session init warning: {e}")
    return session

# ---------- Helper: Call method with fallback ----------
def call_method(obj, method_names, *args, **kwargs):
    """Try multiple method names until one works."""
    for name in method_names:
        if hasattr(obj, name) and callable(getattr(obj, name)):
            try:
                return getattr(obj, name)(*args, **kwargs)
            except Exception:
                continue
    raise AttributeError(f"No suitable method found among {method_names} in {obj}")

# ---------- Helper: Get search results ----------
async def get_search_results(query):
    sess = await get_session()
    if sess is None:
        raise Exception("No session")
    search_obj = Search(session=sess, query=query)
    result = call_method(search_obj, ["get_results", "search", "get", "fetch", "results", "get_content"])
    if isinstance(result, str):
        result = json.loads(result)
    return result

# ---------- Helper: Get trending ----------
async def get_trending_results():
    sess = await get_session()
    if sess is None:
        raise Exception("No session")
    trending_obj = Trending(session=sess)
    result = call_method(trending_obj, ["get_content", "get", "fetch", "content", "results"])
    if isinstance(result, str):
        result = json.loads(result)
    return result

# ---------- Helper: Get info ----------
async def get_info_data(media_id):
    sess = await get_session()
    if sess is None:
        raise Exception("No session")
    # Try TV series first
    try:
        tv_obj = TVSeriesDetails(session=sess, url_or_item=media_id)
        info = call_method(tv_obj, ["get_details", "details", "get", "fetch"])
        if isinstance(info, str):
            info = json.loads(info)
        return info, "tv"
    except:
        pass
    # Fall back to movie
    movie_obj = MovieDetails(session=sess, url_or_item=media_id)
    info = call_method(movie_obj, ["get_details", "details", "get", "fetch"])
    if isinstance(info, str):
        info = json.loads(info)
    return info, "movie"

# ---------- Helper: Get stream ----------
async def get_stream_data(media_id, season=None, episode=None):
    sess = await get_session()
    if sess is None:
        raise Exception("No session")
    if season is not None and episode is not None:
        obj = DownloadableTVSeriesFilesDetail(session=sess, item=media_id, season=season, episode=episode)
    else:
        obj = DownloadableMovieFilesDetail(session=sess, item=media_id)
    sources = call_method(obj, ["get_downloadable_files", "get_sources", "get_links", "fetch"])
    if isinstance(sources, str):
        sources = json.loads(sources)
    return sources

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {"status": "ok", "moviebox_loaded": MOVIEBOX_AVAILABLE}

@app.get("/search", response_model=List[MediaItem])
async def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        results = await get_search_results(query)
        if not isinstance(results, list):
            if isinstance(results, dict):
                results = results.get("items") or results.get("results") or [results]
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
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        info, typ = await get_info_data(media_id)
        if typ == "tv":
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
        else:
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
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        sources = await get_stream_data(media_id, season, episode)
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
    if not MOVIEBOX_AVAILABLE:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        results = await get_trending_results()
        if not isinstance(results, list):
            if isinstance(results, dict):
                results = results.get("subjectList") or results.get("items") or results.get("results") or [results]
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
