"""
Science Policy Daily Digest
Fetches RSS feeds, summarizes with Claude, sends via SendGrid.
"""

import os
import re
import sys
import json
import feedparser
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from datetime import datetime, timezone
from html import escape

# ─── Configuration ────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # Science Policy Organizations
    {"name": "Federation of American Scientists", "url": "https://fas.org/feed/"},
    {"name": "AAAS Policy",                       "url": "https://www.aaas.org/taxonomy/term/13/feed"},
    {"name": "AAU News",                           "url": "https://www.aau.edu/rss.xml"},
    {"name": "COGR News",                          "url": "https://www.cogr.edu/news/feed"},
    {"name": "Research!America",                   "url": "https://www.researchamerica.org/feed/"},

    # Science Journals & News
    {"name": "Nature News",                        "url": "https://www.nature.com/nature.rss"},
    {"name": "Science Magazine News",              "url": "https://www.science.org/rss/news_current.xml"},
    {"name": "Science Insider",                    "url": "https://www.science.org/rss/scienceinsider.xml"},

    # Policy & Government
    {"name": "Politico Science",                   "url": "https://www.politico.com/rss/politicopicks.xml"},
    {"name": "The Hill Science",                   "url": "https://thehill.com/policy/technology/feed/"},

    # Agency Newsrooms
    {"name": "NSF News",                           "url": "https://www.nsf.gov/rss/rss_www_news.xml"},
    {"name": "NIH News",                           "url": "https://www.nih.gov/news-events/feed.xml"},
    {"name": "DOE Science News",                   "url": "https://www.energy.gov/science/rss.xml"},
    {"name": "NASA News",                          "url": "https://www.nasa.gov/news-release/feed/"},
    {"name": "NOAA News",                          "url": "https://www.noaa.gov/media-release/feed"},
    {"name": "NIST News",                          "url": "https://www.nist.gov/news-events/feed"},

    # Congress
    {"name": "House Science Committee",            "url": "https://science.house.gov/rss/news.xml"},
]

MAX_ITEMS_PER_FEED = 5       # Items to pull per feed
MAX_ITEMS_TOTAL    = 60      # Cap before sending to Claude
MAX_DIGEST_ITEMS   = 8       # Stories in the final email


# ─── Step 1: Fetch RSS Feeds ──────────────────────────────────────────────────

def fetch_feeds(feeds: list[dict]) -> list[dict]:
    """Pull recent items from all RSS feeds."""
    items = []
    for feed_meta in feeds:
        try:
            parsed = feedparser.parse(feed_meta["url"])
            for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
                summary = entry.get("summary", "") or ""
                # Strip HTML tags and normalise whitespace
                summary = re.sub(r"<[^>]+>", " ", summary)
                words = summary.split()
                summary = " ".join(words[:120])  # ~600 chars, but word-safe

                items.append({
                    "source":  feed_meta["name"],
                    "title":   entry.get("title", "No title"),
                    "link":    entry.get("link", ""),
                    "summary": summary,
                    "date":    entry.get("published", entry.get("updated", "")),
                })
        except Exception as e:
            print(f"  ⚠️  Could not fetch {feed_meta['name']}: {e}")

    print(f"  ✅ Fetched {len(items)} items from {len(feeds)} feeds")
    return items[:MAX_ITEMS_TOTAL]


# ─── Step 2: Summarize with Claude ────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a senior science policy analyst briefing a senior leader 
at a science policy organization. Your job is to identify the most consequential 
developments of the day across the U.S. science, technology, and innovation policy 
landscape — with particular focus on:

- Federal research funding (NSF, NIH, DOE, NOAA, NASA, USDA, NIST)
- Congressional oversight, hearings, and legislation
- OMB, executive orders, and administration policy actions
- University and academic research policy
- Indirect cost rates, grantmaking reforms, and contracting
- Science workforce and talent policy
- AI, quantum, and emerging technology policy
- Agency reorganizations and structural changes

Your output must be a JSON object with this exact structure:
{{
  "headline": "A single punchy 10-word headline summarizing today's most important story",
  "date": "Today's date in Month Day, Year format",
  "stories": [
    {{
      "rank": 1,
      "title": "Short story title (8 words max)",
      "why_it_matters": "2-3 sentences explaining significance for science policy professionals",
      "action_flag": true or false (true if requires immediate attention or action),
      "source": "Source name",
      "url": "URL if available"
    }}
  ],
  "one_liner": "A single sentence summarizing the overall policy environment today"
}}

