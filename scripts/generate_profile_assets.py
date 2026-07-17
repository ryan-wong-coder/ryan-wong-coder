#!/usr/bin/env python3
"""Generate self-contained SVG assets for the GitHub profile README."""

from __future__ import annotations

import html
import json
import math
import os
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


USERNAME = os.getenv("PROFILE_USERNAME", "ryan-wong-coder")
TOKEN = os.getenv("GITHUB_TOKEN", "")
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ACTIVITY_LOG = ROOT / "RECENT_ACTIVITY.md"
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
EXCLUDED_REPOSITORIES = {
    "aura",
    "sandbox-control",
    "wireguard-vpn-admin-solution",
}
EXCLUDED_ACTIVITY_KEYWORDS = (
    "codex",
    "firecracker",
    "sandbox",
    "wireguard",
)


QUERY = """
query ProfileTelemetry($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    followers { totalCount }
    repositories(
      first: 100
      privacy: PUBLIC
      ownerAffiliations: OWNER
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      totalCount
      nodes {
        name
        isFork
        stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { contributionCount date }
        }
      }
    }
  }
}
"""


THEMES = {
    "dark": {
        "bg": "#070b14",
        "panel": "#0d1424",
        "panel2": "#101a2f",
        "line": "#22304a",
        "text": "#e5edf9",
        "muted": "#8da0bd",
        "grid": "#16223a",
        "blue": "#38bdf8",
        "purple": "#a78bfa",
        "green": "#34d399",
        "orange": "#fb923c",
        "pink": "#f472b6",
    },
    "light": {
        "bg": "#f8fbff",
        "panel": "#ffffff",
        "panel2": "#eff6ff",
        "line": "#d8e2f1",
        "text": "#172033",
        "muted": "#60708a",
        "grid": "#e8eef7",
        "blue": "#0284c7",
        "purple": "#7c3aed",
        "green": "#059669",
        "orange": "#ea580c",
        "pink": "#db2777",
    },
}


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def github_get(path_or_url: str) -> object:
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required")
    url = path_or_url if path_or_url.startswith("https://") else f"https://api.github.com{path_or_url}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": "github-profile-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 409, 422}:
            return {}
        raise


def graphql() -> dict:
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required")

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=364)
    payload = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": USERNAME,
                "from": start.isoformat(),
                "to": now.isoformat(),
            },
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-dashboard",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("errors"):
        raise SystemExit(json.dumps(result["errors"], indent=2))
    return result["data"]["user"]


def truncate(value: str, length: int) -> str:
    value = " ".join(value.strip().split())
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "…"


def activity_is_excluded(repository: str, title: str = "") -> bool:
    repository_name = repository.rsplit("/", 1)[-1]
    if repository_name in EXCLUDED_REPOSITORIES:
        return True
    lowered = title.lower()
    return any(keyword in lowered for keyword in EXCLUDED_ACTIVITY_KEYWORDS)


def fetch_public_events() -> list[dict]:
    events: list[dict] = []
    for page in range(1, 4):
        batch = github_get(f"/users/{USERNAME}/events/public?per_page=100&page={page}")
        if not isinstance(batch, list):
            break
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


