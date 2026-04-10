# Dead Subreddit Unsubscriber

A tool to help you clean up your Reddit subscriptions based on actual community activity (weekly visitors and weekly contributions).

**No Reddit API Key Required.** This tool uses Playwright browser automation to scrape metrics and manage subscriptions safely.

## Features

- **Activity Metrics**: Scrapes "Weekly Visitors" and "Weekly Contributions" directly from subreddit pages.
- **Manual Import**: If automated discovery fails, you can paste your "multireddit" link directly.
- **Bulk Cleanup**: Define a cutoff value and automatically unsubscribe from subreddits that fall below it.
- **CSV Export**: Saves all your subscription data to a CSV for easy sorting and review.

## Installation

1. Install the required Python packages:
   ```bash
   pip install playwright pandas
   ```
2. Install the browser binaries:
   ```bash
   playwright install chromium
   ```

## How to Use

Run the script:
```bash
python subreddit_manager.py
```

### Step 1: Login (Option 1)
Choose **Option 1**. A browser window will open. Log in to your Reddit account. Once you are logged in, return to the terminal and press **ENTER**.

### Step 2: Fetch & Analyze (Option 2 or 3)
If automated discovery (Option 2) finds no subreddits, use **Option 3**:
1. Go to [reddit.com/subreddits](https://www.reddit.com/subreddits).
2. On the right sidebar, look for **"multireddit of your subscriptions"**.
3. Right-click that link and select **"Copy link address"**.
4. Paste that link into the script when prompted.
5. The script will visit each subreddit to scrape activity metrics and save them to `subreddits_stats.csv`.

### Step 3: Filter & Unsubscribe (Option 4)
Choose **Option 4**.
- Choose a metric (Visitors or Contributions) and enter a cutoff value.
- Confirm with `y` to begin the automated unsubscription process.

## CSV Columns

- `name`: Subreddit name.
- `weekly_visitors`: Estimated unique visitors in the last 7 days.
- `weekly_contributions`: Number of posts and comments in the last 7 days.
- `subscribers`: Total member count.
- `created_date`: The date the subreddit was created.
