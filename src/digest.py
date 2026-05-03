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
# Top stories: 3-4 with paragraph summaries; remaining items: unlimited additional links


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


# ─── Step 2: Summarize with Claude ──────────────────────────────────────────

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

ACTION FLAG CRITERIA — set action_flag to true if ANY of these apply:
- A comment period, application deadline, or congressional hearing is within 14 days
- A funding opportunity has been announced or is closing soon
- An executive order or agency rule takes effect imminently
- Congressional testimony or a markup is scheduled this week
- An injunction, court ruling, or legal deadline requires immediate organizational response
- A grant termination or funding freeze directly affects the research community now

Your output must be a JSON object with this exact structure:
{{
  "headline": "A single punchy 10-word headline summarizing today's most important story",
  "date": "Today's date in Month Day, Year format",
  "one_liner": "A single sentence summarizing the overall policy environment today",
  "top_stories": [
    {{
      "rank": 1,
      "title": "Descriptive story title, no word limit",
      "paragraph": "A tight ~100-word summary written for easy skimming. Use plain, direct sentences. Cover: what happened, why it matters, and what comes next. No jargon. No long wind-ups. Get to the point immediately.",
      "action_flag": true or false,
      "action_reason": "If action_flag is true, one sentence explaining exactly what action is needed and by when. If false, leave as empty string.",
      "source": "Publication or agency name",
      "url": "Full absolute URL starting with https:// — REQUIRED, do not omit"
    }}
  ],
  "additional_links": [
    {{
      "title": "Story headline",
      "one_sentence": "One sentence describing what happened and why it matters.",
      "action_flag": true or false,
      "source": "Publication or agency name",
      "url": "Full absolute URL starting with https:// — REQUIRED, do not omit"
    }}
  ]
}}

Select 3-4 items for top_stories. Include ALL remaining items as additional_links — 
do not limit the number of additional links. Every single item must have a real, 
working URL — never omit the url field or leave it blank.
Return ONLY valid JSON, no markdown, no preamble."""


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
        max_tokens=8000,
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

    print(f"  ✅ Claude returned {len(digest.get('top_stories') or [])} top stories + {len(digest.get('additional_links') or [])} additional links")
    return digest


# ─── Step 3: Format HTML Email ────────────────────────────────────────────────

ACTION_CRITERIA_HTML = """
<tr>
  <td style="padding:16px 36px 20px;background:#f9fafb;border-top:1px solid #e5e7eb;">
    <div style="background:#fefce8;border:1px solid #fde68a;border-radius:6px;
                padding:14px 18px;">
      <div style="font-size:11px;font-weight:700;color:#92400e;
                  text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">
        &#9889; Action Flag Criteria
      </div>
      <div style="font-size:12px;color:#78350f;line-height:1.7;">
        A story is flagged for action when one or more of the following apply:
        a comment period, application deadline, or hearing falls within 14 days;
        a funding opportunity has been announced or is closing soon;
        an executive order or agency rule takes effect imminently;
        congressional testimony or a markup is scheduled this week;
        a court ruling or legal deadline requires immediate organizational response; or
        a grant termination or funding freeze directly affects the research community now.
      </div>
    </div>
  </td>
