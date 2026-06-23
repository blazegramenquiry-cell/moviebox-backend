import sys
import importlib
import inspect
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ---------- Import moviebox_api with fallback ----------
MOVIEBOX_AVAILABLE = False
client = None

# Try importing from various locations in the package
import_attempts = [
    ("moviebox_api", "Client"),
    ("moviebox_api", "Moviebox"),
    ("moviebox_api", "MovieBox"),
    ("moviebox_api.v1", "Client"),
    ("moviebox_api.v1", "Moviebox"),
    ("moviebox_api.v2", "Client"),
    ("moviebox_api.v2", "Moviebox"),
    ("moviebox_api.v3", "Client"),
    ("moviebox_api.v3", "Moviebox"),
]

for module_path, class_name in import_attempts:
    try:
        mod = importlib.import_module(module_path)
        if hasattr(mod, class_name):
            MovieboxClass = getattr(mod, class_name)
            # Try to instantiate
            try:
                client = MovieboxClass()
                MOVIEBOX_AVAILABLE = True
                print(f"✅ Successfully imported {module_path}.{class_name}")
                break
            except Exception as e:
                print(f"⚠️ Could not instantiate {module_path}.{class_name}: {e}")
    except ImportError:
        continue
    except Exception as e:
        print(f"⚠️ Error with {module_path}.{class_name}: {e}")

if not MOVIEBOX_AVAILABLE:
    print("❌ Could not import moviebox-api. Please check the installation logs.")
    # Try a fallback: scan the module for any class that looks like a client
    try:
        mod = importlib.import_module("moviebox_api")
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if not name.startswith("_") and name not in ("Exception", "BaseException"):
                try:
                    client = obj()
                    MOVIEBOX_AVAILABLE = True
                    print(f"✅ Fallback: found and instantiated {name}")
                    break
                except:
                    continue
    except:
        pass

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

# ---------- Helper: call method with fallback ----------
def call_method(method_name, *args, **kwargs):
    if client is None:
        raise HTTPException(503, "Client not available")
    
    # Common alternatives for method names
    alternatives = {
        "search": ["search", "get_search", "search_movies", "search_series", "find"],
        "get_info": ["get_info", "info", "get_details", "fetch_info", "details"],
        "get_sources": ["get_sources", "get_links", "get_stream", "get_episode", "fetch_sources", "sources"],
        "trending": ["trending", "get_trending", "popular", "get_popular", "homepage", "get_homepage"],
    }
    
    # Try the method name and all alternatives
    for name in [method_name] + alternatives.get(method_name, []):
        if hasattr(client, name) and callable(getattr(client, name)):
            method = getattr(client, name)
            try:
                return method(*args, **kwargs)
            except TypeError:
                # Try without optional args if we have them
                if kwargs:
                    try:
                        return method(*args)
                    except:
                        continue
                continue
    raise HTTPException(500, f"No suitable method found for {method_name}")

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API is running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE,
        "client_type": str(type(client)) if client else None
    }

@app.get("/search", response_model=List[MediaItem])
def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        results = call_method("search", query)
        items = []
        for r in results:
            items.append(MediaItem(
                id=str(r.get("id") or r.get("movie_id")),
                title=r.get("title") or r.get("name"),
                year=r.get("year"),
                poster=r.get("poster") or r.get("image"),
                backdrop=r.get("backdrop"),
                type="series" if r.get("is_series") or r.get("type") == "series" else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Search error: {str(e)}")

@app.get("/info/{media_id}")
def get_info(media_id: str):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    try:
        info = call_method("get_info", media_id)
        if not info.get("seasons"):
            return {
                "id": media_id,
                "title": info.get("title"),
                "plot": info.get("overview"),
                "poster": info.get("poster"),
                "backdrop": info.get("backdrop"),
                "type": "movie"
            }
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
            plot=info.get("overview"),
            poster=info.get("poster"),
            backdrop=info.get("backdrop"),
            seasons=seasons_list
        )
    except Exception as e:
        raise HTTPException(404, f"Info error: {str(e)}")

@app.get("/stream/{media_id}")
def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    lang: str = Query("en")
):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    try:
        # Try getting sources with different arguments
        sources = None
        if season is not None and episode is not None:
            try:
                sources = call_method("get_sources", media_id, season, episode, lang)
            except:
                sources = call_method("get_sources", media_id, season=season, episode=episode, lang=lang)
        else:
            sources = call_method("get_sources", media_id, lang=lang)
        
        if not sources:
            raise HTTPException(404, "No stream available")
        best = sources[0] if isinstance(sources, list) else sources
        return StreamResponse(
            url=best.get("url"),
            quality=best.get("quality") or "720p",
            subtitle_url=best.get("subtitle_url"),
            language=lang
        )
    except Exception as e:
        raise HTTPException(500, f"Stream error: {str(e)}")

@app.get("/trending")
def trending(limit: int = 20):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    try:
        results = call_method("trending", limit=limit)
        if not isinstance(results, list):
            results = results.get("results", []) if isinstance(results, dict) else []
        items = []
        for r in results:
            items.append(MediaItem(
                id=str(r.get("id")),
                title=r.get("title"),
                poster=r.get("poster"),
                type="series" if r.get("type") == "series" else "movie"
            ))
        return items
    except Exception as e:
        raise HTTPException(500, f"Trending error: {str(e)}")
