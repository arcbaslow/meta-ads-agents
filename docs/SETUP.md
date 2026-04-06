# Meta Ads Plugin Setup Guide

## Prerequisites

- Python 3.10+
- Claude Code CLI
- A Meta (Facebook) account with access to ad accounts

## Step 1: Install Python Dependencies

```bash
cd claude-meta-ads/scripts
pip install -r requirements.txt
```

## Step 2: Create a Meta App

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Click **My Apps** → **Create App**
3. Select **Business** as the app type
4. Fill in the app name (e.g., "Claude Meta Ads Analyzer")
5. Select your Business Manager account (or create one)

## Step 3: Add Marketing API

1. In your app dashboard, go to **Add Products**
2. Find **Marketing API** and click **Set Up**
3. This enables the APIs needed for campaign data access

## Step 4: Configure Permissions

Your app needs these permissions:
- `ads_read` — Read ad account data
- `ads_management` — Access campaign structure
- `read_insights` — Access performance metrics
- `business_management` — Access business-level data

For **development** use, you can generate a token from the Graph API Explorer.
For **production** use, submit your app for App Review.

## Step 5: Authenticate

### Option A: OAuth Flow (Recommended)

```bash
python scripts/meta_auth.py --oauth --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET
```

This opens your browser for Facebook Login. After authorization, a long-lived token (60 days) is stored automatically.

### Option B: Manual Token

For system user tokens (e.g., from Business Manager):

```bash
python scripts/meta_auth.py --configure --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET --access-token YOUR_TOKEN
```

## Step 6: Verify Setup

```bash
python scripts/meta_auth.py --check
```

Should output:
```json
{
  "status": "ok",
  "auth_method": "oauth",
  "ad_accounts": [
    {"id": "act_123456", "name": "My Ad Account", "currency": "USD"}
  ]
}
```

## Step 7: Install Plugin in Claude Code

Add to your Claude Code settings (`.claude/settings.json`):

```json
{
  "enabledPlugins": {
    "claude-meta-ads@your-github-username": true
  }
}
```

Or install via Claude Code:
```
/install-plugin your-github-username/claude-meta-ads
```

## Usage

```
/meta-ads audit act_123456          # Full account audit
/meta-ads performance act_123456    # Performance analysis
/meta-ads creative act_123456       # Creative fatigue check
/meta-ads events act_123456         # Pixel/CAPI health
/meta-ads report act_123456         # Generate PDF report
```

## Troubleshooting

### Token Expired
Re-run the OAuth flow:
```bash
python scripts/meta_auth.py --oauth --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET
```

### Rate Limited
The plugin caches API responses for 15 minutes. If you hit rate limits:
- Wait 60 seconds and retry
- Use `--no-cache` only when you need fresh data
- Check your app's rate limit tier in the Meta App Dashboard

### No Ad Accounts Found
Ensure your Facebook user has access to ad accounts in Business Manager.
Check at: https://business.facebook.com/settings/ad-accounts

### Permission Denied
Your app may need App Review for certain permissions. For development:
- Add yourself as a test user in the app settings
- Use a development access token from Graph API Explorer