def recent_activity(events: list[dict]) -> list[dict]:
    limits = {"commit": 5, "pr": 4, "issue": 3}
    counts = Counter()
    seen: set[tuple[str, str, str]] = set()
    items: list[dict] = []

    for event in events:
        event_type = event.get("type")
        repository = event.get("repo", {}).get("name", "")
        if not repository or activity_is_excluded(repository):
            continue
        payload = event.get("payload") or {}
        created_at = event.get("created_at") or ""

        if event_type == "PushEvent" and counts["commit"] < limits["commit"]:
            sha = payload.get("head") or ""
            if not sha or set(sha) == {"0"}:
                continue
            key = ("commit", repository, sha)
            if key in seen:
                continue
            detail = github_get(f"/repos/{repository}/commits/{sha}")
            if not isinstance(detail, dict) or not detail.get("commit"):
                continue
            title = (detail.get("commit", {}).get("message") or "").splitlines()[0]
            if not title or activity_is_excluded(repository, title):
                continue
            branch = (payload.get("ref") or "").removeprefix("refs/heads/")
            items.append(
                {
                    "kind": "commit",
                    "action": "COMMIT",
                    "created_at": created_at,
                    "repository": repository,
                    "title": title,
                    "url": detail.get("html_url") or f"https://github.com/{repository}/commit/{sha}",
                    "reference": sha[:7],
                    "context": branch,
                }
            )
            seen.add(key)
            counts["commit"] += 1
            continue

        if event_type == "PullRequestEvent" and counts["pr"] < limits["pr"]:
            number = str(payload.get("number") or payload.get("pull_request", {}).get("number") or "")
            if not number:
                continue
            key = ("pr", repository, number)
            if key in seen:
                continue
            pull_request = payload.get("pull_request") or {}
            api_url = pull_request.get("url") or f"/repos/{repository}/pulls/{number}"
            detail = github_get(api_url)
            if not isinstance(detail, dict):
                continue
            title = detail.get("title") or ""
            if not title or activity_is_excluded(repository, title):
                continue
            action = (payload.get("action") or "updated").lower()
            if action == "closed" and detail.get("merged_at"):
                action = "merged"
            items.append(
                {
                    "kind": "pr",
                    "action": f"PR {action.upper()}",
                    "created_at": created_at,
                    "repository": repository,
                    "title": title,
                    "url": detail.get("html_url") or f"https://github.com/{repository}/pull/{number}",
                    "reference": f"#{number}",
                    "context": action,
                }
            )
            seen.add(key)
            counts["pr"] += 1
            continue

        if event_type == "IssuesEvent" and counts["issue"] < limits["issue"]:
            action = (payload.get("action") or "updated").lower()
            if action not in {"opened", "closed", "reopened"}:
                continue
            issue = payload.get("issue") or {}
            number = str(issue.get("number") or "")
            title = issue.get("title") or ""
            if not number or not title or activity_is_excluded(repository, title):
                continue
            key = ("issue", repository, number)
            if key in seen:
                continue
            items.append(
                {
                    "kind": "issue",
                    "action": f"ISSUE {action.upper()}",
                    "created_at": created_at,
                    "repository": repository,
                    "title": title,
                    "url": issue.get("html_url") or f"https://github.com/{repository}/issues/{number}",
                    "reference": f"#{number}",
                    "context": action,
                }
            )
            seen.add(key)
            counts["issue"] += 1

        if all(counts[kind] >= limit for kind, limit in limits.items()):
            break

    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:12]


def month_keys(now: datetime) -> list[str]:
    year, month = now.year, now.month
    keys = []
    for offset in range(11, -1, -1):
        absolute = year * 12 + month - 1 - offset
        keys.append(f"{absolute // 12:04d}-{absolute % 12 + 1:02d}")
    return keys


