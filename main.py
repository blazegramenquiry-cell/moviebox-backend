import sys
import importlib
import inspect
import pkgutil
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ---------- Deep discovery of moviebox_api ----------
MOVIEBOX_AVAILABLE = False
client = None

def discover_client():
    """Search all submodules of moviebox_api for a suitable client class."""
    try:
        # Import the top-level package
        package = importlib.import_module("moviebox_api")
        print("✅ Top-level package 'moviebox_api' imported.")
        print("📋 Top-level attributes:", [a for a in dir(package) if not a.startswith("_")])

        # Walk all submodules
        for importer, modname, ispkg in pkgutil.walk_packages(path=package.__path__, prefix="moviebox_api."):
            try:
                mod = importlib.import_module(modname)
                print(f"🔍 Inspecting {modname}...")
                # Find classes that are not built-in
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if name.startswith("_"):
                        continue
                    if name in ("Exception", "BaseException", "object"):
                        continue
                    # Try to instantiate with no args
                    try:
                        instance = obj()
                        # Check if it has common methods
                        if any(hasattr(instance, m) for m in ["search", "get_info", "get_sources"]):
                            print(f"✅ Found candidate: {modname}.{name}")
                            return instance
                        else:
                            # Still, if it has no methods, skip
                            continue
                    except Exception as e:
                        print(f"⚠️ Could not instantiate {modname}.{name}: {e}")
            except ImportError as e:
                print(f"⚠️ Could not import {modname}: {e}")
            except Exception as e:
                print(f"⚠️ Error in {modname}: {e}")
        return None
    except ImportError:
        print("❌ Could not import moviebox_api at all.")
        return None

# Run discovery
client = discover_client()
if client:
    MOVIEBOX_AVAILABLE = True
    print("✅ Client successfully instantiated.")
else:
    print("❌ No suitable client found.")

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

# ---------- Helper: call method with fallback ----------
def call_method(method_name, *args, **kwargs):
    if client is None:
        raise HTTPException(503, "Client not available")
    alt_methods = {
        "search": ["search", "get_search", "search_movies", "search_series"],
        "get_info": ["get_info", "info", "get_details", "fetch_info"],
        "get_sources": ["get_sources", "get_links", "get_stream", "get_episode"],
        "trending": ["trending", "get_trending", "popular"],
    }
    for name in [method_name] + alt_methods.get(method_name, []):
        if hasattr(client, name) and callable(getattr(client, name)):
            try:
                return getattr(client, name)(*args, **kwargs)
            except Exception:
                continue
    raise HTTPException(500, f"No suitable method for {method_name}")

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE,
        "client_type": str(type(client)) if client else None
    }

@app.get("/search", response_model=List[MediaItem])
def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    results = call_method("search", query)
    items = []
    for r in results:
        items.append(MediaItem(
            id=str(r.get("id") or r.get("movie_id")),
            title=r.get("title") or r.get("name"),
            year=r.get("year"),
            poster=r.get("poster") or r.get("image"),
            backdrop=r.get("backdrop"),
            type="series" if r.get("is_series") else "movie"
        ))
    return items

@app.get("/info/{media_id}")
def get_info(media_id: str):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    info = call_method("get_info", media_id)
    if not info.get("seasons"):
        return {"id": media_id, "title": info.get("title"), "plot": info.get("overview"),
                "poster": info.get("poster"), "backdrop": info.get("backdrop"), "type": "movie"}
    seasons = []
    for s in info.get("seasons", []):
        eps = [Episode(episode=e.get("episode"), title=e.get("title"), thumbnail=e.get("thumbnail"))
               for e in s.get("episodes", [])]
        seasons.append(Season(season=s.get("season"), episodes=eps))
    return SeriesInfo(id=media_id, title=info.get("title"), plot=info.get("overview"),
                      poster=info.get("poster"), backdrop=info.get("backdrop"), seasons=seasons)

@app.get("/stream/{media_id}")
def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    lang: str = Query("en")
):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
    if season is not None and episode is not None:
        sources = call_method("get_sources", media_id, season, episode, lang)
    else:
        sources = call_method("get_sources", media_id, lang=lang)
    if not sources:
        raise HTTPException(404, "No stream")
    best = sources[0] if isinstance(sources, list) else sources
    return StreamResponse(
        url=best.get("url"),
        quality=best.get("quality") or "720p",
        subtitle_url=best.get("subtitle_url"),
        language=lang
    )

@app.get("/trending")
def trending(limit: int = 20):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox not loaded")
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
