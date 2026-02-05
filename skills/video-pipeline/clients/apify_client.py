"""
Apify Client for YouTube Trending Video Scraping.

Uses Apify actors to scrape trending/top-performing YouTube videos
in specific niches for idea generation.
"""

import os
from typing import Optional
from apify_client import ApifyClient


class ApifyYouTubeClient:
    """Client for scraping YouTube data via Apify actors."""

    # Apify actor IDs for YouTube scraping
    # streamers/youtube-scraper - publicly accessible
    YOUTUBE_SCRAPER_ACTOR = "streamers/youtube-scraper"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with Apify API key.

        Args:
            api_key: Apify API token. Falls back to APIFY_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("APIFY_API_KEY")
        if not self.api_key:
            raise ValueError("APIFY_API_KEY not found in environment")

        self.client = ApifyClient(self.api_key)

    async def search_trending_videos(
        self,
        search_queries: list[str],
        max_results_per_query: int = 10,
        sort_by: str = "relevance",
        upload_date: str = "month",
    ) -> list[dict]:
        """Search YouTube for trending videos matching queries.

        Uses the bernardo/youtube-scraper actor which is reliable and well-maintained.

        Args:
            search_queries: List of search terms (e.g., ["economy collapse", "fed rate cuts"])
            max_results_per_query: Max videos per search query
            sort_by: Sort order - "relevance", "date", "viewCount", "rating"
            upload_date: Filter - "hour", "day", "week", "month", "year"

        Returns:
            List of video data dicts with title, views, likes, url, thumbnail, etc.
        """
        all_videos = []

        # Build input for the search scraper
        print(f"  Queued {len(search_queries)} search queries")

        # Build search URLs for YouTube
        start_urls = []
        for query in search_queries:
            encoded_query = query.replace(" ", "+")
            url = f"https://www.youtube.com/results?search_query={encoded_query}"
            start_urls.append({"url": url})

        run_input = {
            "startUrls": start_urls,
            "maxResults": max_results_per_query * len(search_queries),
        }

        print(f"  Running Apify scraper...")
        run = self.client.actor(self.YOUTUBE_SCRAPER_ACTOR).call(run_input=run_input)

        # Fetch results from the dataset
        items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"  Scraper returned {len(items)} items")

        for item in items:
            video_data = self._normalize_video_data(item)
            if video_data:
                all_videos.append(video_data)

        print(f"  Normalized {len(all_videos)} videos")
        return all_videos

    async def scrape_channel_videos(
        self,
        channel_urls: list[str],
        max_videos_per_channel: int = 20,
    ) -> list[dict]:
        """Scrape videos from specific YouTube channels.

        Args:
            channel_urls: List of channel URLs
            max_videos_per_channel: Max videos to fetch per channel

        Returns:
            List of video data dicts
        """
        all_videos = []

        # Build start URLs for channels
        start_urls = [{"url": url} for url in channel_urls]

        print(f"  Scraping {len(channel_urls)} channels...")

        run_input = {
            "startUrls": start_urls,
            "maxResults": max_videos_per_channel * len(channel_urls),
            "maxResultsShorts": 0,
            "maxResultStreams": 0,
        }

        run = self.client.actor(self.YOUTUBE_SCRAPER_ACTOR).call(run_input=run_input)
        items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())

        for item in items:
            video_data = self._normalize_video_data(item)
            if video_data:
                all_videos.append(video_data)

        print(f"    Found {len(all_videos)} videos")

        return all_videos

    def _normalize_video_data(self, raw_item: dict) -> Optional[dict]:
        """Normalize video data from various Apify actor formats.

        Returns standardized video dict or None if invalid.
        """
        # Handle different field naming conventions from various actors
        video_id = (
            raw_item.get("id") or
            raw_item.get("videoId") or
            raw_item.get("video_id")
        )

        title = (
            raw_item.get("title") or
            raw_item.get("name") or
            ""
        )

        if not video_id or not title:
            return None

        # Extract view count (may be string like "1.2M views" or int)
        views_raw = (
            raw_item.get("viewCount") or
            raw_item.get("views") or
            raw_item.get("view_count") or
            0
        )
        views = self._parse_count(views_raw)

        # Extract likes
        likes_raw = (
            raw_item.get("likeCount") or
            raw_item.get("likes") or
            raw_item.get("like_count") or
            0
        )
        likes = self._parse_count(likes_raw)

        # Extract thumbnail
        thumbnail = (
            raw_item.get("thumbnailUrl") or
            raw_item.get("thumbnail") or
            raw_item.get("thumbnails", [{}])[0].get("url") or
            f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        )

        return {
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": thumbnail,
            "views": views,
            "likes": likes,
            "channel": raw_item.get("channelName") or raw_item.get("channel") or "",
            "channel_url": raw_item.get("channelUrl") or "",
            "description": raw_item.get("description") or "",
            "duration": raw_item.get("duration") or "",
            "published_at": raw_item.get("publishedAt") or raw_item.get("uploadDate") or "",
        }

    def _parse_count(self, value) -> int:
        """Parse view/like counts that may be strings like '1.2M' or ints."""
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if not isinstance(value, str):
            return 0

        # Remove commas and spaces
        value = value.replace(",", "").replace(" ", "").lower()

        # Remove "views" or "likes" suffix
        value = value.replace("views", "").replace("likes", "").strip()

        try:
            # Handle K, M, B suffixes
            if value.endswith("k"):
                return int(float(value[:-1]) * 1_000)
            elif value.endswith("m"):
                return int(float(value[:-1]) * 1_000_000)
            elif value.endswith("b"):
                return int(float(value[:-1]) * 1_000_000_000)
            else:
                return int(float(value))
        except (ValueError, TypeError):
            return 0

    def analyze_trending_patterns(self, videos: list[dict]) -> dict:
        """Analyze patterns in trending videos.

        Args:
            videos: List of video data dicts

        Returns:
            Analysis dict with title patterns, top performers, etc.
        """
        if not videos:
            return {"error": "No videos to analyze"}

        # Sort by views
        sorted_by_views = sorted(videos, key=lambda x: x.get("views", 0), reverse=True)

        # Extract title patterns
        titles = [v.get("title", "") for v in videos]

        # Find common title elements
        title_words = []
        for title in titles:
            words = title.lower().split()
            title_words.extend(words)

        # Count word frequency (exclude common words)
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                      "being", "have", "has", "had", "do", "does", "did", "will",
                      "would", "could", "should", "may", "might", "must", "shall",
                      "to", "of", "in", "for", "on", "with", "at", "by", "from",
                      "up", "about", "into", "through", "during", "before", "after",
                      "above", "below", "between", "under", "again", "further", "then",
                      "once", "here", "there", "when", "where", "why", "how", "all",
                      "each", "few", "more", "most", "other", "some", "such", "no",
                      "nor", "not", "only", "own", "same", "so", "than", "too", "very",
                      "just", "and", "but", "if", "or", "because", "as", "until",
                      "while", "this", "that", "these", "those", "i", "you", "he",
                      "she", "it", "we", "they", "what", "which", "who", "whom",
                      "|", "-", "–", "—", ":", "?", "!", "...", "'s", "'t"}

        word_counts = {}
        for word in title_words:
            word = word.strip(".,!?:;\"'()[]{}|")
            if word and word not in stop_words and len(word) > 2:
                word_counts[word] = word_counts.get(word, 0) + 1

        # Top keywords
        top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]

        # Title structure patterns (presence of numbers, questions, etc.)
        patterns = {
            "has_number": sum(1 for t in titles if any(c.isdigit() for c in t)),
            "has_question": sum(1 for t in titles if "?" in t),
            "has_colon": sum(1 for t in titles if ":" in t),
            "has_caps_word": sum(1 for t in titles if any(w.isupper() and len(w) > 1 for w in t.split())),
            "has_year": sum(1 for t in titles if any(str(y) in t for y in range(2024, 2031))),
        }

        return {
            "total_videos": len(videos),
            "top_10_by_views": [
                {
                    "title": v.get("title"),
                    "views": v.get("views"),
                    "channel": v.get("channel"),
                    "url": v.get("url"),
                }
                for v in sorted_by_views[:10]
            ],
            "avg_views": sum(v.get("views", 0) for v in videos) // len(videos) if videos else 0,
            "top_keywords": top_keywords,
            "title_patterns": patterns,
            "all_titles": titles,
        }
