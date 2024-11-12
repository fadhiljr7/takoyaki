import asyncio
import cloudscraper
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from loguru import logger
import aiohttp
import backoff

# Constants
PING_INTERVAL = 30
MAX_RETRIES = 60
MAX_CONNECTIONS = 15
REQUEST_TIMEOUT = 10

@dataclass
class ApiEndpoints:
    SESSION: str = "http://18.136.143.169/api/auth/session"
    PING: str = "http://54.255.192.166/api/network/ping"

class ConnectionState:
    CONNECTED = 1
    DISCONNECTED = 2
    NONE_CONNECTION = 3

@dataclass
class BrowserProfile:
    ping_count: int = 0
    successful_pings: int = 0
    score: int = 0
    start_time: float = time.time()
    last_ping_status: str = "Waiting..."
    last_ping_time: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            'ping_count': self.ping_count,
            'successful_pings': self.successful_pings,
            'score': self.score,
            'start_time': self.start_time,
            'last_ping_status': self.last_ping_status,
            'last_ping_time': self.last_ping_time
        }

class NodePayBot:
    def __init__(self):
        self.api = ApiEndpoints()
        self.status_connect = ConnectionState.NONE_CONNECTION
        self.account_info: Dict = {}
        self.browser_profile = BrowserProfile()
        self.token = self._load_token()
        self.scraper = self._create_scraper()
        
    def _load_token(self) -> str:
        """Load authentication token from file with error handling."""
        try:
            with open('Token.txt', 'r') as file:
                return file.read().strip()
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            raise SystemExit("Cannot continue without valid token")

    def _create_scraper(self) -> cloudscraper.CloudScraper:
        """Create and configure cloudscraper instance."""
        return cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

    def _get_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Generate request headers with optional token override."""
        return {
            "Authorization": f"Bearer {token or self.token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://app.nodepay.ai/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://app.nodepay.ai",
            "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cors-site"
        }

    @backoff.on_exception(backoff.expo, 
                         (aiohttp.ClientError, asyncio.TimeoutError),
                         max_tries=3)
    async def call_api(self, url: str, data: Dict, proxy: str, token: Optional[str] = None) -> Dict:
        """Make API calls with automatic retries and better error handling."""
        async with aiohttp.ClientSession(headers=self._get_headers(token)) as session:
            async with session.post(
                url,
                json=data,
                proxy=proxy,
                timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status >= 400:
                    raise aiohttp.ClientError(f"HTTP {response.status}: {await response.text()}")
                
                result = await response.json()
                if not result or "code" not in result or result["code"] < 0:
                    raise ValueError(f"Invalid API response: {result}")
                return result

    async def ping(self, proxy: str) -> None:
        """Send ping request with enhanced error handling and monitoring."""
        try:
            data = {
                "id": self.account_info.get("uid"),
                "browser_id": self.browser_profile.to_dict(),
                "timestamp": int(time.time())
            }

            response = await self.call_api(self.api.PING, data, proxy)
            
            if response["code"] == 0:
                self.browser_profile.successful_pings += 1
                self.browser_profile.last_ping_status = "Success"
                self.status_connect = ConnectionState.CONNECTED
                logger.info(f"Ping successful via proxy {proxy}")
            else:
                await self._handle_ping_failure(proxy, response)
                
        except Exception as e:
            logger.error(f"Ping failed via proxy {proxy}: {e}")
            await self._handle_ping_failure(proxy, None)
        finally:
            self.browser_profile.ping_count += 1
            self.browser_profile.last_ping_time = time.time()

    async def _handle_ping_failure(self, proxy: str, response: Optional[Dict]) -> None:
        """Handle ping failures with appropriate actions."""
        if response and response.get("code") == 403:
            await self._handle_logout(proxy)
        else:
            self.status_connect = ConnectionState.DISCONNECTED
            self.browser_profile.last_ping_status = "Failed"

    async def _handle_logout(self, proxy: str) -> None:
        """Clean up session state on logout."""
        self.token = None
        self.status_connect = ConnectionState.NONE_CONNECTION
        self.account_info = {}
        await self._save_status(proxy, None)
        logger.info(f"Session terminated for proxy {proxy}")

    @staticmethod
    async def _save_status(proxy: str, status: Any) -> None:
        """Save status information (implemented as needed)."""
        pass

    async def start_monitoring(self, proxy: str) -> None:
        """Main monitoring loop with improved error handling."""
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                await self.ping(proxy)
                retry_count = 0  # Reset on successful ping
                
                if self.status_connect == ConnectionState.CONNECTED:
                    await asyncio.sleep(PING_INTERVAL)
                else:
                    await asyncio.sleep(PING_INTERVAL * 2)  # Back off on disconnected state
                    
            except Exception as e:
                retry_count += 1
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(min(PING_INTERVAL * (2 ** retry_count), 300))  # Exponential backoff with max

class ProxyManager:
    def __init__(self, proxy_file: str):
        self.proxy_file = proxy_file
        self.active_proxies: List[str] = []
        self.available_proxies: List[str] = []
        
    async def load_proxies(self) -> None:
        """Load and validate proxies from file."""
        try:
            with open(self.proxy_file, 'r') as file:
                self.available_proxies = file.read().splitlines()
            logger.info(f"Loaded {len(self.available_proxies)} proxies")
        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
            raise SystemExit("Cannot continue without valid proxies")

    async def get_next_proxy(self) -> Optional[str]:
        """Get next available proxy with validation."""
        while self.available_proxies:
            proxy = self.available_proxies.pop(0)
            if await self.validate_proxy(proxy):
                return proxy
        return None

    async def validate_proxy(self, proxy: str) -> bool:
        """Validate proxy functionality."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'http://httpbin.org/ip',
                    proxy=proxy,
                    timeout=5
                ) as response:
                    return response.status == 200
        except:
            return False

async def main():
    proxy_manager = ProxyManager('Proxy.txt')
    await proxy_manager.load_proxies()
    
    bots: Dict[str, NodePayBot] = {}
    tasks = set()

    async def start_bot(proxy: str):
        try:
            bot = NodePayBot()
            bots[proxy] = bot
            await bot.start_monitoring(proxy)
        except Exception as e:
            logger.error(f"Bot failed for proxy {proxy}: {e}")
            return proxy

    while True:
        # Maintain desired number of connections
        while len(tasks) < MAX_CONNECTIONS:
            proxy = await proxy_manager.get_next_proxy()
            if not proxy:
                break
            task = asyncio.create_task(start_bot(proxy))
            tasks.add(task)

        if not tasks:
            logger.warning("No active tasks remaining")
            break

        done, pending = await asyncio.wait(
            tasks, 
            return_when=asyncio.FIRST_COMPLETED,
            timeout=60
        )

        for task in done:
            tasks.remove(task)
            try:
                failed_proxy = task.result()
                if failed_proxy and failed_proxy in bots:
                    del bots[failed_proxy]
            except Exception as e:
                logger.error(f"Task failed with error: {e}")

        await asyncio.sleep(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user")