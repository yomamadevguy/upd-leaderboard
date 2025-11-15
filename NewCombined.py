import requests, json, time
import datetime
import os

# Load from environment (like NewCombined)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Fail fast if missing
if not all([DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing required environment variables!")

SUPABASE_URL = SUPABASE_URL.rstrip("/")
TABLE_URL = f"{SUPABASE_URL}/rest/v1/leaderboardmain"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

DELAY_BETWEEN_CALLS = 1.0  # seconds


# ===============================================
# Helper: UTC ISO timestamp
# ===============================================
def now_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()


# ===============================================
# 1. Get all invite codes from Supabase
# ===============================================
def get_all_invite_codes():
    print("Fetching all invite codes from leaderboardmain...")
    response = requests.get(
        TABLE_URL,
        headers=HEADERS,
        params={"select": "invite_code", "invite_code": "not.is.null"}
    )
    
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch invites: {response.status_code} {response.text}")
    
    data = response.json()
    codes = [row["invite_code"] for row in data if row["invite_code"]]
    print(f"Found {len(codes)} invite code(s): {codes}")
    return codes


# ===============================================
# 2. Fetch Discord invite data
# ===============================================
def fetch_discord_invite(invite_code):
    url = f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true"
    # Use bot token for authenticated rate limits (better than public)
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 404:
        print(f"Warning: Invite '{invite_code}' is invalid or expired (404). Skipping.")
        return None
    if resp.status_code == 429:
        retry_after = resp.json().get("retry_after", 5)
        print(f"Rate limited. Waiting {retry_after}s...")
        time.sleep(retry_after)
        return fetch_discord_invite(invite_code)
    if resp.status_code != 200:
        print(f"Warning: Discord API error {resp.status_code} for '{invite_code}'. Skipping.")
        return None
    return resp.json()


# ===============================================
# 3. Build payload
# ===============================================
def build_payload(invite_code, data):
    if not data or "guild" not in data:
        return None
    
    guild = data["guild"]
    return {
        "guild_id": guild.get("id"),
        "invite_code": invite_code,
        "server_name": guild.get("name"),
        "server_desc": guild.get("description"),
        "member_count": data.get("approximate_member_count"),
        "online_count": data.get("approximate_presence_count"),
        "icon_hash": guild.get("icon"),
        "banner_hash": guild.get("banner"),
        "last_updated": now_iso()
    }


# ===============================================
# 4. Upsert into Supabase by guild_id
# ===============================================
def upsert_server(payload):
    if not payload or not payload.get("guild_id"):
        return False

    resp = requests.post(
        TABLE_URL,
        headers=HEADERS,
        json=payload,
        params={"on_conflict": "guild_id"}
    )
    
    if resp.status_code in (200, 201):
        print(f"Updated: {payload['server_name']} (Guild ID: {payload['guild_id']})")
        return True
    elif resp.status_code == 429:
        retry_after = resp.json().get("retry_after", 5)
        print(f"Supabase rate limited. Retrying after {retry_after}s...")
        time.sleep(retry_after)
        return upsert_server(payload)
    else:
        print(f"Failed to upsert {payload.get('guild_id')}: {resp.status_code} {resp.text}")
        return False


# ===============================================
# 5. Discord: Clear old message
# ===============================================
def clear_channel(channel_id):
    print(f"Clearing previous message in channel {channel_id}...")
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=1"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 1)
            time.sleep(retry_after)
            return clear_channel(channel_id)
        if resp.status_code == 200 and resp.json():
            msg = resp.json()[0]
            delete_url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{msg['id']}"
            del_resp = requests.delete(delete_url, headers=headers)
            if del_resp.status_code == 204:
                print("Old leaderboard message deleted.")
                return True
            else:
                print(f"Failed to delete message: {del_resp.status_code}")
        return True  # No message or already clean
    except Exception as e:
        print(f"Error clearing channel: {e}")
        return False


# ===============================================
# 6. Fetch leaderboard from Supabase
# ===============================================
def fetch_leaderboard(limit=10):
    print(f"Fetching top {limit} servers from Supabase...")
    url = f"{TABLE_URL}?select=guild_id,server_name,server_desc,member_count,online_count&order=member_count.desc&limit={limit}"
    try:
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        print(f"Fetched {len(data)} leaderboard entries.")
        return data
    except Exception as e:
        print(f"Error fetching leaderboard: {e}")
        return []


# ===============================================
# 7. Post leaderboard to Discord
# ===============================================
def send_leaderboard_to_discord(leaderboard_data):
    print(f"Posting leaderboard to Discord channel {DISCORD_CHANNEL_ID}...")
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    medals = {1: ":first_place:", 2: ":second_place:", 3: ":third_place:"}
    
    fields = []
    for i, entry in enumerate(leaderboard_data, 1):
        medal = medals.get(i, ":medal:")
        fields.append({
            "name": f"{medal} {i}. {entry['server_name']}",
            "value": (
                f"> **Members:** {entry['member_count']}\n"
                f"> **Online:** {entry.get('online_count', 'N/A')}\n"
                f"> **ID:** `{entry['guild_id']}`"
            ),
            "inline": False
        })
    
    embed = {
        "title": "🏆 Server Leaderboard 🏆",
        "description": "Top Spawnism servers by member count.",
        "color": 0x00FFFF,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "footer": {"text": "Last updated"},
        "fields": fields
    }
    
    try:
        resp = requests.post(url, headers=headers, json={"embeds": [embed]})
        if resp.status_code == 200:
            print("Leaderboard posted successfully!")
        elif resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 1)
            print(f"Rate limited. Retrying after {retry_after}s...")
            time.sleep(retry_after)
            return send_leaderboard_to_discord(leaderboard_data)
        else:
            print(f"Failed to post leaderboard: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Error sending to Discord: {e}")


# ===============================================
# Main sync loop + leaderboard post
# ===============================================
def sync_all_servers():
    invite_codes = get_all_invite_codes()
    if not invite_codes:
        print("No invite codes found. Exiting.")
        return

    updated_count = 0
    for i, code in enumerate(invite_codes, 1):
        print(f"\n[{i}/{len(invite_codes)}] Processing invite: {code}")
        data = fetch_discord_invite(code)
        if not data:
            time.sleep(DELAY_BETWEEN_CALLS)
            continue
        
        payload = build_payload(code, data)
        if payload and upsert_server(payload):
            updated_count += 1
        
        time.sleep(DELAY_BETWEEN_CALLS)

    print(f"\nSync complete. Updated {updated_count}/{len(invite_codes)} servers.")

    # === NEW: Post leaderboard to Discord ===
    print("\nPosting updated leaderboard to Discord...")
    if not clear_channel(DISCORD_CHANNEL_ID):
        print("Warning: Could not clear old message. Continuing anyway...")
    
    leaderboard = fetch_leaderboard(limit=10)
    if leaderboard:
        send_leaderboard_to_discord(leaderboard)
    else:
        print("No leaderboard data to display.")


# ===============================================
# Entry point
# ===============================================
if __name__ == "__main__":
    try:
        sync_all_servers()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print(f"Unexpected error: {e}")