def prepare(user: dict) -> dict:
    repositories = user["repositories"]["nodes"]
    original = [
        repo
        for repo in repositories
        if not repo["isFork"] and repo["name"] not in EXCLUDED_REPOSITORIES
    ]

    language_bytes: Counter[str] = Counter()
    language_colors: dict[str, str] = {}
    for repo in original:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            language_bytes[name] += edge["size"]
            language_colors[name] = edge["node"].get("color") or "#64748b"

    total_language_bytes = sum(language_bytes.values()) or 1
    top_languages = language_bytes.most_common(5)
    top_total = sum(size for _, size in top_languages)
    if total_language_bytes > top_total:
        top_languages.append(("Other", total_language_bytes - top_total))
        language_colors["Other"] = "#64748b"

    contributions = user["contributionsCollection"]
    now = datetime.now(timezone.utc)
    keys = month_keys(now)
    monthly = {key: 0 for key in keys}
    daily: list[tuple[str, int]] = []
    for week in contributions["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            daily.append((day["date"], day["contributionCount"]))
            key = day["date"][:7]
            if key in monthly:
                monthly[key] += day["contributionCount"]

    daily.sort()
    longest_streak = 0
    running_streak = 0
    for _, count in daily:
        if count > 0:
            running_streak += 1
            longest_streak = max(longest_streak, running_streak)
        else:
            running_streak = 0

    current_streak = 0
    current_days = daily[:]
    if current_days and current_days[-1][1] == 0:
        current_days.pop()
    for _, count in reversed(current_days):
        if count <= 0:
            break
        current_streak += 1

    return {
        "followers": user["followers"]["totalCount"],
        "public_repos": user["repositories"]["totalCount"],
        "original_repos": len(original),
        "stars": sum(repo["stargazerCount"] for repo in original),
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "commits": contributions["totalCommitContributions"],
        "pull_requests": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
        "reviews": contributions["totalPullRequestReviewContributions"],
        "private": contributions["restrictedContributionsCount"],
        "languages": top_languages,
        "language_colors": language_colors,
        "language_total": total_language_bytes,
        "monthly": list(monthly.items()),
        "updated": now.strftime("%Y-%m-%d %H:%M UTC"),
    }


def arc_path(cx: float, cy: float, outer: float, inner: float, start: float, end: float) -> str:
    start_outer = (cx + outer * math.cos(start), cy + outer * math.sin(start))
    end_outer = (cx + outer * math.cos(end), cy + outer * math.sin(end))
    start_inner = (cx + inner * math.cos(end), cy + inner * math.sin(end))
    end_inner = (cx + inner * math.cos(start), cy + inner * math.sin(start))
    large = 1 if end - start > math.pi else 0
    return (
        f"M {start_outer[0]:.2f} {start_outer[1]:.2f} "
        f"A {outer} {outer} 0 {large} 1 {end_outer[0]:.2f} {end_outer[1]:.2f} "
        f"L {start_inner[0]:.2f} {start_inner[1]:.2f} "
        f"A {inner} {inner} 0 {large} 0 {end_inner[0]:.2f} {end_inner[1]:.2f} Z"
    )


def text(x: float, y: float, value: object, size: int, color: str, weight: int = 400, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def dashboard_svg(data: dict, mode: str) -> str:
    c = THEMES[mode]
    width, height = 1200, 650
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(USERNAME)} engineering telemetry</title>',
        '<desc id="desc">Public repository, star, follower, annual contribution, language and monthly activity data generated from GitHub.</desc>',
        "<defs>",
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{c["bg"]}"/><stop offset="1" stop-color="{c["panel2"]}"/></linearGradient>',
        f'<linearGradient id="signal" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{c["blue"]}"/><stop offset=".52" stop-color="{c["purple"]}"/><stop offset="1" stop-color="{c["pink"]}"/></linearGradient>',
        f'<pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M 28 0 L 0 0 0 28" fill="none" stroke="{c["grid"]}" stroke-width="1"/></pattern>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}</style>',
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="22" fill="url(#bg)"/>',
        f'<rect width="{width}" height="{height}" rx="22" fill="url(#grid)" opacity=".62"/>',
        f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="21" fill="none" stroke="{c["line"]}"/>',
        text(34, 44, "ENGINEERING TELEMETRY // ROLLING 12 MONTHS", 17, c["blue"], 700),
        text(1166, 44, data["updated"], 13, c["muted"], 400, "end"),
    ]

    stats = [
        ("PUBLIC REPOS", data["public_repos"], "all visible repositories"),
        ("STARS EARNED", data["stars"], "curated original work"),
        ("FOLLOWERS", data["followers"], "GitHub network"),
        ("CONTRIBUTIONS", data["contributions"], "rolling 12 months"),
        ("CURRENT STREAK", data["current_streak"], f'longest {data["longest_streak"]} days'),
    ]
    card_w, card_gap, x0, y0 = 213, 18, 34, 70
    for index, (label, value, note) in enumerate(stats):
        x = x0 + index * (card_w + card_gap)
        parts.extend(
            [
                f'<rect x="{x}" y="{y0}" width="{card_w}" height="108" rx="14" fill="{c["panel"]}" stroke="{c["line"]}"/>',
                text(x + 18, y0 + 29, label, 12, c["muted"], 700),
                text(x + 18, y0 + 72, value, 31, c["text"], 700),
                text(x + 18, y0 + 94, note, 11, c["muted"]),
            ]
        )

    # Language donut and legend.
    lx, ly, lw, lh = 34, 202, 455, 414
    parts.extend(
        [
            f'<rect x="{lx}" y="{ly}" width="{lw}" height="{lh}" rx="16" fill="{c["panel"]}" stroke="{c["line"]}"/>',
            text(lx + 22, ly + 34, "PROFILE CODEBASE", 14, c["text"], 700),
            text(lx + 22, ly + 55, "curated language share by repository bytes", 11, c["muted"]),
        ]
    )
    cx, cy, outer, inner = lx + 142, ly + 215, 91, 59
    cursor = -math.pi / 2
    palette = [c["blue"], c["purple"], c["green"], c["orange"], c["pink"], "#64748b"]
    for index, (name, size) in enumerate(data["languages"]):
        angle = (size / data["language_total"]) * math.tau
        end = cursor + angle
        if angle > 0.005:
            parts.append(f'<path d="{arc_path(cx, cy, outer, inner, cursor, end)}" fill="{palette[index % len(palette)]}"/>')
        cursor = end
    parts.append(text(cx, cy - 2, len(data["languages"]), 27, c["text"], 700, "middle"))
    parts.append(text(cx, cy + 21, "LANG GROUPS", 10, c["muted"], 700, "middle"))

    legend_x, legend_y = lx + 265, ly + 105
    for index, (name, size) in enumerate(data["languages"]):
        y = legend_y + index * 43
        percent = size / data["language_total"] * 100
        color = palette[index % len(palette)]
        parts.extend(
            [
                f'<rect x="{legend_x}" y="{y-11}" width="10" height="10" rx="2" fill="{color}"/>',
                text(legend_x + 20, y - 2, name, 13, c["text"], 700),
                text(lx + lw - 22, y - 2, f"{percent:.1f}%", 13, c["muted"], 400, "end"),
            ]
        )

    # Monthly contributions chart.
    rx, ry, rw, rh = 510, 202, 656, 255
    parts.extend(
        [
            f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="16" fill="{c["panel"]}" stroke="{c["line"]}"/>',
            text(rx + 22, ry + 34, "CONTRIBUTION PULSE", 14, c["text"], 700),
            text(rx + 22, ry + 55, "contributions grouped by month", 11, c["muted"]),
        ]
    )
    chart_x, chart_y, chart_w, chart_h = rx + 24, ry + 82, rw - 48, 135
    max_month = max((value for _, value in data["monthly"]), default=1) or 1
    gap = 8
    bar_w = (chart_w - gap * 11) / 12
    for index, (key, value) in enumerate(data["monthly"]):
        height_value = max(2, value / max_month * chart_h)
        x = chart_x + index * (bar_w + gap)
        y = chart_y + chart_h - height_value
        parts.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{height_value:.1f}" rx="4" fill="url(#signal)" opacity="{0.55 + 0.45 * (value / max_month):.2f}"/>',
                text(x + bar_w / 2, chart_y + chart_h + 20, key[5:], 10, c["muted"], 400, "middle"),
            ]
        )
        if value == max_month or (value > 0 and index == len(data["monthly"]) - 1):
            parts.append(text(x + bar_w / 2, y - 7, value, 10, c["text"], 700, "middle"))

    # Contribution mix.
    mx, my, mw, mh = 510, 477, 656, 139
    parts.extend(
        [
            f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="16" fill="{c["panel"]}" stroke="{c["line"]}"/>',
            text(mx + 22, my + 31, "CONTRIBUTION MIX", 14, c["text"], 700),
        ]
    )
    mix = [
        ("COMMITS", data["commits"], c["blue"]),
        ("PULL REQUESTS", data["pull_requests"], c["purple"]),
        ("ISSUES", data["issues"], c["orange"]),
        ("REVIEWS", data["reviews"], c["green"]),
    ]
    max_mix = max((value for _, value, _ in mix), default=1) or 1
    for index, (label, value, color) in enumerate(mix):
        x = mx + 22 + (index % 2) * 317
        y = my + 58 + (index // 2) * 39
        bar_x, bar_w2 = x + 118, 150
        parts.extend(
            [
                text(x, y + 4, label, 10, c["muted"], 700),
                f'<rect x="{bar_x}" y="{y-7}" width="{bar_w2}" height="11" rx="5.5" fill="{c["panel2"]}"/>',
                f'<rect x="{bar_x}" y="{y-7}" width="{max(3, bar_w2 * value / max_mix):.1f}" height="11" rx="5.5" fill="{color}"/>',
                text(x + 298, y + 4, value, 11, c["text"], 700, "end"),
            ]
        )

    parts.append("</svg>")
    return "".join(parts)


def parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(LOCAL_TIMEZONE)


def timeline_svg(items: list[dict], mode: str) -> str:
    c = THEMES[mode]
    width = 1200
    row_height = 82
    height = max(280, 116 + row_height * len(items))
    line_x = 190
    colors = {"commit": c["blue"], "pr": c["purple"], "issue": c["orange"]}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(USERNAME)} recent GitHub activity timeline</title>',
        '<desc id="desc">A chronological timeline of recent public commits, pull requests, and issues.</desc>',
        "<defs>",
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{c["bg"]}"/><stop offset="1" stop-color="{c["panel2"]}"/></linearGradient>',
        f'<pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="{c["grid"]}" stroke-width="1"/></pattern>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}</style>',
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="22" fill="url(#bg)"/>',
        f'<rect width="{width}" height="{height}" rx="22" fill="url(#grid)" opacity=".62"/>',
        f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="21" fill="none" stroke="{c["line"]}"/>',
        text(34, 43, "RECENT ACTIVITY // UTC+8", 17, c["blue"], 700),
        text(1166, 43, datetime.now(timezone.utc).strftime("REFRESHED %Y-%m-%d %H:%M UTC"), 12, c["muted"], 400, "end"),
    ]

    legend = [("commit", "COMMIT"), ("pr", "PULL REQUEST"), ("issue", "ISSUE")]
    legend_x = 34
    for kind, label in legend:
        color = colors[kind]
        parts.extend(
            [
                f'<circle cx="{legend_x+6}" cy="70" r="5" fill="{color}"/>',
                text(legend_x + 18, 74, label, 11, c["muted"], 700),
            ]
        )
        legend_x += 118 if kind != "pr" else 155

    if not items:
        parts.extend(
            [
                f'<line x1="{line_x}" y1="104" x2="{line_x}" y2="226" stroke="{c["line"]}" stroke-width="2"/>',
                f'<circle cx="{line_x}" cy="165" r="7" fill="{c["panel"]}" stroke="{c["muted"]}" stroke-width="2"/>',
                text(226, 159, "NO RECENT PUBLIC ACTIVITY", 16, c["text"], 700),
                text(226, 184, "The next scheduled refresh will check again.", 12, c["muted"]),
            ]
        )
        parts.append("</svg>")
        return "".join(parts)

    first_y = 112
    last_y = first_y + (len(items) - 1) * row_height
    parts.append(f'<line x1="{line_x}" y1="{first_y}" x2="{line_x}" y2="{last_y}" stroke="{c["line"]}" stroke-width="3"/>')

    for index, item in enumerate(items):
        event_time = parse_event_time(item["created_at"])
        y = first_y + index * row_height
        kind = item["kind"]
        color = colors[kind]
        action = item["action"]
        tag_width = max(92, 22 + len(action) * 7.2)

        parts.extend(
            [
                text(34, y - 5, event_time.strftime("%b %d").upper(), 13, c["text"], 700),
                text(34, y + 16, event_time.strftime("%H:%M"), 11, c["muted"]),
            ]
        )

        if kind == "commit":
            parts.append(f'<circle cx="{line_x}" cy="{y}" r="8" fill="{color}" stroke="{c["bg"]}" stroke-width="4"/>')
        elif kind == "pr":
            parts.append(f'<rect x="{line_x-7}" y="{y-7}" width="14" height="14" rx="2" fill="{color}" stroke="{c["bg"]}" stroke-width="3" transform="rotate(45 {line_x} {y})"/>')
        else:
            parts.append(f'<rect x="{line_x-7}" y="{y-7}" width="14" height="14" rx="3" fill="{color}" stroke="{c["bg"]}" stroke-width="3"/>')

        parts.extend(
            [
                f'<rect x="224" y="{y-22}" width="{tag_width:.1f}" height="25" rx="12.5" fill="{color}" opacity=".16"/>',
                text(224 + tag_width / 2, y - 5, action, 10, color, 700, "middle"),
                text(224 + tag_width + 18, y - 5, truncate(item["title"], 82), 15, c["text"], 700),
                text(224, y + 22, f'{item["repository"]}  ·  {item["reference"]}  ·  {truncate(item["context"], 34)}', 11, c["muted"]),
            ]
        )
        if index < len(items) - 1:
            parts.append(f'<line x1="224" y1="{y+39}" x2="1164" y2="{y+39}" stroke="{c["line"]}"/>')

    parts.append("</svg>")
    return "".join(parts)


