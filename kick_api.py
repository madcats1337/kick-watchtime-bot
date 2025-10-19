"""
Kick.com API Integration Module
Handles chatroom ID fetching and API interactions with Kick.com
Uses Playwright with stealth mode to bypass Cloudflare protection
"""

import asyncio
import json
import random
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright
import aiohttp

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

# Referrers for realistic traffic
REFERRERS = [
    "https://www.google.com/",
    "https://twitter.com/",
    "https://www.youtube.com/",
    "https://kick.com/",
]

# Country codes for geolocation
COUNTRY_CODES = ["US", "GB", "CA", "AU", "DE", "FR"]


class KickAPI:
    """Main Kick API class with Playwright-based automation"""
    
    def __init__(self):
        self._browser = None
        self._context = None
        self._stealth_js = """
// Advanced stealth techniques
(() => {
    // Override property descriptors
    const overridePropertyDescriptor = (obj, prop, descriptor) => {
        Object.defineProperty(obj, prop, {
            ...descriptor,
            get: function() {
                return descriptor.value;
            }
        });
    };

    // WebGL fingerprint protection
    const getParameterProxyHandler = {
        apply: function(target, ctx, args) {
            const param = (args || [])[0];
            const result = target.apply(ctx, args);
            
            // Return common WebGL parameters
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel(R) Iris(TM) Graphics 6100';
            
            return result;
        }
    };
    
    if (window.WebGLRenderingContext) {
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = new Proxy(getParameter, getParameterProxyHandler);
    }

    // Permissions API
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );

    // Chrome detection
    overridePropertyDescriptor(navigator, 'webdriver', { value: false });
    overridePropertyDescriptor(navigator, 'plugins', { value: [1, 2, 3, 4, 5] });
    overridePropertyDescriptor(navigator, 'languages', { value: ['en-US', 'en'] });
    
    // Add chrome object
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
})();
"""

    async def setup(self):
        """Initialize the browser and context"""
        if self._browser:
            return
            
        try:
            playwright = await async_playwright().start()
            
            # Try Firefox first (better for Cloudflare bypass)
            try:
                self._browser = await playwright.firefox.launch(
                    headless=True,
                    firefox_user_prefs={
                        "dom.webdriver.enabled": False,
                        "useAutomationExtension": False,
                        "general.platform.override": "Win32",
                        "general.useragent.override": random.choice(USER_AGENTS)
                    }
                )
                print("[Kick] Using Firefox browser")
            except Exception:
                # Fallback to Chromium
                self._browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )
                print("[Kick] Using Chromium browser")
            
            # Create context with stealth settings
            self._context = await self._browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='America/New_York',
                bypass_csp=True,
                ignore_https_errors=True,
                java_script_enabled=True,
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            )
            
            print("[Kick] Browser context initialized")
            
        except Exception as e:
            print(f"[Kick] Error setting up browser: {type(e).__name__}: {str(e)}")
            raise

    async def close(self):
        """Close the browser and cleanup"""
        if self._context:
            try:
                await self._context.close()
            except:
                pass
            self._context = None
            
        if self._browser:
            try:
                await self._browser.close()
            except:
                pass
            self._browser = None

    async def fetch_chatroom_id(self, channel_name: str, max_retries: int = 3) -> Optional[str]:
        """
        Fetch the chatroom ID for a given Kick channel.
        Uses Playwright with stealth mode to bypass Cloudflare protection.
        
        Args:
            channel_name: The Kick channel name
            max_retries: Maximum number of retry attempts
            
        Returns:
            Chatroom ID as string, or None if failed
        """
        await self.setup()
        
        if not self._context:
            print("[Kick] Browser context not available")
            return None
        
        for attempt in range(max_retries):
            page = None
            try:
                print(f"[Kick] Attempt {attempt + 1}/{max_retries}: Fetching chatroom ID for {channel_name}")
                
                # Create new page
                page = await self._context.new_page()
                
                # Add stealth scripts
                await page.add_init_script(self._stealth_js)
                
                # Random delay before navigation
                await asyncio.sleep(random.uniform(0.5, 2))
                
                # Navigate to channel page
                try:
                    response = await page.goto(
                        f"https://kick.com/{channel_name}",
                        wait_until="domcontentloaded",
                        timeout=20000
                    )
                    
                    if not response:
                        print(f"[Kick] No response from navigation")
                        continue
                        
                    if response.status == 404:
                        print(f"[Kick] Channel not found: {channel_name}")
                        return None
                    
                    if response.status == 403:
                        print(f"[Kick] Cloudflare protection detected (403). Waiting longer...")
                        # Wait for Cloudflare challenge to potentially complete
                        await asyncio.sleep(random.uniform(5, 10))
                        try:
                            await page.wait_for_load_state("networkidle", timeout=10000)
                        except:
                            pass
                        # Try to continue anyway
                        
                    if response.status not in [200, 403]:
                        print(f"[Kick] Unexpected status: {response.status}")
                        continue
                        
                except Exception as nav_error:
                    print(f"[Kick] Navigation error: {str(nav_error)}")
                    continue
                
                # Wait for page to settle
                await asyncio.sleep(random.uniform(1, 3))
                
                # Debug: Check page title and content
                page_title = await page.title()
                print(f"[Kick] Page title: {page_title}")
                
                # Try multiple methods to extract chatroom ID
                chatroom_id = await page.evaluate("""() => {
                    // Method 1: Look for chatroom ID in script tags
                    const scripts = document.querySelectorAll('script');
                    for (const script of scripts) {
                        const text = script.textContent || '';
                        
                        // Look for chatroom_id in various formats
                        const patterns = [
                            /"chatroom_id":\s*(\d+)/,
                            /'chatroom_id':\s*(\d+)/,
                            /chatroom_id:\s*(\d+)/,
                            /"chatroomId":\s*(\d+)/,
                            /chatroomId:\s*(\d+)/
                        ];
                        
                        for (const pattern of patterns) {
                            const match = text.match(pattern);
                            if (match) return match[1];
                        }
                    }
                    
                    // Method 2: Check window/global objects
                    if (window.chatroomId) return String(window.chatroomId);
                    if (window.chatroom_id) return String(window.chatroom_id);
                    
                    return null;
                }""")
                
                if chatroom_id:
                    print(f"[Kick] ✅ Found chatroom ID: {chatroom_id}")
                    await page.close()
                    return chatroom_id
                else:
                    # Try alternative method: Fetch from Kick API directly
                    print(f"[Kick] Could not find chatroom ID in page content, trying API endpoint...")
                    try:
                        api_response = await page.evaluate(f"""async () => {{
                            const response = await fetch('https://kick.com/api/v2/channels/{channel_name}');
                            if (response.ok) {{
                                const data = await response.json();
                                return data.chatroom?.id || null;
                            }}
                            return null;
                        }}""")
                        
                        if api_response:
                            print(f"[Kick] ✅ Found chatroom ID from API: {api_response}")
                            await page.close()
                            return api_response
                        else:
                            print(f"[Kick] API endpoint also failed to return chatroom ID")
                    except Exception as api_err:
                        print(f"[Kick] API fetch error: {type(api_err).__name__}: {str(api_err)}")
                    
            except Exception as e:
                print(f"[Kick] Browser error: {type(e).__name__}: {str(e)}")
            finally:
                # Always try to close the page
                if page:
                    try:
                        await page.close()
                    except:
                        pass
            
            if attempt < max_retries - 1:
                # Longer delays to avoid Cloudflare rate limiting
                delay = 5 * (attempt + 1) + random.uniform(3, 7)
                print(f"[Kick] Waiting {delay:.1f} seconds before next attempt...")
                await asyncio.sleep(delay)
        
        # Final fallback: Try direct HTTP request without browser
        print(f"[Kick] All browser attempts failed. Trying direct HTTP request as last resort...")
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'application/json',
                    'Referer': 'https://kick.com/',
                }
                async with session.get(
                    f'https://kick.com/api/v2/channels/{channel_name}',
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        chatroom_id = data.get('chatroom', {}).get('id')
                        if chatroom_id:
                            print(f"[Kick] ✅ Found chatroom ID via HTTP: {chatroom_id}")
                            return str(chatroom_id)
                    print(f"[Kick] HTTP request returned status: {response.status}")
        except Exception as http_err:
            print(f"[Kick] HTTP fallback error: {type(http_err).__name__}: {str(http_err)}")
        
        print(f"[Kick] ❌ Failed to fetch chatroom ID after {max_retries} attempts")
        return None


# Global API instance
_api = None


async def fetch_chatroom_id(channel_name: str, max_retries: int = 3) -> Optional[str]:
    """
    Convenience function to fetch chatroom ID.
    Maintains a global KickAPI instance for reuse.
    
    Args:
        channel_name: The Kick channel name
        max_retries: Maximum number of retry attempts
        
    Returns:
        Chatroom ID as string, or None if failed
    """
    global _api
    
    if not _api:
        _api = KickAPI()
    
    try:
        return await _api.fetch_chatroom_id(channel_name, max_retries)
    except Exception as e:
        print(f"[Kick] Error in fetch_chatroom_id: {type(e).__name__}: {str(e)}")
        # Reset API instance on error
        if _api:
            await _api.close()
        _api = None
        return None


# Export all public interfaces
__all__ = ['KickAPI', 'fetch_chatroom_id', 'USER_AGENTS', 'REFERRERS', 'COUNTRY_CODES']
