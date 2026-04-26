"""HTML parser for Nitter pages."""

import logging
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag
from models import UserProfile, Tweet, UserSearchResult

log = logging.getLogger("twapi.parser")


def _text(el: Tag | None, default: str = "") -> str:
    return el.get_text(strip=True) if el else default


def _attr(el: Tag | None, attr: str, default: str = "") -> str:
    if el is None:
        return default
    val = el.get(attr)
    return str(val) if val else default


def _fix_img_url(url: str, base: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("/pic/"):
        decoded = unquote(url[5:])
        if decoded.startswith("http"):
            return decoded
        return "https://pbs.twimg.com/" + decoded
    return base.rstrip("/") + url


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------

def parse_user_profile(html: str, base_url: str) -> UserProfile:
    soup = BeautifulSoup(html, "lxml")
    profile = soup.select_one(".profile-card")
    if not profile:
        raise ValueError("Profile card not found – user may not exist")

    username = _text(profile.select_one(".profile-card-username")).lstrip("@")
    display_name = _text(profile.select_one(".profile-card-fullname"))
    avatar_url = _fix_img_url(_attr(profile.select_one(".profile-card-avatar img"), "src"), base_url)
    banner_el = soup.select_one(".profile-banner a") or soup.select_one(".profile-banner img")
    banner_url = ""
    if banner_el:
        banner_url = _fix_img_url(_attr(banner_el, "href") or _attr(banner_el, "src"), base_url)
    bio = _text(profile.select_one(".profile-bio"))
    location = _text(profile.select_one(".profile-location"))
    website = _text(profile.select_one(".profile-website a")) or _attr(profile.select_one(".profile-website a"), "href")
    join_date = _text(profile.select_one(".profile-joindate"))

    stat_els = profile.select(".profile-stat-num")
    counts = [_text(e) for e in stat_els]
    tweets_count = counts[0] if len(counts) > 0 else ""
    following_count = counts[1] if len(counts) > 1 else ""
    followers_count = counts[2] if len(counts) > 2 else ""
    likes_count = counts[3] if len(counts) > 3 else ""

    return UserProfile(
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
        banner_url=banner_url,
        bio=bio,
        location=location,
        website=website,
        join_date=join_date,
        tweets_count=tweets_count,
        following_count=following_count,
        followers_count=followers_count,
        likes_count=likes_count,
    )


# ---------------------------------------------------------------------------
# Tweets (timeline / search results)
# ---------------------------------------------------------------------------

def parse_tweet_item(item: Tag, base_url: str) -> Tweet:
    # The item may be .tweet-body inside .timeline-item
    # Walk up to timeline-item to find .tweet-link sibling
    parent = item
    max_depth = 20  # Guard against infinite loop / malformed DOM
    depth = 0
    while parent and "timeline-item" not in (parent.get("class") or []):
        parent = parent.parent
        depth += 1
        if depth >= max_depth:
            break

    is_retweet = item.select_one(".retweet-header") is not None
    is_pinned = item.select_one(".pinned") is not None

    # author info – xcancel uses .fullname / .username classes
    author = _text(item.select_one(".tweet-header .username")).lstrip("@")
    display_name = _text(item.select_one(".tweet-header .fullname"))
    avatar_el = item.select_one(".tweet-header img.avatar") or item.select_one(".tweet-avatar img")
    avatar_url = _fix_img_url(_attr(avatar_el, "src"), base_url)

    # tweet body
    text = _text(item.select_one(".tweet-content"))
    date = _attr(item.select_one(".tweet-date a"), "title") or _text(item.select_one(".tweet-date a"))

    # tweet link / id – robust regex extraction
    link_el = item.select_one(".tweet-link")
    if not link_el and parent:
        link_el = parent.select_one("a.tweet-link")
    link = _attr(link_el, "href") if link_el else ""
    # strip fragment (#m)
    link_clean = link.split("#")[0] if link else ""
    tweet_id = ""
    if link_clean:
        m = re.search(r"/status/(\d+)", link_clean)
        if m:
            tweet_id = m.group(1)

    # stats – xcancel structure: <span class="tweet-stat"><div class="icon-container"><span class="icon-X"></span> NUM</div></span>
    stat_container = item.select(".tweet-stat")
    replies = "0"
    retweets = "0"
    quotes = "0"
    likes = "0"
    for stat in stat_container:
        icon_div = stat.select_one(".icon-container")
        if not icon_div:
            continue
        # find the actual icon span inside .icon-container
        icon_span = icon_div.select_one("span[class]")
        if not icon_span:
            continue
        icon_cls = " ".join(icon_span.get("class", []))
        # extract number: get all text from the icon-container, which includes the number
        raw = icon_div.get_text(strip=True)
        nums = re.findall(r"[\d,]+", raw)
        val = nums[0] if nums else "0"
        if "icon-comment" in icon_cls or "icon-reply" in icon_cls:
            replies = val
        elif "icon-retweet" in icon_cls:
            retweets = val
        elif "icon-quote" in icon_cls:
            quotes = val
        elif "icon-heart" in icon_cls or "icon-like" in icon_cls:
            likes = val

    # media
    images: list[str] = []
    for img_el in item.select(".attachments .still-image"):
        src = _attr(img_el, "href") or _attr(img_el.select_one("img"), "src")
        if src:
            images.append(_fix_img_url(src, base_url))

    videos: list[str] = []
    for vid_el in item.select(".attachments video source"):
        src = _attr(vid_el, "src")
        if src:
            videos.append(_fix_img_url(src, base_url))

    return Tweet(
        id=tweet_id,
        author=author,
        display_name=display_name,
        avatar_url=avatar_url,
        text=text,
        date=date,
        retweets=retweets,
        quotes=quotes,
        likes=likes,
        replies=replies,
        images=images,
        videos=videos,
        is_retweet=is_retweet,
        is_pinned=is_pinned,
        link=link,
    )


def parse_tweets(html: str, base_url: str) -> tuple[list[Tweet], str]:
    """Return (tweets, cursor) from a timeline/search page."""
    soup = BeautifulSoup(html, "lxml")
    tweets: list[Tweet] = []
    for tl_item in soup.select(".timeline-item"):
        body = tl_item.select_one(".tweet-body")
        if not body:
            continue
        try:
            tweets.append(parse_tweet_item(body, base_url))
        except Exception:
            log.debug("Failed to parse tweet item, skipping", exc_info=True)
            continue

    # pagination cursor – pick the show-more link that contains "cursor="
    cursor = ""
    for show_more in soup.select(".show-more a"):
        href = _attr(show_more, "href")
        if "cursor=" in href:
            cursor = href.split("cursor=")[-1].split("&")[0]
            break

    return tweets, cursor


def parse_tweet_detail(html: str, base_url: str) -> tuple[Tweet | None, list[Tweet]]:
    """Parse a single tweet page. Returns (main_tweet, replies)."""
    soup = BeautifulSoup(html, "lxml")

    main_tweet = None
    main_el = soup.select_one(".main-tweet .tweet-body")
    if main_el:
        main_tweet = parse_tweet_item(main_el, base_url)

    replies: list[Tweet] = []
    for item in soup.select(".reply .tweet-body"):
        try:
            replies.append(parse_tweet_item(item, base_url))
        except Exception:
            log.debug("Failed to parse reply item, skipping", exc_info=True)
            continue

    return main_tweet, replies


# ---------------------------------------------------------------------------
# User search results
# ---------------------------------------------------------------------------

def parse_user_search(html: str, base_url: str) -> tuple[list[UserSearchResult], str]:
    """Parse user search results page. Returns (users, cursor)."""
    soup = BeautifulSoup(html, "lxml")
    users: list[UserSearchResult] = []

    for item in soup.select(".timeline-item"):
        body = item.select_one(".tweet-body.profile-result")
        if not body:
            continue
        try:
            username = _text(body.select_one(".username")).lstrip("@")
            display_name = _text(body.select_one(".fullname"))
            avatar_el = body.select_one("img.avatar")
            avatar_url = _fix_img_url(_attr(avatar_el, "src"), base_url)
            bio = _text(body.select_one(".tweet-content"))
            verified = body.select_one(".verified-icon") is not None

            users.append(UserSearchResult(
                username=username,
                display_name=display_name,
                avatar_url=avatar_url,
                bio=bio,
                verified=verified,
            ))
        except Exception:
            log.debug("Failed to parse user search result, skipping", exc_info=True)
            continue

    # pagination cursor
    cursor = ""
    for show_more in soup.select(".show-more a"):
        href = _attr(show_more, "href")
        if "cursor=" in href:
            cursor = href.split("cursor=")[-1].split("&")[0]
            break

    return users, cursor
