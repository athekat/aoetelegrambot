import os
import json
import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import aiohttp
import pytz
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# --- Configuration ---
@dataclass(frozen=True)
class Config:
    """Centralized configuration for the script."""
    TELEGRAM_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.environ.get("TELEGRAM_CHAT_ID")
    TIMEZONE: pytz.BaseTzInfo = pytz.timezone('America/Argentina/Buenos_Aires')
    STATUS_FILE: Path = Path("mostrecentmatch.json")
    PLAYERS: List[Dict[str, str]] = field(default_factory=lambda: [
        {"name": "Carpincho", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=6446904&search=&page=1"},
        {"name": "alanthekat", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=1263162&search=&page=1"},
        {"name": "thexcarpincho", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=18660623&search=&page=1"},
        {"name": "Dicopato", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=255507&search=&page=1"},
        {"name": "Dicopatito", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=6237950&search=&page=1"},
        {"name": "Nanox", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=439001&search=&page=1"},
        {"name": "Sir Monkey", "api_url": "https://data.aoe2companion.com/api/matches?profile_ids=903496&search=&page=1"}
    ])

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# --- Helper Functions ---
def load_previous_statuses(file_path: Path) -> Dict[str, str]:
    """Loads previous player statuses from a JSON file."""
    if not file_path.exists():
        logging.info(f"Status file not found at {file_path}. Assuming first run.")
        return {}
    try:
        with file_path.open('r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Error reading status file {file_path}: {e}. Starting fresh.")
        return {}

def save_current_statuses(statuses: Dict[str, str], file_path: Path):
    """Saves the current player statuses to a JSON file."""
    try:
        with file_path.open('w') as f:
            json.dump(statuses, f, indent=4)
        logging.info(f"Successfully saved current statuses to {file_path}")
    except IOError as e:
        logging.error(f"Could not write to status file {file_path}: {e}")

def escape_markdown(text: str) -> str:
    """Escapes text for Telegram's MarkdownV2 format."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# --- Core Logic ---
async def fetch_player_data(session: aiohttp.ClientSession, player: Dict[str, str]) -> Dict[str, Any]:
    """Asynchronously fetches match data for a single player."""
    player_name = player['name']
    api_url = player['api_url']
    try:
        async with session.get(api_url) as response:
            response.raise_for_status()
            return {"player_name": player_name, "data": await response.json()}
    except aiohttp.ClientError as e:
        logging.error(f"Request error for {player_name}: {e}")
        return {"player_name": player_name, "error": "API request failed"}
    except json.JSONDecodeError:
        logging.error(f"JSON decode error for {player_name}")
        return {"player_name": player_name, "error": "Invalid JSON response"}

def process_player_data(player_result: Dict[str, Any], timezone: pytz.BaseTzInfo) -> str:
    """Processes API data to create a status message."""
    player_name = player_result["player_name"]
    
    if "error" in player_result:
        return f"*{escape_markdown(player_name)}* encountered an error: {escape_markdown(player_result['error'])}"

    data = player_result.get("data", {})
    if not data.get('matches'):
        return f"*{escape_markdown(player_name)}* has no recent matches"

    last_match = data['matches'][0]
    if finished_raw := last_match.get('finished'):
        try:
            utc_dt = datetime.fromisoformat(finished_raw.replace('Z', '+00:00')).replace(tzinfo=pytz.utc)
            local_dt = utc_dt.astimezone(timezone)
            time_str = escape_markdown(local_dt.strftime("%H:%M on %Y-%m-%d"))
            return f"*{escape_markdown(player_name)}* finished playing at {time_str}"
        except ValueError:
            return f"*{escape_markdown(player_name)}* has a match with an invalid finish time"
    else:
        return f"*{escape_markdown(player_name)}* is playing now\\."

async def main():
    """Main function to run the player status checker."""
    config = Config()

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logging.critical("Telegram bot token or chat ID is not configured. Exiting.")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    previous_statuses = load_previous_statuses(config.STATUS_FILE)
    current_statuses: Dict[str, str] = {}
    changed_statuses: List[str] = []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_player_data(session, player) for player in config.PLAYERS]
        results = await asyncio.gather(*tasks)

    for result in results:
        player_name = result["player_name"]
        status_message = process_player_data(result, config.TIMEZONE)
        
        # Store a "clean" version for comparison
        clean_status = status_message.replace('*', '').replace('\\', '')
        current_statuses[player_name] = clean_status
        
        if previous_statuses.get(player_name) != clean_status:
            logging.info(f"Status change for {player_name}: {clean_status}")
            changed_statuses.append(status_message)
        else:
            logging.info(f"No change for {player_name}: {clean_status}")

    save_current_statuses(current_statuses, config.STATUS_FILE)

    if not changed_statuses:
        logging.info("No status changes detected. No messages will be sent.")
        return

    logging.info(f"Sending {len(changed_statuses)} updates to Telegram.")
    full_message = "\n\n".join(changed_statuses)
    
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=full_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logging.info("Successfully sent combined message to Telegram.")
    except TelegramError as e:
        logging.error(f"Failed to send message to Telegram: {e}")

if __name__ == "__main__":
    asyncio.run(main())
