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

    # We wait for manual user input in the terminal as a fallback to unreliable selectors
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "Press ENTER here when you have finished logging in...")

    try:
        # Check if we are actually logged in by looking for common elements
        content = await page.content()
        if "login" in page.url.lower():
             print("Warning: It looks like you might still be on the login page.")

        # Save the storage state
        await context.storage_state(path=SESSION_FILE)
        print(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        print(f"Failed to save session: {e}")
    finally:
        await browser.close()

async def get_subscribed_subreddits(page):
    """Extracts the list of subreddits by scrolling through the 'mine' page."""
    print("Fetching subscribed subreddits...")
    # Navigate to the classic subreddits page which is more stable for scraping
    await page.goto("https://old.reddit.com/subreddits/mine/")

    subreddits = set()

    while True:
        # Extract currently visible subreddits (old reddit style)
        elements = await page.query_selector_all("a.title")
        for el in elements:
            href = await el.get_attribute("href")
            if href and "/r/" in href:
                parts = href.split("/r/")
                if len(parts) > 1:
                    name = parts[1].split("/")[0].strip()
                    if name and name.lower() not in ["all", "popular", "friends"]:
                        subreddits.add(name.lower())

        # Check for "next" button in old reddit
        next_button = await page.query_selector(".next-button a")
        if next_button:
            await next_button.click()
            await asyncio.sleep(2)
        else:
            break

    # Fallback to new reddit if old reddit didn't work or for completeness
    if not subreddits:
        print("Old Reddit list empty, trying new Reddit...")
        await page.goto("https://www.reddit.com/subreddits/mine/")
        last_height = await page.evaluate("document.body.scrollHeight")
        while True:
            elements = await page.query_selector_all("a[href*='/r/']")
            for el in elements:
                href = await el.get_attribute("href")
                if href and "/r/" in href:
                    parts = href.split("/r/")
                    name = parts[1].split("/")[0].strip()
                    if name and name.lower() not in ["all", "popular"]:
                        subreddits.add(name.lower())

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height: break
            last_height = new_height

    print(f"Found {len(subreddits)} unique subreddits.")
    return list(subreddits)

async def scrape_subreddit_metrics(page, sub_name):
    """Navigates to a subreddit and extracts metrics."""
    # We use sh.reddit.com or www.reddit.com as old.reddit doesn't have the new weekly metrics
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
        await asyncio.sleep(3) # Shreddit needs time to load sidebars

        content = await page.content()

        # Look for numbers associated with "Weekly visitors" and "Weekly contributions"
        # Using a more robust regex that ignores extra HTML tags in between
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
        await asyncio.sleep(3)

        # Try finding the 'Joined' button with various methods
        for selector in ["button:has-text('Joined')", "[aria-label*='Leave']", "button:has-text('Leave')"]:
            button = await page.query_selector(selector)
            if button:
                await button.click()
                await asyncio.sleep(1)
                # Confirm if a modal appears
                confirm = await page.query_selector("button:has-text('Leave')")
                if confirm:
                    await confirm.click()
                print(f"Unsubscribed from r/{sub_name}")
                return
        print(f"Could not find leave button for r/{sub_name}")
    except Exception as e:
        print(f"Error: {e}")

async def run_manager():
    async with async_playwright() as p:
        while True:
            print("\n--- Reddit Subreddit Manager ---")
            print("1. Login (Headed Browser)")
            print("2. Fetch & Analyze (Scrape Mode)")
            print("3. Filter & Unsubscribe (from CSV)")
            print("4. Exit")

            choice = input("Select: ")

            if choice == '1':
                await login(p)
            elif choice == '2':
                if not os.path.exists(SESSION_FILE):
                    print("Please login first.")
                    continue
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=SESSION_FILE)
                page = await context.new_page()
                subs = await get_subscribed_subreddits(page)

                results = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] r/{name}...")
                    data = await scrape_subreddit_metrics(page, name)
                    results.append(data)
                    await asyncio.sleep(1)

                pd.DataFrame(results).sort_values('weekly_contributions', ascending=False).to_csv(OUTPUT_CSV, index=False)
                print(f"Done. Saved to {OUTPUT_CSV}")
                await browser.close()
            elif choice == '3':
                if not os.path.exists(OUTPUT_CSV):
                    print("No CSV found.")
                    continue
                df = pd.read_csv(OUTPUT_CSV)
                m = input("Filter by (1: visitors, 2: contributions): ")
                k = 'weekly_visitors' if m == '1' else 'weekly_contributions'
                val = float(input(f"Cutoff for {k}: "))
                to_rem = df[df[k] < val]['name'].tolist()
                if to_rem and input(f"Remove {len(to_rem)} subs? (y/n): ") == 'y':
                    browser = await p.chromium.launch(headless=False)
                    context = await browser.new_context(storage_state=SESSION_FILE)
                    page = await context.new_page()
                    for name in to_rem:
                        await unsubscribe(page, name)
                    await browser.close()
            elif choice == '4':
                break

if __name__ == "__main__":
    asyncio.run(run_manager())
