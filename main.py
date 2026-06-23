import sys
import subprocess
import pkgutil
import importlib

# ---------- DEBUG: List installed packages ----------
print("📦 Installed packages:")
for module in pkgutil.iter_modules():
    print(f"  - {module.name}")

# ---------- Attempt to import moviebox ----------
MOVIEBOX_AVAILABLE = False
MovieboxClass = None

try:
    # Try to import the module by any name we can think of
    for name in ["moviebox", "moviebox_api", "moviebox"]:
        try:
            mod = importlib.import_module(name)
            # Try to find a class named Moviebox, Client, etc.
            for class_name in ["Moviebox", "Client", "MovieBox"]:
                if hasattr(mod, class_name):
                    MovieboxClass = getattr(mod, class_name)
                    MOVIEBOX_AVAILABLE = True
                    print(f"✅ Found {name}.{class_name}")
                    break
            if MOVIEBOX_AVAILABLE:
                break
        except ImportError:
            continue

except Exception as e:
    print(f"❌ Import error: {e}")

# ---------- Initialize client ----------
client = None
if MOVIEBOX_AVAILABLE and MovieboxClass:
    try:
        client = MovieboxClass()
        print("✅ Moviebox client initialized")
    except Exception as e:
        print(f"❌ Client init error: {e}")
        MOVIEBOX_AVAILABLE = False

# ---------- FastAPI app (unchanged) ----------
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

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

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "MovieBox API running",
        "moviebox_loaded": MOVIEBOX_AVAILABLE
    }

@app.get("/search", response_model=List[MediaItem])
def search(query: str = Query(..., min_length=1)):
    if not MOVIEBOX_AVAILABLE or client is None:
        raise HTTPException(503, "Moviebox library not loaded")
    try:
        results = client.search(query)
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
        info = client.get_info(media_id)
        if not info.get("seasons"):
            return {"id": media_id, "title": info.get("title"), "plot": info.get("overview"),
                    "poster": info.get("poster"), "backdrop": info.get("backdrop"), "type": "movie"}
        seasons_list = []
        for s in info.get("seasons", []):
            eps = [Episode(episode=e.get("episode"), title=e.get("title"), thumbnail=e.get("thumbnail"))
                   for e in s.get("episodes", [])]
            seasons_list.append(Season(season=s.get("season"), episodes=eps))
        return SeriesInfo(id=media_id, title=info.get("title"), plot=info.get("overview"),
                          poster=info.get("poster"), backdrop=info.get("backdrop"), seasons=seasons_list)
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
        sources = None
        if hasattr(client, "get_sources"):
            sources = client.get_sources(media_id, season=season, episode=episode, lang=lang)
        elif hasattr(client, "get_links"):
            sources = client.get_links(media_id, season=season, episode=episode)
        elif hasattr(client, "get_stream"):
            sources = client.get_stream(media_id, season=season, episode=episode, lang=lang)
        else:
            sources = client.get_sources(media_id, season, episode, lang)
        if not sources:
            raise HTTPException(404, "No stream available")
        best = sources[0]
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
        if hasattr(client, "trending"):
            results = client.trending(limit=limit)
        else:
            results = client.search("popular", limit=limit)
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
