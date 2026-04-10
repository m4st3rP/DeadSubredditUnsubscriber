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
    if "/r/" in user_input:
        match = re.search(r'/r/([a-zA-Z0-9_+]+)', user_input)
        if match: user_input = match.group(1)
    subs = re.split(r'[+\s,]+', user_input)
    clean_subs = set()
    for s in subs:
        s = s.strip().lower()
        if s and s not in ["all", "popular", "friends", "mod", "home"]: clean_subs.add(s)
    return list(clean_subs)

async def scrape_subreddit_metrics(page, sub_name):
    """Navigates to a subreddit and extracts metrics using Playwright selectors."""
    url = f"https://www.reddit.com/r/{sub_name}/"
    metrics = {'name': sub_name, 'weekly_visitors': 0, 'weekly_contributions': 0, 'subscribers': 0, 'created_date': 'Unknown'}

    try:
        # We need a longer timeout and better wait condition for Shreddit
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(4) # Extra time for all widgets to load

        # 1. Weekly Visitors
        try:
            visitor_el = page.locator("div:has-text('Weekly visitors')").locator("faceplate-number, span, div").first
            # Look for the element that actually contains a number near the text
            # Often it's a sibling or a parent's child
            text = await page.locator("div:has-text('Weekly visitors')").inner_text()
            match = re.search(r'([\d.kKM,]+)\s+Weekly\s+visitors', text, re.IGNORECASE)
            if not match:
                # Try finding the number element directly
                visitor_container = page.locator("div:has-text('Weekly visitors')")
                # Shreddit often uses faceplate-number
                num_el = visitor_container.locator("faceplate-number").first
                val_text = await num_el.get_attribute("number") or await num_el.inner_text()
                if val_text: metrics['weekly_visitors'] = parse_stat(val_text)
            else:
                metrics['weekly_visitors'] = parse_stat(match.group(1))
        except: pass

        # 2. Weekly Contributions
        try:
            contrib_text = await page.locator("div:has-text('Weekly contributions')").inner_text()
            match = re.search(r'([\d.kKM,]+)\s+Weekly\s+contributions', contrib_text, re.IGNORECASE)
            if not match:
                num_el = page.locator("div:has-text('Weekly contributions')").locator("faceplate-number").first
                val_text = await num_el.get_attribute("number") or await num_el.inner_text()
                if val_text: metrics['weekly_contributions'] = parse_stat(val_text)
            else:
                metrics['weekly_contributions'] = parse_stat(match.group(1))
        except: pass

        # 3. Subscribers & Created Date
        try:
            sub_text = await page.locator("div:has-text('Members')").inner_text() or await page.locator("div:has-text('subscribers')").inner_text()
            match = re.search(r'([\d.kKM,]+)', sub_text)
            if match: metrics['subscribers'] = parse_stat(match.group(1))

            # Use raw content for date as it's usually just a string
            content = await page.content()
            date_match = re.search(r'Created\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})', content)
            if date_match: metrics['created_date'] = date_match.group(1)
        except: pass

        # Fallback: if visitors/contributions are still 0, try a more aggressive regex on the whole page
        if metrics['weekly_visitors'] == 0 or metrics['weekly_contributions'] == 0:
            content = await page.content()
            v_match = re.search(r'([\d.kKM,]+)\s+Weekly\s+visitors', content, re.IGNORECASE)
            c_match = re.search(r'([\d.kKM,]+)\s+Weekly\s+contributions', content, re.IGNORECASE)
            if v_match and metrics['weekly_visitors'] == 0: metrics['weekly_visitors'] = parse_stat(v_match.group(1))
            if c_match and metrics['weekly_contributions'] == 0: metrics['weekly_contributions'] = parse_stat(c_match.group(1))

    except Exception as e:
        print(f"Error scraping r/{sub_name}: {e}")

    return metrics

def parse_stat(val):
    if not val: return 0
    val = str(val).lower().replace(',', '').strip()
    try:
        if 'k' in val: return int(float(val.replace('k', '')) * 1000)
        if 'm' in val: return int(float(val.replace('m', '')) * 1000000)
        return int(float(val))
    except: return 0

async def unsubscribe(page, sub_name):
    print(f"Unsubscribing from r/{sub_name}...")
    try:
        await page.goto(f"https://www.reddit.com/r/{sub_name}/")
        await asyncio.sleep(3)
        button = await page.query_selector("button:has-text('Joined'), [aria-label*='Leave'], button:has-text('Leave')")
        if button:
            await button.click()
            await asyncio.sleep(1)
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
            print("2. Fetch & Analyze (Manual Paste URL/List)")
            print("3. Filter & Unsubscribe (from CSV)")
            print("4. Exit")

            choice = input("Select: ")

            if choice == '1':
                await login(p)
            elif choice == '2':
                if not os.path.exists(SESSION_FILE):
                    print("Error: session file missing. Please login first.")
                    continue

                print("\nPaste the 'multireddit of your subscriptions' URL or a list of subreddits:")
                user_input = input("Input: ")
                subs = parse_subs_from_input(user_input)

                if not subs:
                    print("No subreddits identified.")
                    continue

                print(f"Analyzing {len(subs)} subreddits...")
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=SESSION_FILE)
                page = await context.new_page()

                results = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] r/{name}...", end="\r")
                    results.append(await scrape_subreddit_metrics(page, name))
                    # Optional: small random jitter to avoid rate limiting
                    await asyncio.sleep(0.5)

                if results:
                    pd.DataFrame(results).sort_values('weekly_contributions', ascending=False).to_csv(OUTPUT_CSV, index=False)
                    print(f"\nSaved {len(results)} records to {OUTPUT_CSV}")
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
