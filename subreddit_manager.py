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
    print("Once you have successfully logged in and are on your home feed,")
    print("come back to this terminal and press ENTER to save your session.")

    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()

    await page.goto("https://www.reddit.com/login")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "Press ENTER here when you have finished logging in...")

    try:
        # Save the storage state
        await context.storage_state(path=SESSION_FILE)
        print(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        print(f"Failed to save session: {e}")
    finally:
        await browser.close()

async def get_subscribed_subreddits(page):
    """Extracts the list of subreddits by exploring multiple Reddit pages."""
    print("Fetching subscribed subreddits...")
    subreddits = set()

    # Target URLs that list subreddits
    urls = [
        "https://old.reddit.com/subreddits/mine/",
        "https://www.reddit.com/subreddits/mine/",
        "https://www.reddit.com/best/communities/1/", # Another source of community lists
    ]

    for url in urls:
        print(f"Scanning {url}...")
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Extract links containing /r/
            # This is a broad search to ensure we catch everything
            elements = await page.query_selector_all("a")
            for el in elements:
                href = await el.get_attribute("href")
                if href and "/r/" in href:
                    # Clean the name
                    match = re.search(r'/r/([a-zA-Z0-9_]+)', href)
                    if match:
                        name = match.group(1).lower()
                        if name not in ["all", "popular", "friends", "dashboard", "help", "redditdev", "mod", "home"]:
                            subreddits.add(name)

            # Handle pagination if on old reddit
            if "old.reddit" in url:
                for _ in range(10): # Max 10 pages for safety
                    next_button = await page.query_selector(".next-button a")
                    if next_button:
                        await next_button.click()
                        await asyncio.sleep(2)
                        elements = await page.query_selector_all("a.title")
                        for el in elements:
                            href = await el.get_attribute("href")
                            match = re.search(r'/r/([a-zA-Z0-9_]+)', href)
                            if match: subreddits.add(match.group(1).lower())
                    else:
                        break
        except Exception as e:
            print(f"Skipping {url} due to error: {e}")

    # Fallback to the sidebar navigation in new reddit if still empty
    if not subreddits:
        print("Still nothing... checking sidebar navigation.")
        await page.goto("https://www.reddit.com/", wait_until="networkidle")
        # Try to open the community drawer
        drawer_button = await page.query_selector("#left-nav-drawer-button, [aria-label='Communities']")
        if drawer_button:
            await drawer_button.click()
            await asyncio.sleep(2)
            elements = await page.query_selector_all("a[href*='/r/']")
            for el in elements:
                href = await el.get_attribute("href")
                match = re.search(r'/r/([a-zA-Z0-9_]+)', href)
                if match: subreddits.add(match.group(1).lower())

    print(f"Found {len(subreddits)} unique subreddits.")
    return list(subreddits)

async def scrape_subreddit_metrics(page, sub_name):
    """Navigates to a subreddit and extracts metrics."""
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
        await asyncio.sleep(2)

        content = await page.content()

        # Robust regex for activity metrics
        v_match = re.search(r'([\d.kKM,]+)\s+Weekly\s+visitors', content, re.IGNORECASE)
        c_match = re.search(r'([\d.kKM,]+)\s+Weekly\s+contributions', content, re.IGNORECASE)

        def parse_val(m):
            if not m: return 0
            val = m.group(1).lower().replace(',', '')
            try:
                if 'k' in val: return int(float(val.replace('k', '')) * 1000)
                if 'm' in val: return int(float(val.replace('m', '')) * 1000000)
                return int(float(val))
            except: return 0

        metrics['weekly_visitors'] = parse_val(v_match)
        metrics['weekly_contributions'] = parse_val(c_match)

        sub_match = re.search(r'([\d.kKM,]+)\s+(Members|subscribers)', content, re.IGNORECASE)
        if sub_match:
            metrics['subscribers'] = parse_val(sub_match)

        date_match = re.search(r'Created\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})', content)
        if date_match:
            metrics['created_date'] = date_match.group(1)

    except Exception as e:
        print(f"Error scraping r/{sub_name}: {e}")

    return metrics

async def unsubscribe(page, sub_name):
    print(f"Unsubscribing from r/{sub_name}...")
    try:
        await page.goto(f"https://www.reddit.com/r/{sub_name}/")
        await asyncio.sleep(2)
        # Try finding the Joined button
        button = await page.query_selector("button:has-text('Joined'), [aria-label*='Leave'], button:has-text('Leave')")
        if button:
            await button.click()
            await asyncio.sleep(1)
            confirm = await page.query_selector("button:has-text('Leave')")
            if confirm: await confirm.click()
            print("Success.")
        else:
            print("Button not found.")
    except Exception as e:
        print(f"Error: {e}")

async def run_manager():
    async with async_playwright() as p:
        while True:
            print("\n--- Reddit Subreddit Manager ---")
            print("1. Login (Headed)")
            print("2. Fetch & Analyze")
            print("3. Filter & Unsubscribe (from CSV)")
            print("4. Exit")

            choice = input("Select: ")

            if choice == '1':
                await login(p)
            elif choice == '2':
                if not os.path.exists(SESSION_FILE):
                    print("Error: session file missing. Please login first.")
                    continue

                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=SESSION_FILE)
                page = await context.new_page()

                # Check if we are really logged in
                await page.goto("https://www.reddit.com/settings/")
                if "login" in page.url.lower():
                    print("Error: The saved session is invalid or expired. Please login again.")
                    await browser.close()
                    continue

                subs = await get_subscribed_subreddits(page)
                if not subs:
                    print("Error: No subreddits found. Ensure you are logged in and have subscriptions.")
                    await browser.close()
                    continue

                results = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] r/{name}...")
                    data = await scrape_subreddit_metrics(page, name)
                    results.append(data)
                    await asyncio.sleep(1)

                if results:
                    df = pd.DataFrame(results)
                    df.sort_values('weekly_contributions', ascending=False).to_csv(OUTPUT_CSV, index=False)
                    print(f"\nSaved to {OUTPUT_CSV}")
                else:
                    print("No data collected.")

                await browser.close()

            elif choice == '3':
                if not os.path.exists(OUTPUT_CSV):
                    print("Error: CSV not found.")
                    continue
                df = pd.read_csv(OUTPUT_CSV)
                m = input("Filter by (1: visitors, 2: contributions): ")
                k = 'weekly_visitors' if m == '1' else 'weekly_contributions'
                val = float(input(f"Cutoff: "))
                to_rem = df[df[k] < val]['name'].tolist()
                if to_rem and input(f"Unsubscribe from {len(to_rem)}? (y/n): ") == 'y':
                    browser = await p.chromium.launch(headless=False)
                    context = await browser.new_context(storage_state=SESSION_FILE)
                    page = await context.new_page()
                    for name in to_rem: await unsubscribe(page, name)
                    await browser.close()
            elif choice == '4':
                break

if __name__ == "__main__":
    asyncio.run(run_manager())
