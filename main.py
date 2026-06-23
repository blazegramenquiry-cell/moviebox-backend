import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the moviebox library
from moviebox import Moviebox

load_dotenv()

app = FastAPI(
    title="MovieBox API Wrapper",
    description="Backend for XiON Android app to stream movies/series",
    version="1.0.0"
)

# Initialize the Moviebox client (some versions need config/token)
# If no token required: client = Moviebox()
client = Moviebox()

# ---------- Response Models ----------
class MediaItem(BaseModel):
    id: str
    title: str
    year: Optional[str] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    type: str  # "movie" or "series"

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
    return {"message": "MovieBox API is running. Use /search, /info, /stream"}


@app.get("/search", response_model=List[MediaItem])
def search(query: str = Query(..., min_length=2, description="Search term")):
    """
    Search for movies or TV series.
    """
    try:
        results = client.search(query)
        items = []
        for r in results:
            # Adjust mapping based on actual response structure of moviebox
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
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.get("/info/{media_id}")
def get_info(media_id: str):
    """
    Get detailed info for a movie or series, including seasons and episodes.
    """
    try:
        # Fetch detailed info
        info = client.get_info(media_id)
        
        # If it's a movie, return simple movie info
        if not info.get("seasons"):
            return {
                "id": media_id,
                "title": info.get("title"),
                "plot": info.get("overview"),
                "poster": info.get("poster"),
                "backdrop": info.get("backdrop"),
                "type": "movie"
            }
        
        # If it's a TV series, build seasons/episodes
        seasons_list = []
        for season_data in info.get("seasons", []):
            season_num = season_data.get("season")
            episodes = []
            for ep in season_data.get("episodes", []):
                episodes.append(Episode(
                    episode=ep.get("episode"),
                    title=ep.get("title"),
                    thumbnail=ep.get("thumbnail")
                ))
            seasons_list.append(Season(season=season_num, episodes=episodes))
        
        return SeriesInfo(
            id=media_id,
            title=info.get("title"),
            plot=info.get("overview"),
            poster=info.get("poster"),
            backdrop=info.get("backdrop"),
            seasons=seasons_list
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Media not found: {str(e)}")


@app.get("/stream/{media_id}")
def get_stream(
    media_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    lang: str = Query("en", description="Language code (en, es, fr, etc.)")
):
    """
    Get the direct streaming URL and subtitles for a specific episode or movie.
    - For movies: omit season/episode.
    - For TV series: provide season AND episode.
    """
    try:
        # The actual method name may differ (e.g., get_sources, get_links)
        # Adjust the call below based on the real moviebox API:
        # If method is get_episode_source(media_id, season, episode, lang)
        # or get_stream(media_id, season, episode, lang)
        
        # Example 1: If the library has get_sources()
        sources = client.get_sources(media_id, season=season, episode=episode, lang=lang)
        
        # Example 2: If you need to filter by language manually
        # sources = client.get_sources(media_id, season, episode)
        # best_source = next((s for s in sources if s["lang"] == lang), sources[0])
        
        if not sources:
            raise HTTPException(status_code=404, detail="No streams available for this media")
        
        # Pick the highest quality available (or just the first)
        best = sources[0]
        return StreamResponse(
            url=best.get("url"),
            quality=best.get("quality") or "720p",
            subtitle_url=best.get("subtitle_url"),  # optional
            language=lang
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stream retrieval failed: {str(e)}")


@app.get("/trending")
def trending(limit: int = 20):
    """
    Fetch trending movies/series (if supported by the library).
    """
    try:
        # If moviebox has a trending() method, use it; else fallback to popular search
        if hasattr(client, "trending"):
            results = client.trending(limit=limit)
        else:
            # Fallback: search popular terms or cached list (you can extend this)
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
        raise HTTPException(status_code=500, detail=f"Trending fetch failed: {str(e)}")

# ---------- Run (for local testing) ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
