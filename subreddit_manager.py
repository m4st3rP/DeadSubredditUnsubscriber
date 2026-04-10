import asyncio
import pandas as pd
import re
import os
import sys
import json
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
    """Navigates to a subreddit and extracts metrics using robust shadow-piercing evaluation."""
    url = f"https://www.reddit.com/r/{sub_name}/"
    metrics = {
        'name': sub_name,
        'weekly_visitors': 0,
        'weekly_contributions': 0,
        'subscribers': 0
    }

    try:
        # Load the page and wait for it to be ready
        await page.goto(url, wait_until="load", timeout=60000)

        # Scroll down to trigger lazy-loading of sidebar widgets
        await page.evaluate("window.scrollTo(0, 1000)")
        # Give Shreddit widgets ample time to "hydrate" their numbers
        await asyncio.sleep(8)

        # Use a very aggressive in-browser evaluation to find the numbers, piercing shadow DOM
        found_metrics = await page.evaluate("""
            () => {
                const res = { v: 0, c: 0, s: 0 };
                const parse = (s) => {
                    if (!s) return 0;
                    const c = s.toLowerCase().replace(/,/g, '').trim();
                    if (c.includes('k')) return parseFloat(c.replace('k', '')) * 1000;
                    if (c.includes('m')) return parseFloat(c.replace('m', '')) * 1000000;
                    return parseFloat(c) || 0;
                };

                const findInNode = (root) => {
                    // Check faceplate-number
                    const faceplates = (root.querySelectorAll ? root.querySelectorAll('faceplate-number') : []);
                    faceplates.forEach(el => {
                        const label = (el.getAttribute('label') || el.parentElement.innerText || "").toLowerCase();
                        const num = el.getAttribute('number') || el.innerText;
                        if (label.includes('visitors')) res.v = Math.max(res.v, parse(num));
                        else if (label.includes('contributions')) res.c = Math.max(res.c, parse(num));
                        else if (label.includes('members') || label.includes('subscribers')) res.s = Math.max(res.s, parse(num));
                    });

                    // Check text patterns in this root
                    const text = (root.innerText || root.textContent || "");
                    if (res.v === 0) {
                        const m = text.match(/([\\d.kKM,]+)\\s+Weekly\\s+visitors/i);
                        if (m) res.v = parse(m[1]);
                    }
                    if (res.c === 0) {
                        const m = text.match(/([\\d.kKM,]+)\\s+Weekly\\s+contributions/i);
                        if (m) res.c = parse(m[1]);
                    }
                    if (res.s === 0) {
                        const m = text.match(/([\\d.kKM,]+)\\s+(Members|subscribers)/i);
                        if (m) res.s = parse(m[1]);
                    }

                    // Recurse into shadow roots
                    const all = (root.querySelectorAll ? root.querySelectorAll('*') : []);
                    all.forEach(el => {
                        if (el.shadowRoot) findInNode(el.shadowRoot);
                    });
                };

                findInNode(document.body);
                return res;
            }
        """)

        metrics['weekly_visitors'] = int(found_metrics['v'])
        metrics['weekly_contributions'] = int(found_metrics['c'])
        metrics['subscribers'] = int(found_metrics['s'])

    except Exception as e:
        print(f"Error scraping r/{sub_name}: {e}")

    return metrics

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
            elif choice in ['2']:
                if not os.path.exists(SESSION_FILE):
                    print("Error: session file missing. Please login first.")
                    continue

                print("\nPaste the 'multireddit of your subscriptions' URL or a list of subreddits:")
                user_input = input("Input: ")
                subs = parse_subs_from_input(user_input)

                if not subs:
                    print("No subreddits identified.")
                    continue

                is_headless = input("Run browser in headless mode? (y/n, recommend 'n' if metrics were 0 before): ").lower() != 'n'

                print(f"Analyzing {len(subs)} subreddits...")
                browser = await p.chromium.launch(headless=is_headless)
                context = await browser.new_context(
                    storage_state=SESSION_FILE,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                results = []
                for i, name in enumerate(subs):
                    print(f"[{i+1}/{len(subs)}] r/{name}...", end="\r")
                    data = await scrape_subreddit_metrics(page, name)
                    results.append(data)

                    if name == "absolutelynotmeirl":
                        v = data['weekly_visitors']
                        c = data['weekly_contributions']
                        print(f"\n[TEST] r/absolutelynotmeirl: {v} visitors (target: 763), {c} contributions (target: 20)")
                        if not (763 - 50 <= v <= 763 + 50):
                            print(f"  FAILED: Visitors ({v}) outside range 763 +- 50.")
                        else:
                            print(f"  SUCCESS: Visitors ({v}) within range!")

                    await asyncio.sleep(1)

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
