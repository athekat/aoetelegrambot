import requests
import json
import os
from datetime import datetime
import asyncio #it's a requirement driven by the design of the python-telegram-bot
from telegram import Bot
from telegram.error import TelegramError
import pytz #Buenos Aires time conversion

# --- Telegram Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- Buenos Aires Timezone ---
BUENOS_AIRES_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# --- Telegram Posting Function ---
async def send_telegram_message(text_content):
    """
    Sends a text message via Telegram bot.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram BOT_TOKEN or CHAT_ID not configured.")
        print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables or directly in the script.")
        return False

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text_content, parse_mode='MarkdownV2')
        print("Telegram message sent successfully!")
        return True
    except TelegramError as e:
        print(f"Error sending Telegram message: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while sending Telegram message: {e}")
        return False

# --- Main Logic Function ---
async def check_player_statuses_and_post_changes(players): 
    """
    Checks player statuses, compares with previous run, and posts changes to Telegram.
    """
    PREVIOUS_STATUS_FILE = "mostrecentmatch.json"

    # 1. Load previous player statuses
    previous_results = {}
    if os.path.exists(PREVIOUS_STATUS_FILE):
        try:
            with open(PREVIOUS_STATUS_FILE, 'r') as f:
                previous_results = json.load(f)
            print(f"Loaded previous statuses from {PREVIOUS_STATUS_FILE}")
        except json.JSONDecodeError as e:
            print(f"Error reading previous JSON file ({PREVIOUS_STATUS_FILE}): {e}. Starting with empty previous data.")
            previous_results = {}
    else:
        print(f"No previous status file found at {PREVIOUS_STATUS_FILE}. This might be the first run.")

    current_results = {}
    changed_posts = []

    # 2. Fetch current player statuses
    for playerdic in players:
        player_name = playerdic['name']
        api_url = playerdic['api_url']

        outcome = "status unknown"
        finished_info = ""

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()

            if data['matches']:
                last_match = data['matches'][0]
                finished_raw = last_match.get('finished')

                if finished_raw:
                    outcome = "finished playing at"
                    # Convert UTC to Buenos Aires time
                    utc_dt = datetime.fromisoformat(finished_raw.replace('Z', '+00:00')).replace(tzinfo=pytz.utc)
                    buenos_aires_dt = utc_dt.astimezone(BUENOS_AIRES_TZ)
                    finished_info = buenos_aires_dt.strftime("%H:%M %Y\-%m\-%d")
                else:
                    outcome = "is playing now\\." # Escaped for MarkdownV2
                    finished_info = ""
            else:
                print(f"No recent matches found for player: {player_name}")
                outcome = "has no recent matches"
                finished_info = ""

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data for player {player_name}: {e}")
            outcome = f"encountered an API error: {e}"
            finished_info = ""
        except json.JSONDecodeError:
            print(f"Error decoding JSON for player {player_name}. API might have returned invalid data.")
            outcome = "returned invalid data"
            finished_info = ""

        # Construct the full status message for comparison and posting
        # Use MarkdownV2 for bolding player names
        status_message = f"*{player_name}* {outcome} {finished_info}".strip()
        current_results[player_name] = status_message.replace('*', '') # Store unformatted for comparison

        # 3. Compare current status with previous status
        previous_status = previous_results.get(player_name)

        if previous_status is None:
            print(f"NEW PLAYER STATUS: {status_message}")
            changed_posts.append(status_message)
        elif previous_status != current_results[player_name]: # Compare unformatted string
            print(f"STATUS CHANGED: {status_message} (Previously: {previous_status})")
            changed_posts.append(status_message)
        else:
            print(f"NO CHANGE: {status_message.replace('*', '')}") # Print unformatted

    # 4. Save the current results
    try:
        with open(PREVIOUS_STATUS_FILE, 'w') as f:
            json.dump(current_results, f, indent=4)
        print(f"\nUpdated player statuses saved to {PREVIOUS_STATUS_FILE}")
    except IOError as e:
        print(f"Error writing to file {PREVIOUS_STATUS_FILE}: {e}")

    # 5. Post all identified changes to Telegram
    if changed_posts:
        print(f"\n--- Posting {len(changed_posts)} changed statuses to Telegram ---")
        for post_text in changed_posts:
            print(f"Attempting to send to Telegram: '{post_text}'")
            await send_telegram_message(post_text)

    else:
        print("\nNo status changes detected. No new messages to Telegram.")

# Define the players to monitor
players = [
    {"name": "Carpincho", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=6446904&search=&page=1"},
    {"name": "alanthekat", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=1263162&search=&page=1"},
    {"name": "thexcarpincho", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=18660623&search=&page=1"},
    {"name": "Dicopato", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=255507&search=&page=1"},
    {"name": "Dicopatito", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=6237950&search=&page=1"},
    {"name": "Nanox", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=439001&search=&page=1"},
    {"name": "Sir Monkey", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=903496&search=&page=1"}
]

if __name__ == "__main__":
    # To run async functions, you need to use asyncio.run()
    asyncio.run(check_player_statuses_and_post_changes(players))