</tr>"""


def _action_badge_html(story: dict) -> str:
    """Return action badge + reason as a block-level element (never inline)."""
    if not story.get("action_flag"):
        return ""
    reason = escape(story.get("action_reason") or "")
    badge = (
        '<div style="margin-top:8px;">'
        '<span style="display:inline-block;background:#b91c1c;color:#fff;'
        'font-size:10px;font-weight:700;padding:3px 10px;border-radius:4px;'
        'text-transform:uppercase;letter-spacing:0.06em;">&#9889; Action Needed</span>'
    )
    if reason:
        badge += (
            f'<span style="font-size:12px;color:#b91c1c;margin-left:8px;'
            f'font-style:italic;">{reason}</span>'
        )
    badge += "</div>"
    return badge


def _story_url_html(url: str, label: str = "Read more &#8594;") -> str:
    """Return a source link, or empty string if URL is missing/invalid."""
    if not url or not url.startswith("http"):
        return ""
    return (
        f'<a href="{escape(url)}" style="font-size:12px;color:#2563eb;'
        f'text-decoration:none;font-weight:600;">{escape(label)}</a>'
    )


def build_email_html(digest: dict) -> str:
    """Render the digest as a clean HTML email."""

    one_liner = escape(digest.get("one_liner") or "")
    headline  = escape(digest.get("headline")  or "Science Policy Daily Digest")
    date_str  = escape(digest.get("date")      or datetime.now().strftime("%B %d, %Y"))

    # ── Top Stories (paragraph summaries) ──────────────────────────────────────
    top_stories_html = ""
    for story in (digest.get("top_stories") or []):
        url    = story.get("url") or ""
        if not url.startswith("http"):
            url = ""
        title  = story.get("title") or "Untitled"
        source = story.get("source") or ""
        rank   = str(story.get("rank") or "")
        para   = story.get("paragraph") or ""

        title_linked = (
            f'<a href="{escape(url)}" style="color:#1e3a5f;text-decoration:none;">'
            f'{escape(title)}</a>'
            if url else escape(title)
        )

        top_stories_html += f"""
        <tr>
          <td style="padding:20px 0;border-bottom:2px solid #e5e7eb;">
            <div style="font-size:11px;color:#6b7280;text-transform:uppercase;
                        letter-spacing:0.08em;font-weight:600;margin-bottom:6px;">
              Top Story #{rank} · {escape(source)}
            </div>
            <div style="font-size:17px;font-weight:800;color:#1e3a5f;
                        line-height:1.4;margin-bottom:10px;">
              {title_linked}
            </div>
            <div style="font-size:14px;color:#374151;line-height:1.75;
                        margin-bottom:10px;">
              {escape(para)}
            </div>
            <div style="margin-bottom:10px;">
              {_story_url_html(url)}
            </div>
            {_action_badge_html(story)}
          </td>
        </tr>"""

    # ── Additional Links ────────────────────────────────────────────────────────
    additional_html = ""
    for link in (digest.get("additional_links") or []):
        url      = link.get("url") or ""
        if not url.startswith("http"):
            url = ""
        title    = link.get("title") or "Untitled"
        one_sent = link.get("one_sentence") or ""
        source   = link.get("source") or ""
        is_action = bool(link.get("action_flag"))

        action_dot = (
            '<span style="display:inline-block;width:8px;height:8px;'
            'background:#b91c1c;border-radius:50%;margin-right:6px;'
            'vertical-align:middle;" title="Action needed"></span>'
            if is_action else
            '<span style="display:inline-block;width:8px;height:8px;'
            'background:#d1d5db;border-radius:50%;margin-right:6px;'
            'vertical-align:middle;"></span>'
        )

        title_linked = (
            f'<a href="{escape(url)}" style="color:#1e40af;text-decoration:none;'
            f'font-weight:600;font-size:13px;">{escape(title)}</a>'
            if url else
            f'<span style="color:#1e40af;font-weight:600;font-size:13px;">'
            f'{escape(title)}</span>'
        )

        additional_html += f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="16" style="vertical-align:top;padding-top:3px;">
                  {action_dot}
                </td>
                <td style="vertical-align:top;">
                  {title_linked}
                  <span style="font-size:11px;color:#9ca3af;margin-left:6px;">
                    {escape(source)}
                  </span>
                  <div style="font-size:12px;color:#6b7280;line-height:1.5;
                              margin-top:3px;">
                    {escape(one_sent)}
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Legend for additional links ─────────────────────────────────────────────
    legend_html = """
    <tr>
      <td style="padding:10px 0 4px;">
        <span style="font-size:11px;color:#6b7280;">
          <span style="display:inline-block;width:8px;height:8px;background:#b91c1c;
                border-radius:50%;margin-right:4px;vertical-align:middle;"></span>
          Action needed &nbsp;&nbsp;
          <span style="display:inline-block;width:8px;height:8px;background:#d1d5db;
                border-radius:50%;margin-right:4px;vertical-align:middle;"></span>
          For awareness
        </span>
      </td>
    </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Science Policy Digest</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;
             font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f3f4f6;padding:32px 0;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
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
          <td style="background:#eff6ff;padding:14px 36px;
                     border-bottom:1px solid #dbeafe;">
            <div style="font-size:13px;color:#1e40af;line-height:1.5;
                        font-style:italic;">
              {one_liner}
            </div>
          </td>
        </tr>

        <!-- Top Stories header -->
        <tr>
          <td style="padding:4px 36px 0;">
            <div style="font-size:13px;font-weight:700;color:#1e3a5f;
                        text-transform:uppercase;letter-spacing:0.1em;
                        border-bottom:3px solid #1e3a5f;padding-bottom:6px;">
              Top Stories
            </div>
          </td>
        </tr>

        <!-- Top Stories -->
        <tr>
          <td style="padding:0 36px 8px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              {top_stories_html}
            </table>
          </td>
        </tr>

        <!-- Additional Links header -->
        {'<tr><td style="padding:20px 36px 0;background:#f9fafb;border-top:2px solid #e5e7eb;"><div style="font-size:13px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.1em;border-bottom:2px solid #d1d5db;padding-bottom:6px;">Additional Links</div></td></tr><tr><td style="padding:0 36px 16px;background:#f9fafb;"><table width="100%" cellpadding="0" cellspacing="0">' + legend_html + additional_html + '</table></td></tr>' if additional_html.strip() else ''}

        <!-- Action Flag Criteria -->
        {ACTION_CRITERIA_HTML}

        <!-- Footer -->
        <tr>
          <td style="background:#f3f4f6;padding:16px 36px;
                     border-top:1px solid #e5e7eb;">
            <div style="font-size:11px;color:#9ca3af;line-height:1.6;">
              Science Policy Digest · Powered by Claude &amp; curated RSS feeds ·
              To update sources or delivery time, edit
              <code>src/digest.py</code>
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

    raw_headline = digest.get('headline') or 'Daily Digest'
    if len(raw_headline) > 80:
        raw_headline = raw_headline[:77] + "..."
    subject = (
        f"[Science Policy] {raw_headline} · "
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