def activity_markdown(items: list[dict]) -> str:
    lines = [
        "# Recent public GitHub activity",
        "",
        "> Automatically generated from GitHub's public Events API. Times use Asia/Shanghai (UTC+8).",
        "",
        "| Time | Type | Repository | Activity |",
        "| --- | --- | --- | --- |",
    ]
    for item in items:
        event_time = parse_event_time(item["created_at"]).strftime("%Y-%m-%d %H:%M")
        title = (
            item["title"]
            .replace("|", "\\|")
            .replace("[", "\\[")
            .replace("]", "\\]")
        )
        repository = item["repository"].replace("|", "\\|")
        lines.append(
            f'| {event_time} | `{item["action"]}` | [{repository}](https://github.com/{repository}) | [{title}]({item["url"]}) |'
        )
    lines.extend(
        [
            "",
            f'_Last refreshed: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}_',
            "",
        ]
    )
    return "\n".join(lines)


def header_svg(mode: str) -> str:
    c = THEMES[mode]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="300" viewBox="0 0 1200 300" role="img" aria-labelledby="title desc">
<title id="title">Ryan systems lab</title>
<desc id="desc">Backend, distributed systems and developer tools.</desc>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{c['bg']}"/><stop offset="1" stop-color="{c['panel2']}"/></linearGradient>
  <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{c['blue']}"/><stop offset=".5" stop-color="{c['purple']}"/><stop offset="1" stop-color="{c['pink']}"/></linearGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="{c['grid']}" stroke-width="1"/></pattern>
  <filter id="glow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <style>text{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}}</style>
