import asyncio
import aiohttp
import time
import uuid
import cloudscraper
from loguru import logger
from fake_useragent import UserAgent
import os
from datetime import datetime
from urllib.parse import urlparse, unquote

# Constants
PING_INTERVAL = 60
RETRIES = 60
TOKEN_FILE = "Token.txt"

DOMAIN_API = {
    "SESSION": "http://api.nodepay.ai/api/auth/session",
    "PING": "http://52.77.10.116/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

class NodePayBot:
    def __init__(self):
        self.status_connect = CONNECTION_STATES["NONE_CONNECTION"]
        self.browser_id = None
        self.account_info = {}
        self.last_ping_time = {}
        self.token = None
        self.active_connections = set()
        
    def load_token(self):
        try:
            if not os.path.exists(TOKEN_FILE):
                logger.error(f"Token file '{TOKEN_FILE}' not found!")
                raise SystemExit(1)
                
            with open(TOKEN_FILE, 'r') as file:
                self.token = file.read().strip()
                if not self.token:
                    logger.error("Token file is empty!")
                    raise SystemExit(1)
                    
            logger.info(f"Loaded token starting with: {self.token[:5]}...")
            return self.token
        except Exception as e:
            logger.error(f"Error loading token: {e}")
            raise SystemExit(1)

    def uuidv4(self):
        return str(uuid.uuid4())
    
    def valid_resp(self, resp):
        if not resp or "code" not in resp or resp["code"] < 0:
            raise ValueError("Invalid response")
        return resp

    def parse_proxy(self, proxy_url):
        """Parse proxy URL with authentication."""
        try:
            parsed = urlparse(proxy_url)
            auth_part = parsed.netloc.split('@')[0]
            username, password = auth_part.split(':')
            host_part = parsed.netloc.split('@')[1]
            
            return {
                'username': unquote(username),
                'password': unquote(password),
                'host': host_part,
                'proxy_url': f"http://{host_part}"
            }
        except Exception as e:
            logger.error(f"Error parsing proxy URL {proxy_url}: {e}")
            return None
    
    async def call_api(self, url, data, proxy_url):
        try:
            proxy_info = self.parse_proxy(proxy_url)
            if not proxy_info:
                raise ValueError(f"Invalid proxy format: {proxy_url}")

            user_agent = UserAgent(os=['windows', 'macos', 'linux'], browsers='chrome')
            random_user_agent = user_agent.random
            headers = {
                "Authorization": f"Bearer {self.token}",
                "User-Agent": random_user_agent,
                "Content-Type": "application/json",
                "Origin": "chrome-extension://lgmpfmgeabnnlemejacfljbmonaomfmm",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Proxy-Authorization": aiohttp.BasicAuth(
                    proxy_info['username'],
                    proxy_info['password']
                )
            }

            proxy_auth = aiohttp.BasicAuth(proxy_info['username'], proxy_info['password'])
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    proxy=proxy_info['proxy_url'],
                    proxy_auth=proxy_auth,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return self.valid_resp(result)

        except aiohttp.ClientError as e:
            logger.error(f"Network error during API call to {url}: {e}")
            raise ValueError(f"Failed API call to {url}")
        except Exception as e:
            logger.error(f"Error during API call to {url}: {e}")
            raise ValueError(f"Failed API call to {url}")

    async def render_profile_info(self, proxy):
        try:
            np_session_info = self.load_session_info(proxy)

            if not np_session_info:
                self.browser_id = self.uuidv4()
                response = await self.call_api(DOMAIN_API["SESSION"], {}, proxy)
                self.valid_resp(response)
                self.account_info = response["data"]
                
                if self.account_info.get("uid"):
                    self.save_session_info(proxy, self.account_info)
                    self.active_connections.add(proxy)
                    await self.start_ping(proxy)
                else:
                    self.handle_logout(proxy)
            else:
                self.account_info = np_session_info
                self.active_connections.add(proxy)
                await self.start_ping(proxy)
                
        except Exception as e:
            logger.error(f"Error in render_profile_info for proxy {proxy}: {e}")
            error_message = str(e)
            if any(phrase in error_message for phrase in [
                "sent 1011 (internal error) keepalive ping timeout",
                "500 Internal Server Error",
                "Failed API call"
            ]):
                logger.info(f"Removing error proxy from list: {proxy}")
                self.remove_proxy_from_list(proxy)
                return None
            return proxy

    async def start_ping(self, proxy):
        try:
            while proxy in self.active_connections:
                await self.ping(proxy)
                await asyncio.sleep(PING_INTERVAL)
        except asyncio.CancelledError:
            logger.info(f"Ping task cancelled for proxy {proxy}")
        except Exception as e:
            logger.error(f"Error in start_ping for proxy {proxy}: {e}")
            self.active_connections.remove(proxy)

    async def ping(self, proxy):
        current_time = time.time()

        if proxy in self.last_ping_time and (current_time - self.last_ping_time[proxy]) < PING_INTERVAL:
            return

        self.last_ping_time[proxy] = current_time

        try:
            data = {
                "id": self.account_info.get("uid"),
                "browser_id": self.browser_id,
                "timestamp": int(current_time),
                "version": "2.2.7"
            }

            response = await self.call_api(DOMAIN_API["PING"], data, proxy)
            if response["code"] == 0:
                logger.info(f"Ping successful via proxy {proxy}")
                self.status_connect = CONNECTION_STATES["CONNECTED"]
            else:
                self.handle_ping_fail(proxy, response)
        except Exception as e:
            logger.error(f"Ping failed via proxy {proxy}: {e}")
            self.handle_ping_fail(proxy, None)

    def handle_ping_fail(self, proxy, response):
        if response and response.get("code") == 403:
            self.handle_logout(proxy)
        else:
            self.status_connect = CONNECTION_STATES["DISCONNECTED"]

    def handle_logout(self, proxy):
        self.status_connect = CONNECTION_STATES["NONE_CONNECTION"]
        self.account_info = {}
        if proxy in self.active_connections:
            self.active_connections.remove(proxy)
        self.save_status(proxy, None)
        logger.info(f"Logged out and cleared session for proxy {proxy}")

    def load_proxies(self, proxy_file):
        try:
            with open(proxy_file, 'r') as file:
                return [line.strip() for line in file if line.strip()]
        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
            raise SystemExit(1)

    def save_status(self, proxy, status):
        # Implement status saving logic here if needed
        pass

    def save_session_info(self, proxy, data):
        # Implement session info saving logic here if needed
        pass

    def load_session_info(self, proxy):
        # Implement session info loading logic here if needed
        return {}

    def is_valid_proxy(self, proxy):
        try:
            proxy_info = self.parse_proxy(proxy)
            return proxy_info is not None
        except:
            return False

    def remove_proxy_from_list(self, proxy):
        if proxy in self.active_connections:
            self.active_connections.remove(proxy)

    async def main(self):
        logger.info("Starting NodePay Bot...")
        logger.info(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        all_proxies = self.load_proxies('local_proxies.txt')
        active_proxies = [proxy for proxy in all_proxies if self.is_valid_proxy(proxy)][:100]
        
        if not active_proxies:
            logger.error("No valid proxies found!")
            return

        logger.info(f"Loaded {len(active_proxies)} valid proxies")

        while True:
            tasks = []
            for proxy in active_proxies:
                if proxy not in self.active_connections:
                    task = asyncio.create_task(self.render_profile_info(proxy))
                    tasks.append(task)

            if tasks:
                completed, _ = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
                for task in completed:
                    if task.result() is None:
                        proxy = next((p for p in active_proxies if p not in self.active_connections), None)
                        if proxy:
                            active_proxies.remove(proxy)
                            if all_proxies:
                                new_proxy = all_proxies.pop(0)
                                if self.is_valid_proxy(new_proxy):
                                    active_proxies.append(new_proxy)

            await asyncio.sleep(3)

if __name__ == '__main__':
    bot = NodePayBot()
    try:
        bot.load_token()
        asyncio.run(bot.main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
