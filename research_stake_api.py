"""
Research script to explore Stake.com affiliate API endpoints
This is for research purposes only - NOT for production use
"""

import requests
import json

# Test API token (for research only)
API_TOKEN = "611c363ec6a762b917580cdc7ff8d0bc3585f552eee20cb31913ae4f11799424423423f2d2fb768a134d999b7ee26389"

# Common API base URLs to try
BASE_URLS = [
    "https://api.stake.com",
    "https://affiliate-api.stake.com",
    "https://api.stake.com/affiliate",
    "https://stake.com/api/affiliate",
]

# Common endpoints to test
ENDPOINTS = [
    "/campaigns",
    "/referrals",
    "/players",
    "/users",
    "/stats",
    "/wagers",
    "/reports",
    "/v1/campaigns",
    "/v1/referrals",
    "/v1/players",
    "/v1/stats",
]

def test_endpoint(base_url, endpoint):
    """Test a specific API endpoint"""
    url = f"{base_url}{endpoint}"
    
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Also try with different auth header formats
    auth_formats = [
        {"Authorization": f"Bearer {API_TOKEN}"},
        {"Authorization": f"Token {API_TOKEN}"},
        {"X-API-Token": API_TOKEN},
        {"X-Access-Token": API_TOKEN},
        {"api-token": API_TOKEN},
    ]
    
    for auth_header in auth_formats:
        headers_test = {**headers, **auth_header}
        
        try:
            response = requests.get(url, headers=headers_test, timeout=10)
            
            if response.status_code != 404:
                print(f"\n✅ SUCCESS: {url}")
                print(f"   Auth: {list(auth_header.keys())[0]}")
                print(f"   Status: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"   Response structure:")
                        print(f"   {json.dumps(data, indent=4)[:500]}...")
                        return True
                    except:
                        print(f"   Response (text): {response.text[:200]}")
                else:
                    print(f"   Response: {response.text[:200]}")
                    
        except requests.exceptions.RequestException as e:
            pass  # Silently continue
            
    return False

def main():
    """Test all combinations of base URLs and endpoints"""
    print("🔍 Researching Stake.com Affiliate API...")
    print("=" * 60)
    
    found_endpoints = []
    
    for base_url in BASE_URLS:
        print(f"\n📡 Testing base URL: {base_url}")
        for endpoint in ENDPOINTS:
            if test_endpoint(base_url, endpoint):
                found_endpoints.append(f"{base_url}{endpoint}")
    
    print("\n" + "=" * 60)
    print(f"\n📊 Summary: Found {len(found_endpoints)} working endpoints")
    for ep in found_endpoints:
        print(f"  • {ep}")
    
    if not found_endpoints:
        print("\n⚠️ No working endpoints found.")
        print("Possible reasons:")
        print("  • API token might be for dashboard access only (not API)")
        print("  • Stake might not have a public affiliate API")
        print("  • API might require different authentication")
        print("  • Need to check Stake's API documentation")

if __name__ == "__main__":
    main()