Select the {MAX_DIGEST_ITEMS} most important and actionable stories. Prioritize 
time-sensitive items, congressional actions, funding decisions, and executive 
branch moves. Return ONLY valid JSON, no markdown, no preamble."""


def summarize_with_claude(items: list[dict]) -> dict:
    """Send feed items to Claude and get structured digest back."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Format items for the prompt
    feed_text = ""
    for i, item in enumerate(items, 1):
        feed_text += f"\n[{i}] SOURCE: {item['source']}\n"
        feed_text += f"    TITLE: {item['title']}\n"
        feed_text += f"    DATE: {item['date']}\n"
        feed_text += f"    URL: {item['link']}\n"
        if item["summary"]:
            feed_text += f"    SUMMARY: {item['summary']}\n"

    user_prompt = f"""Today is {datetime.now(timezone.utc).strftime('%B %d, %Y')}.

Here are today's science policy news items from across your monitored sources:

{feed_text}

Analyze these items and return your structured JSON digest of the most important 
stories for a senior science policy leader."""

    print("  🤖 Sending to Claude for analysis...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences robustly (handles ```json, ``` json, ``` etc.)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()

    try:
        digest = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ❌ Claude returned invalid JSON: {e}\n  Raw output:\n{raw[:500]}")
        sys.exit(1)
    print(f"  ✅ Claude returned {len(digest.get('stories', []))} stories")
    return digest


# ─── Step 3: Format HTML Email ────────────────────────────────────────────────

def build_email_html(digest: dict) -> str:
    """Render the digest as a clean HTML email."""

    stories_html = ""
    for story in digest.get("stories", []):
        action_badge = ""
        if story.get("action_flag"):
            action_badge = (
                '<span style="background:#b91c1c;color:#fff;'
                'font-size:10px;font-weight:700;padding:2px 8px;'
                'border-radius:999px;margin-left:8px;'
                'text-transform:uppercase;letter-spacing:0.05em;">'
                '⚡ Action Needed</span>'
            )

        url        = story.get("url") or ""
        # Only use URL as a link if it looks like a real absolute URL
        if not url.startswith("http"):
            url = ""
        title      = story.get("title", "Untitled")
        source     = story.get("source", "")
        rank       = story.get("rank", "")
        why        = story.get("why_it_matters", "")
        title_html = (
            f'<a href="{escape(url)}" style="color:#1e3a5f;text-decoration:none;">'
            f'{escape(title)}</a>'
            if url else escape(title)
        )

        stories_html += f"""
        <tr>
          <td style="padding:16px 0;border-bottom:1px solid #e5e7eb;">
            <div style="font-size:11px;color:#6b7280;text-transform:uppercase;
                        letter-spacing:0.08em;font-weight:600;margin-bottom:4px;">
              #{rank} · {escape(source)}
            </div>
            <div style="font-size:16px;font-weight:700;color:#1e3a5f;
                        margin-bottom:6px;line-height:1.35;">
              {title_html}{action_badge}
            </div>
            <div style="font-size:14px;color:#374151;line-height:1.6;">
              {escape(why)}
            </div>
          </td>
        </tr>"""

    one_liner = escape(digest.get("one_liner", ""))
    headline  = escape(digest.get("headline",  "Science Policy Daily Digest"))
    date_str  = escape(digest.get("date", datetime.now().strftime("%B %d, %Y")))

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 0;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 1px 4px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:#1e3a5f;padding:28px 36px;">
            <div style="font-size:11px;color:#93c5fd;text-transform:uppercase;
                        letter-spacing:0.12em;font-weight:600;margin-bottom:6px;">
              Science &amp; Technology Policy · {date_str}
            </div>
            <div style="font-size:22px;font-weight:800;color:#fff;line-height:1.3;">
              {headline}
            </div>
          </td>
        </tr>

        <!-- One-liner -->
        <tr>
          <td style="background:#eff6ff;padding:14px 36px;border-bottom:1px solid #dbeafe;">
            <div style="font-size:13px;color:#1e40af;line-height:1.5;font-style:italic;">
              {one_liner}
            </div>
          </td>
        </tr>

        <!-- Stories -->
        <tr>
          <td style="padding:4px 36px 8px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              {stories_html}
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:20px 36px;
                     border-top:1px solid #e5e7eb;">
            <div style="font-size:11px;color:#9ca3af;line-height:1.6;">
              Generated daily by your Science Policy Digest · 
              Powered by Claude &amp; curated RSS feeds ·
              To update sources or frequency, edit <code>src/digest.py</code>
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ─── Step 4: Send via SendGrid ────────────────────────────────────────────────

def send_email(html: str, digest: dict):
    """Send the formatted digest via SendGrid."""
    sg = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])

    subject = (
        f"[Science Policy] {digest.get('headline', 'Daily Digest')} · "
        f"{datetime.now().strftime('%b %d')}"
    )

    message = Mail(
        from_email=os.environ["FROM_EMAIL"],
        to_emails=os.environ["TO_EMAIL"],
        subject=subject,
        html_content=html,
    )

    try:
        response = sg.send(message)
        print(f"  ✅ Email sent — status {response.status_code}")
    except Exception as e:
        print(f"  ❌ SendGrid error: {e}")
        sys.exit(1)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n🔭 Science Policy Digest — starting run")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Validate required environment variables up front
    required = ["ANTHROPIC_API_KEY", "SENDGRID_API_KEY", "FROM_EMAIL", "TO_EMAIL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    print("📡 Fetching RSS feeds...")
    items = fetch_feeds(RSS_FEEDS)

    if not items:
        print("❌ No items fetched — aborting.")
        sys.exit(1)

    print("\n🤖 Summarizing with Claude...")
    digest = summarize_with_claude(items)

    print("\n📧 Building and sending email...")
    html = build_email_html(digest)
    send_email(html, digest)

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
