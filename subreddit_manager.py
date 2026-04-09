import os
import sys
import csv
import praw
import time
import argparse
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_reddit_instance():
    """Initializes and returns a PRAW Reddit instance."""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    user_agent = os.getenv("REDDIT_USER_AGENT", "DeadSubredditUnsubscriber/0.1")

    if not all([client_id, client_secret, username, password]):
        logger.error("Missing Reddit API credentials in .env file.")
        logger.info("Please ensure REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, and REDDIT_PASSWORD are set.")
        sys.exit(1)

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        user_agent=user_agent
    )

def fetch_weekly_metrics(subreddit_name):
    """
    Attempts to fetch weekly visitors and contributions by scraping the subreddit's about page.
    Note: This is a fallback as these metrics are not currently in the official PRAW/Reddit API.
    """
    url = f"https://www.reddit.com/r/{subreddit_name}/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    visitors = 0
    contributions = 0

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # These metrics are often inside a shreddit-app or specific custom elements
            # Look for patterns like "21K Weekly visitors" or "137 Weekly contributions"
            text = soup.get_text()

            # Simple regex search in the text
            import re
            v_match = re.search(r'([0-9kK.M]+)\s+Weekly visitors', text)
            c_match = re.search(r'([0-9kK.M]+)\s+Weekly contributions', text)

            def parse_metric(m):
                if not m: return 0
                val = m.group(1).lower()
                if 'k' in val:
                    return int(float(val.replace('k', '')) * 1000)
                if 'm' in val:
                    return int(float(val.replace('m', '')) * 1000000)
                return int(float(val))

            visitors = parse_metric(v_match)
            contributions = parse_metric(c_match)
    except Exception as e:
        logger.debug(f"Could not fetch weekly metrics for r/{subreddit_name}: {e}")

    return visitors, contributions

def collect_subreddits(reddit):
    """Collects data for all subscribed subreddits."""
    logger.info("Fetching subscribed subreddits... this may take a moment.")
    subreddits_data = []

    try:
        subscriptions = list(reddit.user.subreddits(limit=None))
    except Exception as e:
        logger.error(f"Error fetching subscriptions: {e}")
        sys.exit(1)

    total = len(subscriptions)
    for i, sub in enumerate(subscriptions):
        logger.info(f"[{i+1}/{total}] Processing r/{sub.display_name}...")

        # Subscription date is not available via API, we use creation date instead.
        created_at = datetime.fromtimestamp(sub.created_utc).strftime('%Y-%m-%d')

        # Fetch weekly metrics (best effort)
        visitors, contributions = fetch_weekly_metrics(sub.display_name)

        subreddits_data.append({
            'name': sub.display_name,
            'weekly_visitors': visitors,
            'weekly_contributions': contributions,
            'subscribers': sub.subscribers,
            'created_date': created_at
        })

        # Slow down to avoid being blocked
        time.sleep(1)

    return subreddits_data

def save_to_csv(data, filename, sort_by='weekly_contributions'):
    """Saves the collected data to a CSV file, sorted by the specified metric."""
    if not data:
        logger.warning("No data to save.")
        return

    # Sort data descending by default
    sorted_data = sorted(data, key=lambda x: int(x.get(sort_by, 0)), reverse=True)

    keys = data[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(sorted_data)

    logger.info(f"Data saved to {filename}")

def load_from_csv(filename):
    """Loads subreddit data from a CSV file."""
    if not os.path.exists(filename):
        logger.error(f"File {filename} not found.")
        return []

    with open(filename, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def main():
    parser = argparse.ArgumentParser(description="Manage Reddit subscriptions based on activity metrics.")
    parser.add_argument("--fetch", action="store_true", help="Fetch fresh data from Reddit")
    parser.add_argument("--csv", default="subreddits_stats.csv", help="CSV file path (default: subreddits_stats.csv)")
    parser.add_argument("--sort", choices=["weekly_visitors", "weekly_contributions"], default="weekly_contributions", help="Sort metric")

    args = parser.parse_args()

    reddit = None
    data = []

    if args.fetch:
        reddit = get_reddit_instance()
        data = collect_subreddits(reddit)
        save_to_csv(data, args.csv, sort_by=args.sort)
    else:
        if os.path.exists(args.csv):
            logger.info(f"Loading data from {args.csv}")
            data = load_from_csv(args.csv)
        else:
            logger.info("No CSV found. Use --fetch to get data from Reddit.")
            return

    if not data:
        return

    while True:
        print(f"\nSubreddits loaded: {len(data)}")
        print("1. Sort and show top 10")
        print("2. Filter and Unsubscribe")
        print("3. Exit")

        choice = input("Select an option: ")

        if choice == '3':
            break
        elif choice == '1':
            sort_metric = input("Sort by (1: weekly_visitors, 2: weekly_contributions): ")
            metric_key = 'weekly_visitors' if sort_metric == '1' else 'weekly_contributions'
            sorted_data = sorted(data, key=lambda x: int(x.get(metric_key, 0)), reverse=True)
            for item in sorted_data[:10]:
                print(f"r/{item['name']}: {metric_key}={item[metric_key]}, subscribers={item['subscribers']}")
        elif choice == '2':
            filter_metric = input("Filter by (1: weekly_visitors, 2: weekly_contributions): ")
            metric_key = 'weekly_visitors' if filter_metric == '1' else 'weekly_contributions'

            try:
                cutoff = float(input(f"Enter cutoff value for {metric_key} (subreddits BELOW this will be removed): "))
            except ValueError:
                print("Invalid cutoff value.")
                continue

            to_unsubscribe = [row['name'] for row in data if int(row[metric_key]) < cutoff]

            if not to_unsubscribe:
                print("No subreddits found below the cutoff.")
                continue

            print(f"\nFound {len(to_unsubscribe)} subreddits below the cutoff:")
            print(", ".join(to_unsubscribe))

            confirm = input(f"\nAre you sure you want to unsubscribe from these {len(to_unsubscribe)} subreddits? (yes/no): ")
            if confirm.lower() == 'yes':
                if not reddit:
                    reddit = get_reddit_instance()

                for name in to_unsubscribe:
                    try:
                        logger.info(f"Unsubscribing from r/{name}...")
                        reddit.subreddit(name).unsubscribe()
                    except Exception as e:
                        logger.error(f"Failed to unsubscribe from r/{name}: {e}")
                print("Unsubscription complete.")
                break
            else:
                print("Operation cancelled.")
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
