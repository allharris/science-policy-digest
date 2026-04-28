# 🔭 Science Policy Daily Digest

A fully automated daily email briefing on U.S. science, technology, and 
innovation policy — powered by Claude AI and delivered to your inbox every 
weekday morning.

---

## What It Does

Every weekday at 7 AM Eastern, this tool:

1. **Fetches** the latest items from 17 curated RSS feeds across science 
   agencies, policy organizations, journals, and Congress
2. **Analyzes** them with Claude, which identifies the 6–8 most consequential 
   stories for science policy professionals
3. **Emails** you a clean, formatted digest with summaries, significance 
   explanations, and ⚡ action flags for time-sensitive items

**Monitored sources include:** FAS, AAAS, AAU, COGR, NSF, NIH, DOE, NOAA, 
NASA, NIST, Nature, Science, Politico, The Hill, House Science Committee, 
and more.

---

## Setup: 4 Steps, ~20 Minutes

### Step 1 — Get Your API Keys

You need three free accounts:

**A) Anthropic API Key**
- Go to [console.anthropic.com](https://console.anthropic.com)
- Create an account → API Keys → Create Key
- Copy the key (starts with `sk-ant-...`)
- Cost: ~$0.01–0.05/day at Claude Sonnet pricing

**B) SendGrid API Key** (free tier: 100 emails/day)
- Go to [sendgrid.com](https://sendgrid.com) → sign up free
- Settings → API Keys → Create API Key → Full Access
- Copy the key (starts with `SG....`)
- Also: verify your sender email address under Sender Authentication

**C) GitHub Account** (free)
- Go to [github.com](https://github.com) → sign up if needed

---

### Step 2 — Create Your GitHub Repository

```bash
# Option A: Use GitHub's web interface
# Go to github.com → New Repository → name it "science-policy-digest"
# Upload all files from this folder

# Option B: Command line
git init
git add .
git commit -m "Initial science policy digest"
gh repo create science-policy-digest --public --push
```

Your repository should have this structure:
```
science-policy-digest/
├── src/
│   └── digest.py
├── requirements.txt
├── .github/
│   └── workflows/
│       └── daily-digest.yml
└── README.md
```

---

### Step 3 — Add Your Secrets to GitHub

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add all four:

| Secret Name        | Value                              |
|--------------------|------------------------------------|
| `ANTHROPIC_API_KEY`| Your Anthropic key (`sk-ant-...`)  |
| `SENDGRID_API_KEY` | Your SendGrid key (`SG....`)       |
| `FROM_EMAIL`       | The verified sender email address  |
| `TO_EMAIL`         | Where you want the digest sent     |

---

### Step 4 — Test It

1. Go to your repository → **Actions** tab
2. Click **Science Policy Daily Digest** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — you should receive an email within ~2 minutes

If it works, you're done. The workflow will run automatically every 
weekday at 7 AM Eastern from now on.

---

## Customization

### Change the delivery time
Edit `.github/workflows/daily-digest.yml`:
```yaml
- cron: "0 12 * * 1-5"   # 12:00 UTC = 7:00 AM Eastern
- cron: "0 14 * * 1-5"   # 14:00 UTC = 9:00 AM Eastern
- cron: "0 12 * * *"     # Run 7 days a week instead of 5
```

Use [crontab.guru](https://crontab.guru) to build custom schedules.

### Add or remove RSS feeds
Edit the `RSS_FEEDS` list in `src/digest.py`. Each entry needs:
```python
{"name": "Display Name", "url": "https://example.com/feed.xml"}
```

To find an RSS feed for any website, try appending `/feed`, `/rss`, 
or `/feed.xml` to the URL, or use a browser extension like "RSS Finder."

### Change the focus areas
Edit the `SYSTEM_PROMPT` in `src/digest.py` to adjust which topics 
Claude prioritizes. The current prompt emphasizes:
- Federal research funding
- Congressional oversight and legislation
- OMB and executive branch actions
- University and academic research policy
- AI, quantum, and emerging technology

### Send to multiple recipients
Change `TO_EMAIL` to a distribution list address, or modify the 
`send_email()` function to accept a comma-separated list.

### Add a weekend edition
Add Saturday/Sunday cron triggers and adjust the prompt to request 
a weekly summary instead of daily news.

---

## Troubleshooting

**Email not arriving?**
- Check your spam folder
- Verify your FROM_EMAIL is authenticated in SendGrid
- Check the GitHub Actions logs for error messages

**"No items fetched" error?**
- Some RSS feeds occasionally go down — this is normal
- The script will still run if at least one feed returns items

**Claude API errors?**
- Check your Anthropic account has credits
- The `claude-sonnet-4-20250514` model string may need updating — 
  check [docs.anthropic.com](https://docs.anthropic.com) for current model names

---

## Cost Estimate

| Service     | Usage              | Monthly Cost |
|-------------|-------------------|--------------|
| Anthropic   | ~22 runs/month    | ~$0.50–2.00  |
| SendGrid    | ~22 emails/month  | Free         |
| GitHub      | Actions minutes   | Free         |
| **Total**   |                   | **< $2/month** |

---

## File Structure

```
src/digest.py                    # Main script (feeds → Claude → email)
requirements.txt                 # Python dependencies
.github/workflows/daily-digest.yml  # GitHub Actions scheduler
README.md                        # This file
```
