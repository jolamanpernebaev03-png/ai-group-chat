"""
This script gets a fresh guest token from Uzum and then tests the GraphQL API.
Run this to get a new working token.
"""
import requests
import json

headers_base = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU",
    "Content-Type": "application/json",
    "Origin": "https://uzum.uz",
    "Referer": "https://uzum.uz/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
}

# Step 1: Get a guest token from Uzum auth
print("Step 1: Getting guest token from Uzum...")
try:
    r = requests.post(
        "https://id.uzum.uz/api/auth/token/guest",
        headers=headers_base,
        json={},
        timeout=15,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.text[:500]}")
    if r.status_code == 200:
        data = r.json()
        token = data.get("access_token") or data.get("token") or data.get("accessToken")
        print(f"\n✅ Got token: {token[:80] if token else 'NOT FOUND in response'}...")
        print(f"\nFull response keys: {list(data.keys())}")
except Exception as e:
    print(f"  Error: {e}")

# Step 2: Try alternative guest auth endpoint
print("\nStep 2: Trying alternative guest auth...")
try:
    r2 = requests.post(
        "https://id.uzum.uz/api/auth/anonymous",
        headers=headers_base,
        json={},
        timeout=15,
    )
    print(f"  Status: {r2.status_code}")
    print(f"  Response: {r2.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# Step 3: Try the main site to see what auth it uses
print("\nStep 3: Checking uzum.uz main page headers...")
try:
    r3 = requests.get(
        "https://uzum.uz/ru/",
        headers=headers_base,
        timeout=15,
        allow_redirects=True,
    )
    print(f"  Status: {r3.status_code}")
    # Look for any set-cookie headers
    for k, v in r3.headers.items():
        if "cookie" in k.lower() or "token" in k.lower() or "auth" in k.lower():
            print(f"  Header {k}: {v[:100]}")
    cookies = r3.cookies.get_dict()
    print(f"  Cookies: {list(cookies.keys())}")
except Exception as e:
    print(f"  Error: {e}")
