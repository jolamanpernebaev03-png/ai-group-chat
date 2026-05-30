"""
Try to get a fresh Uzum token via the actual login/guest flow used by the web app.
"""
import requests
import json

session = requests.Session()

headers_base = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://uzum.uz",
    "Referer": "https://uzum.uz/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
}

# Try various known Uzum auth endpoints
endpoints = [
    ("POST", "https://id.uzum.uz/api/auth/token", {}),
    ("POST", "https://id.uzum.uz/api/auth/guest", {}),
    ("GET",  "https://id.uzum.uz/api/auth/guest", None),
    ("POST", "https://id.uzum.uz/api/v1/auth/guest", {}),
    ("POST", "https://id.uzum.uz/api/v1/auth/token/guest", {}),
    ("POST", "https://id.uzum.uz/api/v2/auth/token/guest", {}),
]

for method, url, body in endpoints:
    try:
        if method == "POST":
            r = session.post(url, headers=headers_base, json=body, timeout=10)
        else:
            r = session.get(url, headers=headers_base, timeout=10)
        print(f"{method} {url}")
        print(f"  Status: {r.status_code} | Body: {r.text[:200]}")
    except Exception as e:
        print(f"{method} {url} -> Error: {e}")

# Also try the GraphQL endpoint with a simple introspection to see what error we get
print("\n--- Testing GraphQL with no auth ---")
gql_headers = {**headers_base,
    "Apollographql-Client-Name": "web-customers",
    "Apollographql-Client-Version": "1.63.2",
    "City-Id": "1",
    "City-Latitude": "41.379112",
    "City-Longitude": "69.29944",
    "Latitude": "41.379112",
    "Longitude": "69.29944",
}
r = session.post(
    "https://graphql.uzum.uz/",
    headers=gql_headers,
    json={"query": "{ __typename }"},
    timeout=10,
)
print(f"  Status: {r.status_code}")
print(f"  Headers: {dict(r.headers)}")
print(f"  Body: {r.text[:400]}")
