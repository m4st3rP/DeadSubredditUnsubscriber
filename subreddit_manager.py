import asyncio
import pandas as pd
import re
import os
import sys
from playwright.async_api import async_playwright

# File to store the browser session to avoid repeated logins
SESSION_FILE = "reddit_session.json"
OUTPUT_CSV = "subreddits_stats.csv"

async def login(p):
    """Launch a headed browser for manual login and save session."""
    print("\n--- LOGIN MODE ---")
    print("A browser window will open. Please log in to your Reddit account.")
    print("Once you are logged in and see your home feed, the script will detect it.")

    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()

    await page.goto("https://www.reddit.com/login")

    try:
        # Wait until we see evidence of being logged in (the user drawer/avatar)
        # We use a long timeout (5 minutes) to give the user plenty of time.
        await page.wait_for_selector("#email-collection-tooltip-id, #web-navigation-user-menu, faceplate-tracker[noun='user_menu']", timeout=300000)
        print("Login detected!")
        # Save the storage state
        await context.storage_state(path=SESSION_FILE)
        print(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        print(f"Login timeout or failed: {e}")
    finally:
        await browser.close()

async def get_subscribed_subreddits(page):
    """Extracts the list of subreddits by scrolling through the 'mine' page."""
    print("Fetching subscribed subreddits...")
    await page.goto("https://www.reddit.com/subreddits/mine/")

    subreddits = set()

    # Scroll to load all subreddits (Reddit uses infinite scroll or pagination here)
    last_height = await page.evaluate("document.body.scrollHeight")
    while True:
        # Extract currently visible subreddits
        elements = await page.query_selector_all("a.title, a.subreddit, .subscription-box a")
        for el in elements:
            href = await el.get_attribute("href")
            if href and "/r/" in href:
                # Handle cases like /r/python/ or /r/python
                parts = href.split("/r/")
                if len(parts) > 1:
                    name = parts[1].split("/")[0].strip()
                    if name and name not in ["all", "popular"]:
                        subreddits.add(name.lower())

        # Scroll down
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2) # Wait for load

        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            # Try one more wait in case it's slow
            await asyncio.sleep(3)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
        last_height = new_height

    print(f"Found {len(subreddits)} unique subreddits.")
    return list(subreddits)

async def scrape_subreddit_metrics(page, sub_name):
    """Navigates to a subreddit and extracts metrics from the sidebar/content."""
    url = f"https://www.reddit.com/r/{sub_name}/"
    metrics = {
        'name': sub_name,
        'weekly_visitors': 0,
        'weekly_contributions': 0,
        'subscribers': 0,
        'created_date': 'Unknown'
    }

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2) # Allow for hydration

        content = await page.content()

        # 1. Weekly Visitors & Contributions (Regex on raw HTML content)
        v_match = re.search(r'([0-9kK.M]+)\s+Weekly visitors', content)
        c_match = re.search(r'([0-9kK.M]+)\s+Weekly contributions', content)

        def parse_val(m):
            if not m: return 0
            val = m.group(1).lower().replace(',', '')
            if 'k' in val: return int(float(val.replace('k', '')) * 1000)
            if 'm' in val: return int(float(val.replace('m', '')) * 1000000)
            return int(float(val))

        metrics['weekly_visitors'] = parse_val(v_match)
        metrics['weekly_contributions'] = parse_val(c_match)

        # 2. Subscribers
        sub_match = re.search(r'([0-9kK.M,]+)\s+Members', content) or re.search(r'([0-9kK.M,]+)\s+subscribers', content)
        if sub_match:
            metrics['subscribers'] = parse_val(sub_match)

        # 3. Created Date (proxy for subscription date)
        # Look for "Created ..." in the sidebar
        date_match = re.search(r'Created\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})', content)
        if date_match:
            metrics['created_date'] = date_match.group(1)

    except Exception as e:
        print(f"Error scraping r/{sub_name}: {e}")

    return metrics

async def unsubscribe(page, sub_name):
    """Unsubscribes from a subreddit."""
    print(f"Attempting to unsubscribe from r/{sub_name}...")
    try:
        await page.goto(f"https://www.reddit.com/r/{sub_name}/")
        await asyncio.sleep(2)

        # Try different selectors for the "Joined" button
        button = await page.query_selector("button:has-text('Joined'), [aria-label*='Leave'], button:has-text('Leave')")
        if button:
            await button.click()
            await asyncio.sleep(1)
            # Handle confirmation popup if it appears
            confirm = await page.query_selector("button:has-text('Leave')")
            if confirm:
                await confirm.click()
                await asyncio.sleep(1)
            print(f"Success.")
        else:
            print(f"Could not find leave button (might already be unsubscribed).")
    except Exception as e:
        print(f"Error during unsubscription: {e}")

async def run_manager():
    async with async_playwright() as p:
        while True:
            print("\n--- Reddit Subreddit Manager (No API Key) ---")
            print("1. Login (Headed Browser)")
            print("2. Fetch & Analyze Subreddits (Scrape Mode)")
            print("3. Filter & Unsubscribe (from CSV)")
            print("4. Exit")

            choice = input("Select an option: ")

            if choice == '1':
                await login(p)

            elif choice == '2':
                if not os.path.exists(SESSION_FILE):
                    print("Error: No session found. Please login first (Option 1).")
                    continue

                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=SESSION_FILE)
                page = await context.new_page()

                subs = await get_subscribed_subreddits(page)
                all_data = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] Analyzing r/{name}...")
                    data = await scrape_subreddit_metrics(page, name)
                    all_data.append(data)
                    await asyncio.sleep(1) # Be gentle

                df = pd.DataFrame(all_data)
                # Default sort by contributions descending
                df = df.sort_values(by='weekly_contributions', ascending=False)
                df.to_csv(OUTPUT_CSV, index=False)
                print(f"\nDone! Results saved to {OUTPUT_CSV}")
                await browser.close()

            elif choice == '3':
                if not os.path.exists(OUTPUT_CSV):
                    print(f"Error: {OUTPUT_CSV} not found. Run Option 2 first.")
                    continue

                df = pd.read_csv(OUTPUT_CSV)
                print(f"\nLoaded {len(df)} subreddits.")

                metric = input("Filter by (1: weekly_visitors, 2: weekly_contributions): ")
                metric_key = 'weekly_visitors' if metric == '1' else 'weekly_contributions'

                try:
                    cutoff = float(input(f"Enter cutoff value for {metric_key} (BELOW this will be removed): "))
                except ValueError:
                    print("Invalid input.")
                    continue

                to_remove = df[df[metric_key] < cutoff]['name'].tolist()

                if not to_remove:
                    print("No subreddits found below cutoff.")
                else:
                    print(f"\nSubreddits to remove: {', '.join(to_remove)}")
                    confirm = input(f"Are you sure you want to unsubscribe from {len(to_remove)} subreddits? (yes/no): ")
                    if confirm.lower() == 'yes':
                        browser = await p.chromium.launch(headless=False) # Headed to see progress/avoid being flagged
                        context = await browser.new_context(storage_state=SESSION_FILE)
                        page = await context.new_page()

                        for name in to_remove:
                            await unsubscribe(page, name)
                            await asyncio.sleep(2)

                        print("\nFinished cleanup.")
                        await browser.close()

            elif choice == '4':
                break

if __name__ == "__main__":
    asyncio.run(run_manager())
