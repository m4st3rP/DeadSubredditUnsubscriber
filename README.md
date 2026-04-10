# Dead Subreddit Unsubscriber

A tool to help you clean up your Reddit subscriptions based on actual community activity (weekly visitors and weekly contributions).

**No Reddit API Key Required.** This tool uses Playwright browser automation to scrape metrics and manage subscriptions safely.

## Features

- **Activity Metrics**: Scrapes "Weekly Visitors" and "Weekly Contributions" directly from subreddit pages.
- **Bulk Cleanup**: Define a cutoff value and automatically unsubscribe from subreddits that fall below it.
- **CSV Export**: Saves all your subscription data to a CSV for easy sorting and review.
- **Secure Session**: Saves your login session locally so you don't have to log in every time.

## Prerequisites

- Python 3.8+
- [Playwright](https://playwright.dev/python/docs/intro)

## Installation

1. Clone this repository or download the script.
2. Install the required Python packages:
   ```bash
   pip install playwright pandas
   ```
3. Install the browser binaries:
   ```bash
   playwright install chromium
   ```

## How to Use

Run the script:
```bash
python subreddit_manager.py
```

### Step 1: Login
Choose **Option 1** from the menu. A browser window will open. Log in to your Reddit account normally. Once you are logged in, the script will save your session and close the browser.

### Step 2: Fetch & Analyze
Choose **Option 2**. The script will:
- Navigate to your "mine" subreddits page.
- Scroll to capture all your subscriptions.
- Visit each subreddit one by one to scrape its activity metrics.
- Save everything to `subreddits_stats.csv`.

### Step 3: Filter & Unsubscribe
Choose **Option 3**.
- The script will load the CSV.
- You can choose which metric to filter by (Visitors or Contributions).
- Enter a cutoff value.
- Review the list of subreddits to be removed.
- Confirm with `yes` to begin the automated unsubscription process.

## CSV Columns

- `name`: Subreddit name.
- `weekly_visitors`: Estimated unique visitors in the last 7 days.
- `weekly_contributions`: Number of posts and comments in the last 7 days.
- `subscribers`: Total member count.
- `created_date`: The date the subreddit was created (proxy for subscription date).

## Note on "Subscription Date"
Reddit does not publicly expose the exact date you subscribed to a community. This tool uses the **Subreddit Creation Date** as a fallback to help you identify how old a community is.
