"""
The /api/auth/token endpoint returns 204 (success, no content).
It likely sets cookies. Let's capture those cookies and use them.
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

# Step 1: Hit the auth/token endpoint (returns 204 + sets cookies)
print("Step 1: POST /api/auth/token ...")
r = session.post(
    "https://id.uzum.uz/api/auth/token",
    headers=headers_base,
    json={},
    timeout=15,
)
print(f"  Status: {r.status_code}")
print(f"  Response headers:")
for k, v in r.headers.items():
    print(f"    {k}: {v}")
print(f"  Cookies set: {session.cookies.get_dict()}")

# Step 2: Try to get a token with the session cookies
print("\nStep 2: GET /api/auth/token ...")
r2 = session.get(
    "https://id.uzum.uz/api/auth/token",
    headers=headers_base,
    timeout=15,
)
print(f"  Status: {r2.status_code}")
print(f"  Body: {r2.text[:500]}")
print(f"  Cookies: {session.cookies.get_dict()}")

# Step 3: Try to refresh/get token
print("\nStep 3: POST /api/auth/token/refresh ...")
r3 = session.post(
    "https://id.uzum.uz/api/auth/token/refresh",
    headers=headers_base,
    json={},
    timeout=15,
)
print(f"  Status: {r3.status_code}")
print(f"  Body: {r3.text[:500]}")
print(f"  Response headers:")
for k, v in r3.headers.items():
    if any(x in k.lower() for x in ["cookie", "token", "auth", "set"]):
        print(f"    {k}: {v}")

# Step 4: Now try GraphQL with the session cookies
print("\nStep 4: Testing GraphQL with session cookies...")
gql_headers = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU",
    "Apollographql-Client-Name": "web-customers",
    "Apollographql-Client-Version": "1.63.2",
    "City-Id": "1",
    "City-Latitude": "41.379112",
    "City-Longitude": "69.29944",
    "Content-Type": "application/json",
    "Latitude": "41.379112",
    "Longitude": "69.29944",
    "Origin": "https://uzum.uz",
    "Referer": "https://uzum.uz/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
}

query = """query MakeSearch_ItemsAndFilters($queryInput: MakeSearchQueryInput!) {
  makeSearch(query: $queryInput) {
    items {
      catalogCard {
        id
        productId
        title
        minFullPrice
        minSellPrice
        feedbackQuantity
        rating
        __typename
      }
      __typename
    }
    total
    __typename
  }
}"""

payload = {
    "operationName": "MakeSearch_ItemsAndFilters",
    "query": query,
    "variables": {"queryInput": {
        "categoryId": 10012,
        "showAdultContent": False,
        "filters": [],
        "sort": "BY_ORDERS_QUANTITY_DESC",
        "pagination": {"offset": 0, "limit": 3},
    }},
}

r4 = session.post("https://graphql.uzum.uz/", headers=gql_headers, json=payload, timeout=15)
print(f"  Status: {r4.status_code}")
print(f"  Body: {r4.text[:600]}")

# Print the cookie string we can use
print("\n=== COOKIE STRING FOR uzum_analyzer.py ===")
cookie_str = "; ".join([f"{k}={v}" for k, v in session.cookies.get_dict().items()])
print(cookie_str)

# Check if access_token cookie was set
access_token = session.cookies.get("access_token")
if access_token:
    print(f"\n✅ ACCESS TOKEN: {access_token[:100]}...")
else:
    print("\n❌ No access_token cookie found")