</defs>
<rect width="1200" height="300" rx="24" fill="url(#bg)"/>
<rect width="1200" height="300" rx="24" fill="url(#grid)" opacity=".76"/>
<rect x="1" y="1" width="1198" height="298" rx="23" fill="none" stroke="{c['line']}"/>
<circle cx="1010" cy="150" r="105" fill="none" stroke="{c['line']}"/>
<circle cx="1010" cy="150" r="72" fill="none" stroke="{c['line']}" stroke-dasharray="7 9"/>
<path d="M905 150H1115M1010 45V255" stroke="{c['line']}"/>
<path d="M926 181C951 181 950 111 975 111S999 209 1024 209s25-118 50-118 24 59 49 59" fill="none" stroke="url(#beam)" stroke-width="5" stroke-linecap="round" filter="url(#glow)"/>
<rect x="56" y="52" width="162" height="28" rx="14" fill="{c['panel']}" stroke="{c['line']}"/>
<circle cx="76" cy="66" r="5" fill="{c['green']}"/>
<text x="91" y="71" fill="{c['muted']}" font-size="12" font-weight="700">SYSTEMS ONLINE</text>
<text x="56" y="137" fill="{c['text']}" font-size="50" font-weight="700">RYAN // SYSTEMS LAB</text>
<rect x="56" y="160" width="704" height="5" rx="2.5" fill="url(#beam)"/>
<text x="56" y="204" fill="{c['muted']}" font-size="18">BACKEND · DISTRIBUTED SYSTEMS · DEVELOPER TOOLS</text>
<text x="56" y="244" fill="{c['blue']}" font-size="14">JAVA</text><text x="112" y="244" fill="{c['line']}" font-size="14">/</text>
<text x="132" y="244" fill="{c['purple']}" font-size="14">GO</text><text x="164" y="244" fill="{c['line']}" font-size="14">/</text>
<text x="184" y="244" fill="{c['green']}" font-size="14">RUST</text><text x="226" y="244" fill="{c['line']}" font-size="14">/</text>
<text x="246" y="244" fill="{c['orange']}" font-size="14">PYTHON</text>
</svg>'''


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = prepare(graphql())
    activity = recent_activity(fetch_public_events())
    for mode in ("dark", "light"):
        (ASSETS / f"header-{mode}.svg").write_text(header_svg(mode), encoding="utf-8")
        (ASSETS / f"dashboard-{mode}.svg").write_text(dashboard_svg(data, mode), encoding="utf-8")
        (ASSETS / f"activity-timeline-{mode}.svg").write_text(timeline_svg(activity, mode), encoding="utf-8")
    ACTIVITY_LOG.write_text(activity_markdown(activity), encoding="utf-8")
    print(
        json.dumps(
            {
                "user": USERNAME,
                "public_repos": data["public_repos"],
                "original_repos": data["original_repos"],
                "stars": data["stars"],
                "contributions": data["contributions"],
                "current_streak": data["current_streak"],
                "longest_streak": data["longest_streak"],
                "languages": [name for name, _ in data["languages"]],
                "activity_items": len(activity),
                "activity_mix": dict(Counter(item["kind"] for item in activity)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
