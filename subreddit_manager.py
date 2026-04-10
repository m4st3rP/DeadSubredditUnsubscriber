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
        await context.storage_state(path=SESSION_FILE)
        print(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        print(f"Failed to save session: {e}")
    finally:
        await browser.close()

async def get_subscribed_subreddits(page):
    """Extracts the list of subreddits using the multireddit link method."""
    print("Fetching subscribed subreddits...")
    subreddits = set()

    # Method 1: Search for the 'multireddit' link on the subreddits page
    # This link usually looks like /r/sub1+sub2+sub3...
    urls_to_check = [
        "https://old.reddit.com/subreddits/",
        "https://www.reddit.com/subreddits/",
    ]

    for url in urls_to_check:
        print(f"Scanning {url} for multireddit link...")
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Find all links and look for the one containing many '+' symbols
            links = await page.query_selector_all("a")
            for link in links:
                href = await link.get_attribute("href")
                if href and "+" in href and "/r/" in href:
                    # Potential multireddit link
                    match = re.search(r'/r/([a-zA-Z0-9_+]+)', href)
                    if match:
                        subs = match.group(1).split("+")
                        if len(subs) > 5: # Only if it's a real list
                            print(f"Found multireddit link with {len(subs)} subreddits!")
                            for s in subs:
                                if s: subreddits.add(s.lower())

            if subreddits: break # Stop if we found them
        except Exception as e:
            print(f"Error on {url}: {e}")

    # Method 2: Fallback to scanning for any /r/ links (existing logic)
    if not subreddits:
        print("No multireddit link found, falling back to manual scanning...")
        # Check 'mine' pages
        mine_urls = ["https://old.reddit.com/subreddits/mine/", "https://www.reddit.com/subreddits/mine/"]
        for url in mine_urls:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                links = await page.query_selector_all("a")
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        m = re.search(r'/r/([a-zA-Z0-9_]+)', href)
                        if m:
                            name = m.group(1).lower()
                            if name not in ["all", "popular", "friends", "mod", "home"]:
                                subreddits.add(name)
            except: pass

    print(f"Total unique subreddits found: {len(subreddits)}")
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
        await asyncio.sleep(1.5) # Fast but enough for basic shreddit load

        content = await page.content()

        # Regex for activity metrics
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
        button = await page.query_selector("button:has-text('Joined'), [aria-label*='Leave'], button:has-text('Leave')")
        if button:
            await button.click()
            await asyncio.sleep(0.5)
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
            print("2. Fetch & Analyze (Long process!)")
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

                # Verify session
                await page.goto("https://www.reddit.com/settings/")
                if "login" in page.url.lower():
                    print("Error: The saved session is invalid or expired. Please login again.")
                    await browser.close()
                    continue

                subs = await get_subscribed_subreddits(page)
                if not subs:
                    print("No subreddits found.")
                    await browser.close()
                    continue

                results = []
                total = len(subs)
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{total}] r/{name}...", end="\r")
                    data = await scrape_subreddit_metrics(page, name)
                    results.append(data)
                    # No delay for large lists, Playwright handles speed well

                if results:
                    df = pd.DataFrame(results)
                    df.sort_values('weekly_contributions', ascending=False).to_csv(OUTPUT_CSV, index=False)
                    print(f"\nSaved {len(results)} records to {OUTPUT_CSV}")

                await browser.close()

            elif choice == '3':
                if not os.path.exists(OUTPUT_CSV):
                    print("Error: CSV not found.")
                    continue
                df = pd.read_csv(OUTPUT_CSV)
                m = input("Filter by (1: visitors, 2: contributions): ")
                k = 'weekly_visitors' if m == '1' else 'weekly_contributions'
                val = float(input(f"Cutoff (remove items < this): "))
                to_rem = df[df[k] < val]['name'].tolist()
                if to_rem and input(f"Unsubscribe from {len(to_rem)} subreddits? (y/n): ") == 'y':
                    browser = await p.chromium.launch(headless=False)
                    context = await browser.new_context(storage_state=SESSION_FILE)
                    page = await context.new_page()
                    for name in to_rem: await unsubscribe(page, name)
                    await browser.close()
            elif choice == '4':
                break

if __name__ == "__main__":
    asyncio.run(run_manager())
