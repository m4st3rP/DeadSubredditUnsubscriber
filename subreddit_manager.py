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

def parse_subs_from_input(user_input):
    """Parses subreddit names from a multireddit URL or raw string."""
    # Handle multireddit URL (e.g. /r/sub1+sub2+sub3)
    if "/r/" in user_input:
        match = re.search(r'/r/([a-zA-Z0-9_+]+)', user_input)
        if match:
            user_input = match.group(1)

    # Split by + or comma or space
    subs = re.split(r'[+\s,]+', user_input)
    # Clean and filter
    clean_subs = set()
    for s in subs:
        s = s.strip().lower()
        if s and s not in ["all", "popular", "friends", "mod", "home"]:
            clean_subs.add(s)
    return list(clean_subs)

async def get_subscribed_subreddits(page):
    """Attempt automated extraction (Fallback)."""
    print("Attempting automated fetch...")
    subreddits = set()
    urls = ["https://old.reddit.com/subreddits/", "https://www.reddit.com/subreddits/"]
    for url in urls:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            links = await page.query_selector_all("a")
            for link in links:
                href = await link.get_attribute("href")
                if href and "+" in href and "/r/" in href:
                    m = re.search(r'/r/([a-zA-Z0-9_+]+)', href)
                    if m:
                        for s in m.group(1).split("+"):
                            if s: subreddits.add(s.lower())
            if subreddits: break
        except: pass
    return list(subreddits)

async def scrape_subreddit_metrics(page, sub_name):
    """Navigates to a subreddit and extracts metrics."""
    url = f"https://www.reddit.com/r/{sub_name}/"
    metrics = {'name': sub_name, 'weekly_visitors': 0, 'weekly_contributions': 0, 'subscribers': 0, 'created_date': 'Unknown'}
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(1.5)
        content = await page.content()
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
        if sub_match: metrics['subscribers'] = parse_val(sub_match)
        date_match = re.search(r'Created\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})', content)
        if date_match: metrics['created_date'] = date_match.group(1)
    except: pass
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
        else: print("Button not found.")
    except Exception as e: print(f"Error: {e}")

async def run_manager():
    async with async_playwright() as p:
        while True:
            print("\n--- Reddit Subreddit Manager ---")
            print("1. Login (Headed)")
            print("2. Fetch & Analyze (Automated Discovery)")
            print("3. Fetch & Analyze (Manual Paste URL/List)")
            print("4. Filter & Unsubscribe (from CSV)")
            print("5. Exit")

            choice = input("Select: ")

            if choice == '1':
                await login(p)
            elif choice in ['2', '3']:
                if not os.path.exists(SESSION_FILE):
                    print("Error: session file missing. Please login first.")
                    continue

                subs = []
                if choice == '3':
                    print("\nPaste the 'multireddit of your subscriptions' URL or a list of subreddits separated by + or commas:")
                    user_input = input("Input: ")
                    subs = parse_subs_from_input(user_input)
                else:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(storage_state=SESSION_FILE)
                    page = await context.new_page()
                    subs = await get_subscribed_subreddits(page)
                    await browser.close()

                if not subs:
                    print("No subreddits identified.")
                    continue

                print(f"Identified {len(subs)} subreddits. Starting analysis...")
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=SESSION_FILE)
                page = await context.new_page()

                results = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] r/{name}...", end="\r")
                    results.append(await scrape_subreddit_metrics(page, name))

                if results:
                    pd.DataFrame(results).sort_values('weekly_contributions', ascending=False).to_csv(OUTPUT_CSV, index=False)
                    print(f"\nSaved {len(results)} records to {OUTPUT_CSV}")
                await browser.close()

            elif choice == '4':
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
            elif choice == '5':
                break

if __name__ == "__main__":
    asyncio.run(run_manager())
