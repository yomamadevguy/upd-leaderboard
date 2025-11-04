import os
import requests, json, time
from datetime import datetime

# Load from GitHub Secrets
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Fail fast if missing
if not all([DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing required environment variables!")

INVITE_CODES = [
    "UvVGCEXhE4",
    "eQeJjnd8Ck",
    "mPqZVrTVeg",
    "ZwnNJkJapr",
    "dAZDq4KQ8R",
    "VjU4Y9qRDB",
    "NhAXyvdCw8",
    "rAPkgvQEUm",
    "jTnCD2Fjq6",
    "K2uxg2PAmq",
    "JXN2zAsN4q",
    "fRVPQWwdMb",
    "KZj8evgbbf",
    "WynuG77Wnw",
    "EHndFgbShQ",
    "pPnzW2skhC",
    "fYGt5nTrc8",
    "G4BCqEt9zm",
    "xgWZwvtu5c",
    "x8aXAA2bhc",
    "WRfbdnWSms",
    "QaAnEsD2dw",
    "syCCeXJ6ja",
    "uVetkeSaR3",
    "aV8w98WCEU",
    "HgDZ7yRj4m",
    "TXx7tDnVM8",
    "rP5tF4XpyH",
    "e6cdeW6fGY",
    "PwjsTtg4KC",
    "9zbWby8pJx"
]

def fetch_invite_info(code):
    """Fetch invite information from Discord."""
    print(f"Fetching invite info for code: {code}")
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=true"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            guild = data.get('guild', {})
            # NEW: description & online count
            return {
                'guild_id': int(guild.get('id')) if guild.get('id') else None,
                'server_name': guild.get('name'),
                'server_desc': guild.get('description'),          # <-- NEW
                'member_count': data.get('approximate_member_count'),
                'online_count': data.get('approximate_presence_count'),
                'icon_hash': guild.get('icon'),
                'banner_hash': guild.get('banner') # <-- NEW
            }
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"Rate limited, retrying after {retry_after} seconds")
            time.sleep(retry_after)
            return fetch_invite_info(code)
        else:
            print(f"Error fetching invite {code}: {response.status_code} - {response.text}")
            return None
    except requests.RequestException as e:
        print(f"Error fetching invite {code}: {e}")
        return None

def insert_to_supabase(data):
    """Insert or update data in Supabase."""
    print(f"Upserting data for guild {data['guild_id']}")
    url = f"{SUPABASE_URL}/rest/v1/leaderboardmain"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"  # Enable upsert
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code in (200, 201):
            print(f"Data for guild {data['guild_id']} upserted successfully.")
            return True
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"Rate limited, retrying after {retry_after} seconds")
            time.sleep(retry_after)
            return insert_to_supabase(data)
        else:
            print(f"Error upserting data: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        print(f"Error upserting data: {e}")
        return False

def get_messages(channel_id, limit=1):
    """Fetch a single message from the specified channel."""
    print(f"Fetching messages from channel {channel_id}")
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print(f"Successfully fetched {len(response.json())} messages")
            return response.json()
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"Rate limited, retrying after {retry_after} seconds")
            time.sleep(retry_after)
            return get_messages(channel_id, limit)
        else:
            print(f"Error fetching messages: {response.status_code} {response.text}")
            return []
    except requests.RequestException as e:
        print(f"Error fetching messages: {e}")
        return []

def delete_message(channel_id, message_id):
    """Delete a single message by its ID."""
    print(f"Deleting message {message_id} from channel {channel_id}")
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            print("Successfully deleted the previous leaderboard message")
            return True
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"Rate limited, retrying after {retry_after} seconds")
            time.sleep(retry_after)
            return delete_message(channel_id, message_id)
        else:
            print(f"Error deleting message: {response.status_code} {response.text}")
            return False
    except requests.RequestException as e:
        print(f"Error deleting message: {e}")
        return False

def clear_channel(channel_id):
    """Delete the single message in the channel."""
    print(f"Attempting to clear channel {channel_id}")
    messages = get_messages(channel_id, limit=1)
    if not messages:
        print("No messages found in the channel")
        return True  # No message to delete, proceed with posting
    message_id = messages[0]["id"]
    return delete_message(channel_id, message_id)

def fetch_leaderboard(limit=10):
    """Fetch leaderboard data from Supabase."""
    print("Fetching leaderboard data from Supabase")
    # NEW: also select the description and online count
    url = f"{SUPABASE_URL}/rest/v1/leaderboardmain?select=guild_id,server_name,server_desc,member_count,online_count&order=member_count.desc&limit={limit}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        print(f"Successfully fetched {len(response.json())} leaderboard entries")
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching leaderboard: {e}")
        return []

def send_leaderboard_to_discord(leaderboard_data):
    """Send leaderboard data to Discord as an embed."""
    print(f"Sending leaderboard to Discord channel {DISCORD_CHANNEL_ID}")
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    medals = {1: ":first_place:", 2: ":second_place:", 3: ":third_place:"}
    
    embed = {
        "title": "Server Leaderboard",
        "description": "Top Spawnism servers by member count.",
        "color": 0xFFFFFF,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Last updated"},
        "fields": [
            {
                "name": f"{medals.get(i, ':medal:')} {i}. {entry['server_name']}",
                # NEW: show description (if any) and online count
                "value": (
                    f"> Members: {entry['member_count']}\n"
                    f"> Online: {entry.get('online_count', 'N/A')}\n"
                    f"> Guild ID: {entry['guild_id']}"
                ),
                "inline": False
            } for i, entry in enumerate(leaderboard_data, 1)
        ]
    }
    payload = {"embeds": [embed]}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print(f"Leaderboard sent to Discord channel {DISCORD_CHANNEL_ID}")
    except requests.RequestException as e:
        print(f"Error sending leaderboard to Discord: {e}")

def main():
    print("Starting main function")
    if not all([DISCORD_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, DISCORD_CHANNEL_ID]) or \
       any(x.startswith("YOUR_") for x in [DISCORD_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, DISCORD_CHANNEL_ID]):
        print("Missing or invalid environment variables. Set DISCORD_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, and DISCORD_CHANNEL_ID.")
        return

    # Update database with invite info
    print("Updating database with invite information")
    for code in INVITE_CODES:
        info = fetch_invite_info(code)
        if info and info['guild_id']:
            current_timestamp = datetime.utcnow().isoformat()
            payload = {
                "guild_id": info['guild_id'],
                "server_name": info['server_name'],
                "server_desc": info.get('server_desc'),          # <-- NEW
                "member_count": info['member_count'],
                "online_count": info.get('online_count'),        
                "icon_hash": info.get('icon_hash'),
                "banner_hash": info.get('banner_hash'),
                "last_updated": current_timestamp
            }
            insert_to_supabase(payload)
        else:
            print(f"Skipping invalid invite: {code}")

    # Clear the previous leaderboard message
    print("Clearing previous leaderboard message")
    if not clear_channel(DISCORD_CHANNEL_ID):
        print("Failed to clear the channel, stopping")
        return

    # Fetch and send the new leaderboard
    print("Fetching and sending new leaderboard")
    leaderboard_data = fetch_leaderboard(limit=10)
    if leaderboard_data:
        send_leaderboard_to_discord(leaderboard_data)
    else:
        print("No leaderboard data to send.")

if __name__ == "__main__":
    print("Script is running as main module")
    main()
