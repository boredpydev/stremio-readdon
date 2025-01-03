import aiohttp
import asyncio
import json
import csv
import os

# Constants
LOGIN_URL = 'https://api.strem.io/api/login'
ADDON_COLLECTION_GET_URL = 'https://api.strem.io/api/addonCollectionGet'
ADDON_COLLECTION_SET_URL = 'https://api.strem.io/api/addonCollectionSet'

HEADERS = {'Content-Type': 'application/json'}
CUSTOM_ADDONS_FILE = r'custom_addons.json'
LOGIN_CSV_FILE = r'stremio_logins.csv'  # CSV file for account info

# Default addons (safe to keep)
DEFAULT_ADDONS = {
    "com.linvo.cinemeta",
    "org.stremio.opensubtitlesv3",
    "org.stremio.opensubtitles",
    "org.stremio.local"
}


async def log_action(email, message):
    """Logs actions for each email."""
    with open('stremio_log.txt', 'a') as log_file:
        log_file.write(f"[{email}] {message}\n")
    print(f"[{email}] {message}")  # Print logs to console


async def fetch_manifest(url, session):
    """Fetches addon manifest data from a given transport URL."""
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            manifest = await response.json()
            await log_action("INIT", f"Fetched manifest from {url}.")
            return manifest
    except Exception as e:
        await log_action("INIT", f"Failed to fetch manifest from {url}. Error: {str(e)}")
        return None


async def load_custom_addons():
    """Loads custom addons from JSON or initializes them if the file doesn't exist."""
    if os.path.exists(CUSTOM_ADDONS_FILE):
        with open(CUSTOM_ADDONS_FILE, 'r') as file:
            return json.load(file)

    custom_addons = []
    print("No custom addons found. Enter addon URLs (type 'done' to finish):")

    async with aiohttp.ClientSession() as session:
        while True:
            url = input("Paste addon URL (or type 'done' to finish): ").strip()
            if url.lower() == 'done':
                break

            # Replace /configure with /manifest.json
            if url.endswith('/configure'):
                url = url.replace('/configure', '/manifest.json')
                print(f"Updated URL to: {url}")

            # Fetch manifest data
            manifest = await fetch_manifest(url, session)
            if manifest:
                addon = {
                    "manifest": manifest,
                    "transportUrl": url,
                    "flags": manifest.get("flags", {"official": False, "protected": False})
                }
                custom_addons.append(addon)
                print(f"Added addon: {manifest.get('name', 'Unknown')}")
            else:
                print("Invalid addon URL. Try again.")

    # Save custom addons to JSON file
    with open(CUSTOM_ADDONS_FILE, 'w') as file:
        json.dump(custom_addons, file, indent=4)
    return custom_addons


async def login_and_get_auth(email, password, session):
    """Logs into Stremio and returns authKey."""
    payload = {'type': 'Login', 'email': email, 'password': password, 'facebook': False}
    async with session.post(LOGIN_URL, headers=HEADERS, json=payload) as response:
        response.raise_for_status()
        data = await response.json()
        return data['result']['authKey']


async def get_addons(auth_key, session):
    """Fetches current addon collection."""
    payload = {'authKey': auth_key, 'type': 'AddonCollectionGet', 'update': True}
    async with session.post(ADDON_COLLECTION_GET_URL, headers=HEADERS, json=payload) as response:
        response.raise_for_status()
        data = await response.json()
        return data['result']['addons']


async def update_addons(auth_key, addons, session):
    """Updates the addon collection for a given account."""
    payload = {
        'authKey': auth_key,
        'type': 'AddonCollectionSet',
        'addons': addons
    }
    async with session.post(ADDON_COLLECTION_SET_URL, headers=HEADERS, json=payload) as response:
        response.raise_for_status()
        await log_action("UPDATE", "Addons updated successfully.")


async def write_csv(login_data):
    """Writes updated auth tokens to CSV."""
    with open(LOGIN_CSV_FILE, 'w', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['email', 'password', 'auth_token'])
        for email, data in login_data.items():
            writer.writerow([email, data['password'], data['auth_token']])


async def clone_addons(email, password):
    """Clones addons from a given account."""
    try:
        async with aiohttp.ClientSession() as session:
            # Authenticate and fetch addons
            auth_key = await login_and_get_auth(email, password, session)
            addons = await get_addons(auth_key, session)

            # Filter non-default and non-Trakt addons
            custom_addons = [
                addon for addon in addons if addon['manifest']['id'] not in DEFAULT_ADDONS and
                "trakt" not in addon['manifest']['id'].lower()
            ]

            # Save cloned addons to custom_addons.json
            with open(CUSTOM_ADDONS_FILE, 'w') as file:
                json.dump(custom_addons, file, indent=4)

            cloned_addon_names = [addon['manifest']['name'] for addon in custom_addons]
            await log_action(email, f"Cloned addons: {', '.join(cloned_addon_names)}.")
            print(f"Cloned addons saved to {CUSTOM_ADDONS_FILE}.")

    except Exception as e:
        print(f"Error cloning addons: {str(e)}")


async def process_account(email, password, auth_key, login_data, session, custom_addons):
    """Processes each Stremio account asynchronously."""
    try:
        # Authenticate using stored auth token or login
        if not auth_key:
            await log_action(email, "No token. Logging in...")
            auth_key = await login_and_get_auth(email, password, session)
            login_data[email]['auth_token'] = auth_key
            await write_csv(login_data)  # Write updated token immediately

        # Fetch current addons
        addons = await get_addons(auth_key, session)

        # Process addons (keep defaults and Trakt addons, add custom ones)
        updated_addons = [addon for addon in addons if addon['manifest']['id'] in DEFAULT_ADDONS or
                          "trakt" in addon['manifest']['id'].lower()]
        updated_addons += custom_addons
        await update_addons(auth_key, updated_addons, session)
        await log_action(email, "Processed addons successfully.")

    except Exception as e:
        await log_action(email, f"Error: {str(e)}")


async def main():
    """Main function to process all logins."""
    print("[1] Process accounts.")
    print("[2] Clone addons from an account.")
    option = input("Choose an option: ")

    if option == "2":
        email = input("Enter email of account to clone: ")
        password = input("Enter password: ")
        await clone_addons(email, password)
        return

    login_data = {}
    custom_addons = await load_custom_addons()

    # Read login data
    with open(LOGIN_CSV_FILE, 'r') as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            login_data[row['email']] = {'password': row['password'], 'auth_token': row.get('auth_token', '')}

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_account(email, data['password'], data['auth_token'], login_data, session, custom_addons)
            for email, data in login_data.items()
        ]
        await asyncio.gather(*tasks)

    await write_csv(login_data)


if __name__ == "__main__":
    asyncio.run(main())
