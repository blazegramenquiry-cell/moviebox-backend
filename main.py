import sys
import importlib
import inspect
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ---------- Import moviebox_api with session ----------
MOVIEBOX_AVAILABLE = False
session = None

# Import the package
try:
    package = importlib.import_module("moviebox_api")
    print("✅ moviebox_api imported successfully")
    
    # Try to create a session
    # The library likely uses httpx sessions internally
    try:
        import httpx
        session = httpx.Client()
        print("✅ HTTPX session created")
        MOVIEBOX_AVAILABLE = True
    except Exception as e:
        print(f"⚠️ Could not create session: {e}")
        
except ImportError as e:
    print(f"❌ Could not import moviebox_api: {e}")

# Dictionary to cache imported classes
classes = {}

def get_class(module_path, class_name):
    """Import and cache a class from moviebox_api."""
    cache_key = f"{module_path}.{class_name}"
    if cache_key in classes:
        return classes[cache_key]
    try:
        mod = importlib.import_module(module_path)
        if hasattr(mod, class_name):
            cls = getattr(mod, class_name)
            classes[cache_key] = cls
            print(f"✅ Loaded {module_path}.{class_name}")
            return cls
    except Exception as e:
        print(f"⚠️ Could not load {module_path}.{class_name}: {e}")
    return None

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

# ---------- Helper: call with class ----------
def call_with_class(module_path, class_name, method_name, *args, **kwargs):
    """Instantiate a class with session and call a method."""
    if not MOVIEBOX_AVAILABLE or session is None:
        raise HTTPException(503, "Moviebox session not available")
    cls = get_class(module_path, class_name)
    if cls is None:
        raise HTTPException(500, f"Class {class_name} not found in {module_path}")
    try:
        # Instantiate with session
        instance = cls(session=session)
        if hasattr(instance, method_name):
            method = getattr(instance, method_name)
            return method(*args, **kwargs)
        else:
            raise HTTPException(500, f"Method {method_name} not found in {class_name}")
    except Exception as e:
        raise HTTPException(500, f"Error in {class_name}.{method_name}: {str(e)}")

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE,
        "session_type": str(type(session)) if session else None
    }

@app.get("/search", response_model=List[MediaItem])
def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE or session is None:
        raise HTTPException(503, "Moviebox session not available")
    try:
        # Try v1.Search class
        cls = get_class("moviebox_api.v1", "Search")
        if cls is None:
            cls = get_class("moviebox_api.v1.core", "Search")
        if cls is None:
            raise HTTPException(500, "Search class not found")
        
        instance = cls(session=session, query=query)
        results = instance.get_results()
        
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
def get_info(media_id: str):
    if not MOVIEBOX_AVAILABLE or session is None:
        raise HTTPException(503, "Moviebox session not available")
    try:
        # Try v1.TVSeriesDetails or v1.MovieDetails
        # First try TV series
        tv_cls = get_class("moviebox_api.v1", "TVSeriesDetails")
        if tv_cls is not None:
            try:
                instance = tv_cls(session=session, url_or_item=media_id)
                info = instance.get_details()
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
            except:
                pass  # Fall through to movie
        
        # Try movie
        movie_cls = get_class("moviebox_api.v1", "MovieDetails")
        if movie_cls is not None:
            instance = movie_cls(session=session, url_or_item=media_id)
            info = instance.get_details()
            return {
                "id": media_id,
                "title": info.get("title"),
                "plot": info.get("description"),
                "poster": info.get("cover"),
                "backdrop": info.get("cover"),
                "type": "movie"
            }
        
        raise HTTPException(500, "No info class found")
    except Exception as e:
        raise HTTPException(404, f"Info error: {str(e)}")

@app.get("/stream/{media_id}")
def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    lang: str = Query("en")
):
    if not MOVIEBOX_AVAILABLE or session is None:
        raise HTTPException(503, "Moviebox session not available")
    try:
        # Try to get downloadable files
        if season is not None and episode is not None:
            # TV series episode
            cls = get_class("moviebox_api.v1.download", "DownloadableTVSeriesFilesDetail")
            if cls is None:
                raise HTTPException(500, "DownloadableTVSeriesFilesDetail not found")
            instance = cls(session=session, item=media_id, season=season, episode=episode)
            sources = instance.get_downloadable_files()
        else:
            # Movie
            cls = get_class("moviebox_api.v1.download", "DownloadableMovieFilesDetail")
            if cls is None:
                raise HTTPException(500, "DownloadableMovieFilesDetail not found")
            instance = cls(session=session, item=media_id)
            sources = instance.get_downloadable_files()
        
        if not sources:
            raise HTTPException(404, "No stream available")
        
        # Find the best quality or first source
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
def trending(limit: int = 20):
    if not MOVIEBOX_AVAILABLE or session is None:
        raise HTTPException(503, "Moviebox session not available")
    try:
        # Use v1.Trending class
        cls = get_class("moviebox_api.v1", "Trending")
        if cls is None:
            cls = get_class("moviebox_api.v1.core", "Trending")
        if cls is None:
            raise HTTPException(500, "Trending class not found")
        
        instance = cls(session=session)
        results = instance.get_content()
        
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
