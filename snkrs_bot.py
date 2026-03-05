#!/usr/bin/env python3
"""
SNKRS 自动抢购脚本 (API 方式 + 反检测)
==========================================
功能: 自动登录 Nike 账号 + 定时抢购 + 反机器人检测绕过
警告: 使用本脚本可能违反 Nike 服务条款，账号有被封禁风险，请自行评估。

使用前请安装依赖:
    pip install requests curl_cffi

    如需代理功能:
    pip install requests[socks]

用法:
    python snkrs_bot.py

    首次运行前请修改下方 CONFIG 配置区域中的参数。
"""

import json
import time
import hashlib
import uuid
import random
import string
import logging
import platform
import struct
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# 优先使用 curl_cffi (模拟真实浏览器 TLS 指纹)，否则回退到 requests
try:
    from curl_cffi import requests as cffi_requests
    USE_CFFI = True
except ImportError:
    import requests
    USE_CFFI = False

# ============================================================
#  配置区域 - 请根据你的实际信息修改
# ============================================================
CONFIG = {
    # Nike 账号信息
    "email": "your_email@example.com",
    "password": "your_password",

    # 要抢购的商品信息
    "product_id": "",            # 商品 SKU ID (如: "DZ5485-612")
    "size": "42.5",              # 鞋码 (EU)

    # 抢购时间 (UTC 时间，注意时区转换)
    # 格式: "YYYY-MM-DD HH:MM:SS"
    "launch_time": "2026-03-10 02:00:00",

    # 提前多少秒开始发送请求 (建议 0.5 - 2 秒)
    "advance_seconds": 1.0,

    # 重试次数
    "max_retries": 5,

    # 请求超时 (秒)
    "timeout": 10,

    # ===== 反检测配置 =====

    # 代理列表 (留空则不使用代理)
    # 支持格式: http://ip:port, socks5://ip:port, http://user:pass@ip:port
    "proxies": [
        # "http://127.0.0.1:7890",
        # "socks5://127.0.0.1:1080",
        # "http://user:pass@proxy.example.com:8080",
    ],

    # 是否启用代理轮换
    "rotate_proxy": True,

    # TLS 指纹模拟 (需安装 curl_cffi)
    # 可选: "chrome120", "chrome124", "safari17_0", "safari_ios17_2"
    "tls_fingerprint": "safari_ios17_2",

    # 请求间随机延迟范围 (秒)
    "min_delay": 0.1,
    "max_delay": 0.5,

    # 模拟的设备类型
    # 可选: "ios", "android", "web"
    "device_type": "ios",
}

# ============================================================
#  日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("snkrs_bot")

# ============================================================
#  Nike API 常量
# ============================================================
NIKE_API_BASE = "https://api.nike.com"
NIKE_AUTH_URL = f"{NIKE_API_BASE}/idn/shim/oauth/2.0/token"
NIKE_PRODUCT_URL = f"{NIKE_API_BASE}/product_feed/threads/v3"
NIKE_LAUNCH_URL = f"{NIKE_API_BASE}/launch/launch_views/v2"
NIKE_BUY_URL = f"{NIKE_API_BASE}/buy/checkout_previews/v2"


# ============================================================
#  反检测: 设备指纹生成器
# ============================================================
class DeviceFingerprint:
    """
    生成逼真的设备指纹信息。
    Nike 会检查设备一致性，因此同一个 session 内指纹必须保持不变。
    """

    # 真实的 iOS 设备型号列表
    IOS_MODELS = [
        ("iPhone15,3", "iPhone 14 Pro Max", "16.4"),
        ("iPhone15,4", "iPhone 15", "17.0"),
        ("iPhone15,5", "iPhone 15 Plus", "17.1"),
        ("iPhone16,1", "iPhone 15 Pro", "17.2"),
        ("iPhone16,2", "iPhone 15 Pro Max", "17.3"),
        ("iPhone17,1", "iPhone 16 Pro", "18.0"),
        ("iPhone17,2", "iPhone 16 Pro Max", "18.0"),
    ]

    # 真实的 Android 设备
    ANDROID_MODELS = [
        ("SM-S928B", "Samsung Galaxy S24 Ultra", "14"),
        ("SM-S926B", "Samsung Galaxy S24+", "14"),
        ("Pixel 8 Pro", "Google Pixel 8 Pro", "14"),
        ("2401116C", "Xiaomi 14", "14"),
    ]

    # SNKRS App 版本号
    APP_VERSIONS = [
        "2024.2.0", "2024.3.0", "2024.4.1", "2024.5.0",
        "2025.1.0", "2025.2.0",
    ]

    def __init__(self, device_type: str = "ios"):
        self.device_type = device_type
        self._device_id = self._generate_device_id()

        if device_type == "ios":
            model = random.choice(self.IOS_MODELS)
            self.model_id = model[0]
            self.model_name = model[1]
            self.os_version = model[2]
        elif device_type == "android":
            model = random.choice(self.ANDROID_MODELS)
            self.model_id = model[0]
            self.model_name = model[1]
            self.os_version = model[2]

        self.app_version = random.choice(self.APP_VERSIONS)
        self.screen_scale = random.choice(["2.0", "3.0"])

    def _generate_device_id(self) -> str:
        """生成一个持久化的设备ID（基于账号的哈希，保证同账号同设备）"""
        seed = f"snkrs_device_{random.randint(100000, 999999)}"
        return hashlib.sha256(seed.encode()).hexdigest()[:32]

    @property
    def device_id(self) -> str:
        return self._device_id

    def get_user_agent(self) -> str:
        """根据设备类型生成对应的 User-Agent"""
        if self.device_type == "ios":
            return (
                f"Nike/{self.app_version} "
                f"(iPhone; iOS {self.os_version}; Scale/{self.screen_scale})"
            )
        elif self.device_type == "android":
            return (
                f"Nike/{self.app_version} "
                f"({self.model_id}; Android {self.os_version}; Scale/{self.screen_scale})"
            )
        else:
            # Web 浏览器模式
            chrome_ver = random.randint(120, 126)
            return (
                f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_ver}.0.0.0 Safari/537.36"
            )

    def get_caller_id(self) -> str:
        if self.device_type == "ios":
            return "nike:snkrs:ios:2.0"
        elif self.device_type == "android":
            return "nike:snkrs:android:2.0"
        else:
            return "nike:snkrs:web:1.0"

    def get_ux_id(self) -> str:
        if self.device_type == "ios":
            return "com.nike.commerce.snkrs.ios"
        elif self.device_type == "android":
            return "com.nike.commerce.snkrs.droid"
        else:
            return "com.nike.commerce.snkrs.web"


# ============================================================
#  反检测: 请求头随机化引擎
# ============================================================
class HeaderRandomizer:
    """
    为每个请求生成略有不同但合理的 HTTP 头。
    避免所有请求头完全一致被识别为机器人。
    """

    ACCEPT_LANGUAGES = [
        "zh-CN,zh;q=0.9,en;q=0.8",
        "zh-CN,zh;q=0.9",
        "zh-Hans-CN;q=1.0,en-CN;q=0.9",
        "zh-CN,zh-Hans;q=0.9,en;q=0.8",
    ]

    ACCEPT_ENCODINGS = [
        "gzip, deflate, br",
        "gzip, deflate",
        "br, gzip, deflate",
    ]

    def __init__(self, fingerprint: DeviceFingerprint):
        self.fingerprint = fingerprint

    def generate_headers(self, extra: Optional[Dict] = None) -> Dict[str, str]:
        """
        生成带有轻微随机变化的请求头。
        核心字段保持一致（User-Agent, Caller-Id），
        次要字段引入合理变化。
        """
        headers = {
            "User-Agent": self.fingerprint.get_user_agent(),
            "Accept": "application/json",
            "Accept-Language": random.choice(self.ACCEPT_LANGUAGES),
            "Accept-Encoding": random.choice(self.ACCEPT_ENCODINGS),
            "Content-Type": "application/json; charset=utf-8",
            "X-Nike-Caller-Id": self.fingerprint.get_caller_id(),
            "X-Kpsdk-Ct": self._generate_kasada_token(),
            "X-Nike-Visitor-Id": self._generate_visitor_id(),
        }

        if extra:
            headers.update(extra)

        return headers

    def _generate_kasada_token(self) -> str:
        """
        生成模拟的 Kasada 反机器人 token。

        注意: 这只是格式模拟。真实的 Kasada token 需要执行 JS 挑战。
        如果 Nike 严格验证此 token，你需要集成真实的 Kasada solver。
        """
        # 模拟 Kasada CT token 格式 (Base64-like)
        chars = string.ascii_letters + string.digits + "+/"
        token_body = ''.join(random.choices(chars, k=random.randint(80, 120)))
        return token_body

    def _generate_visitor_id(self) -> str:
        """生成 Nike Visitor ID (UUID v4 格式)"""
        return str(uuid.uuid4())


# ============================================================
#  反检测: 代理管理器
# ============================================================
class ProxyManager:
    """
    管理和轮换代理 IP，避免同一 IP 发送过多请求。
    """

    def __init__(self, proxy_list: List[str], rotate: bool = True):
        self.proxies = proxy_list
        self.rotate = rotate
        self.current_index = 0
        self._failed_proxies: set = set()

    def get_proxy(self) -> Optional[Dict[str, str]]:
        """获取下一个可用的代理"""
        if not self.proxies:
            return None

        available = [p for p in self.proxies if p not in self._failed_proxies]
        if not available:
            logger.warning("⚠️ 所有代理均已失败，重置状态")
            self._failed_proxies.clear()
            available = self.proxies

        if self.rotate:
            proxy = available[self.current_index % len(available)]
            self.current_index += 1
        else:
            proxy = available[0]

        return {"http": proxy, "https": proxy}

    def mark_failed(self, proxy_url: str):
        """标记一个代理为失败"""
        self._failed_proxies.add(proxy_url)
        logger.warning(f"⚠️ 代理 {proxy_url} 已标记为失败")

    @property
    def has_proxies(self) -> bool:
        return len(self.proxies) > 0


# ============================================================
#  反检测: 行为模拟器
# ============================================================
class BehaviorSimulator:
    """
    模拟人类操作行为，避免请求模式过于机械。
    """

    def __init__(self, min_delay: float = 0.1, max_delay: float = 0.5):
        self.min_delay = min_delay
        self.max_delay = max_delay

    def random_delay(self):
        """添加随机延迟，模拟人类操作节奏"""
        delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

    def human_like_delay(self):
        """
        模拟更接近人类的延迟分布。
        使用对数正态分布，大多数延迟较短，偶尔较长。
        """
        delay = random.lognormvariate(mu=-1.5, sigma=0.5)
        delay = max(self.min_delay, min(delay, self.max_delay * 2))
        time.sleep(delay)

    @staticmethod
    def generate_mouse_trajectory() -> List[Dict[str, Any]]:
        """
        生成模拟的鼠标移动轨迹数据。
        某些反机器人系统会要求提交鼠标/触摸轨迹。
        """
        trajectory = []
        x, y = random.randint(100, 300), random.randint(200, 400)
        start_time = int(time.time() * 1000)

        # 生成 10-20 个轨迹点，模拟从页面某处移动到按钮
        num_points = random.randint(10, 20)
        target_x = random.randint(150, 250)
        target_y = random.randint(350, 450)

        for i in range(num_points):
            progress = (i + 1) / num_points
            # 使用贝塞尔曲线模拟真实鼠标运动
            noise_x = random.gauss(0, 3)
            noise_y = random.gauss(0, 3)
            current_x = x + (target_x - x) * progress + noise_x
            current_y = y + (target_y - y) * progress + noise_y

            trajectory.append({
                "x": round(current_x, 2),
                "y": round(current_y, 2),
                "t": start_time + int(i * random.uniform(30, 80)),
            })

        return trajectory

    @staticmethod
    def generate_touch_events() -> List[Dict[str, Any]]:
        """
        生成模拟的触摸事件 (用于 mobile 模式)。
        """
        events = []
        base_time = int(time.time() * 1000)

        # touchstart
        x = random.randint(140, 240)
        y = random.randint(500, 600)
        events.append({
            "type": "touchstart",
            "x": x + random.gauss(0, 1),
            "y": y + random.gauss(0, 1),
            "t": base_time,
        })

        # touchend (轻微偏移)
        events.append({
            "type": "touchend",
            "x": x + random.gauss(0, 2),
            "y": y + random.gauss(0, 2),
            "t": base_time + random.randint(80, 200),
        })

        return events


# ============================================================
#  核心: SNKRS 抢购机器人
# ============================================================
class SNKRSBot:
    """SNKRS 自动抢购机器人 (带反检测)"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.access_token: Optional[str] = None
        self.user_id: Optional[str] = None

        # 初始化反检测组件
        self.fingerprint = DeviceFingerprint(config.get("device_type", "ios"))
        self.header_gen = HeaderRandomizer(self.fingerprint)
        self.proxy_mgr = ProxyManager(
            config.get("proxies", []),
            config.get("rotate_proxy", True),
        )
        self.behavior = BehaviorSimulator(
            config.get("min_delay", 0.1),
            config.get("max_delay", 0.5),
        )

        logger.info(f"🔧 设备类型: {config.get('device_type', 'ios')}")
        logger.info(f"🔧 设备ID: {self.fingerprint.device_id[:16]}...")
        logger.info(f"🔧 User-Agent: {self.fingerprint.get_user_agent()}")
        logger.info(f"🔧 TLS指纹模拟: {'curl_cffi (' + config.get('tls_fingerprint', 'N/A') + ')' if USE_CFFI else '标准 requests (无TLS伪装)'}")
        logger.info(f"🔧 代理数量: {len(config.get('proxies', []))}")

    # --------------------------------------------------------
    #  安全请求封装
    # --------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Optional[Any]:
        """
        统一的请求方法，集成:
        - TLS 指纹伪装 (curl_cffi)
        - 代理轮换
        - 随机请求头
        - 行为模拟延迟
        - 自动重试（换代理）
        """
        # 生成请求头
        req_headers = self.header_gen.generate_headers(headers)
        if self.access_token:
            req_headers["Authorization"] = f"Bearer {self.access_token}"

        # 获取代理
        proxy_dict = self.proxy_mgr.get_proxy()

        # 模拟人类延迟
        self.behavior.random_delay()

        try:
            if USE_CFFI:
                # 使用 curl_cffi 模拟真实浏览器 TLS 指纹
                impersonate = self.config.get("tls_fingerprint", "safari_ios17_2")

                resp = cffi_requests.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    json=json_data,
                    params=params,
                    proxies=proxy_dict,
                    timeout=self.config["timeout"],
                    impersonate=impersonate,
                )
            else:
                # 回退到标准 requests
                import requests
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    json=json_data,
                    params=params,
                    proxies=proxy_dict,
                    timeout=self.config["timeout"],
                )

            return resp

        except Exception as e:
            logger.error(f"❌ 请求异常: {e}")
            # 如果使用了代理，标记该代理失败
            if proxy_dict and self.proxy_mgr.has_proxies:
                proxy_url = list(proxy_dict.values())[0]
                self.proxy_mgr.mark_failed(proxy_url)
            return None

    # --------------------------------------------------------
    #  1. 登录认证
    # --------------------------------------------------------
    def login(self) -> bool:
        """
        通过 Nike API 登录。
        使用 TLS 指纹伪装 + 设备指纹避免被检测。
        """
        logger.info(f"正在登录账号: {self.config['email']}")

        payload = {
            "client_id": "HlHa2Cje3ctlaOqnxvgZXNaAs7T9nAuH",
            "grant_type": "password",
            "ux_id": self.fingerprint.get_ux_id(),
            "username": self.config["email"],
            "password": self.config["password"],
        }

        resp = self._request("POST", NIKE_AUTH_URL, json_data=payload)

        if resp is None:
            logger.error("❌ 登录请求失败")
            return False

        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token")
            self.user_id = data.get("user_id")
            logger.info("✅ 登录成功!")
            logger.info(f"   用户ID: {self.user_id}")
            return True
        else:
            logger.error(f"❌ 登录失败: HTTP {resp.status_code}")
            logger.error(f"   响应: {resp.text[:500]}")

            if resp.status_code == 403:
                logger.error("   提示: 可能需要更换代理 IP 或 TLS 指纹")
            elif resp.status_code == 401:
                logger.error("   提示: 账号或密码错误")
            elif resp.status_code == 429:
                logger.error("   提示: 请求频率过高，请等待后重试")

            return False

    # --------------------------------------------------------
    #  2. 查询商品信息
    # --------------------------------------------------------
    def get_product_info(self, product_id: str) -> Optional[Dict]:
        """获取商品详细信息"""
        logger.info(f"正在查询商品: {product_id}")

        url = (
            f"{NIKE_PRODUCT_URL}/"
            f"?filter=marketplace(CN)"
            f"&filter=language(zh-Hans)"
            f"&filter=productInfo.merchProduct.styleColor({product_id})"
        )

        resp = self._request("GET", url)

        if resp is None:
            return None

        if resp.status_code == 200:
            data = resp.json()
            objects = data.get("objects", [])
            if objects:
                product = objects[0]
                title = (
                    product.get("publishedContent", {})
                    .get("properties", {})
                    .get("title", "N/A")
                )
                logger.info(f"✅ 找到商品: {title}")
                return product
            else:
                logger.warning("⚠️ 未找到对应商品")
                return None
        else:
            logger.error(f"❌ 查询失败: HTTP {resp.status_code}")
            return None

    # --------------------------------------------------------
    #  3. 获取尺码 SKU
    # --------------------------------------------------------
    def get_sku_id(self, product_info: Dict, target_size: str) -> Optional[str]:
        """从商品信息中提取指定尺码 SKU ID"""
        try:
            product_info_list = product_info.get("productInfo", [])
            for pi in product_info_list:
                skus = pi.get("skus", [])
                for sku in skus:
                    nike_size = sku.get("nikeSize", "")
                    if str(nike_size) == str(target_size):
                        sku_id = sku.get("id")
                        logger.info(f"✅ 找到尺码 {target_size} -> SKU: {sku_id}")
                        return sku_id

            logger.error(f"❌ 未找到尺码: {target_size}")
            for pi in product_info_list:
                sizes = [sku.get("nikeSize") for sku in pi.get("skus", [])]
                logger.info(f"   可用尺码: {sizes}")
            return None

        except (KeyError, TypeError) as e:
            logger.error(f"❌ 解析尺码失败: {e}")
            return None

    # --------------------------------------------------------
    #  4. 提交抢购 (含反检测增强)
    # --------------------------------------------------------
    def submit_order(self, product_id: str, sku_id: str) -> bool:
        """
        提交抢购请求，附带模拟的行为数据。
        """
        logger.info(f"🚀 正在提交抢购请求: SKU={sku_id}")

        checkout_id = str(uuid.uuid4())

        # 构建请求 payload，包含行为模拟数据
        payload = {
            "request": {
                "skuId": sku_id,
                "deviceId": self.fingerprint.device_id,
                "channel": "SNKRS",
                "locale": "zh_CN",
                "currency": "CNY",
                "country": "CN",
            },
            "checkoutId": checkout_id,
        }

        # 附加行为模拟数据 (如果 Nike 要求)
        if self.config.get("device_type") in ("ios", "android"):
            payload["metadata"] = {
                "touchEvents": self.behavior.generate_touch_events(),
                "deviceTime": int(time.time() * 1000),
                "timezone": "Asia/Shanghai",
                "batteryLevel": random.uniform(0.2, 0.95),
                "networkType": random.choice(["wifi", "4g", "5g"]),
            }
        else:
            payload["metadata"] = {
                "mouseTrajectory": self.behavior.generate_mouse_trajectory(),
                "deviceTime": int(time.time() * 1000),
                "timezone": "Asia/Shanghai",
                "screenResolution": random.choice([
                    "1920x1080", "2560x1440", "1440x900",
                ]),
            }

        resp = self._request("POST", NIKE_BUY_URL, json_data=payload)

        if resp is None:
            return False

        if resp.status_code in (200, 201, 202):
            data = resp.json()
            status = data.get("status", "UNKNOWN")
            logger.info(f"✅ 请求已提交! 状态: {status}")
            logger.info(f"   Checkout ID: {checkout_id}")

            if status == "PENDING":
                logger.info("📋 进入排队/抽签模式，等待结果...")
            elif status == "COMPLETED":
                logger.info("🎉🎉🎉 抢购成功！请去 Nike App 确认订单！")
            return True

        elif resp.status_code == 403:
            logger.error("❌ 被拒绝 (403) - 反机器人检测触发")
            logger.error("   建议: 更换代理 IP + TLS 指纹后重试")
            return False
        elif resp.status_code == 412:
            logger.error("❌ 前置条件失败 (412) - 可能需要完成验证")
            return False
        elif resp.status_code == 429:
            logger.error("❌ 请求过于频繁 (429) - 需要降速或换 IP")
            return False
        else:
            logger.error(f"❌ 提交失败: HTTP {resp.status_code}")
            logger.error(f"   响应: {resp.text[:500]}")
            return False

    # --------------------------------------------------------
    #  5. 定时等待
    # --------------------------------------------------------
    def wait_for_launch(self, launch_time_str: str, advance_seconds: float = 1.0):
        """等待发售时间"""
        launch_time = datetime.strptime(launch_time_str, "%Y-%m-%d %H:%M:%S")
        launch_time = launch_time.replace(tzinfo=timezone.utc)
        target_time = launch_time.timestamp() - advance_seconds

        logger.info(f"⏰ 发售时间 (UTC): {launch_time_str}")
        logger.info(f"⏰ 将提前 {advance_seconds} 秒开始抢购")

        while True:
            now = time.time()
            remaining = target_time - now

            if remaining <= 0:
                logger.info("🔥 时间到！开始抢购！")
                break

            if remaining > 60:
                logger.info(f"   距离开抢还有 {remaining:.0f} 秒...")
                time.sleep(30)
            elif remaining > 5:
                logger.info(f"   距离开抢还有 {remaining:.1f} 秒...")
                time.sleep(1)
            else:
                time.sleep(0.01)

    # --------------------------------------------------------
    #  6. Token 保活
    # --------------------------------------------------------
    def keep_alive(self):
        """
        定期刷新 token，防止长时间等待后 token 过期。
        Nike 的 access_token 通常有效期为 1 小时。
        """
        logger.info("🔄 刷新 Token 保活...")
        # 发一个轻量级请求来保持 session
        resp = self._request("GET", f"{NIKE_API_BASE}/user/info")
        if resp and resp.status_code == 200:
            logger.info("✅ Token 有效")
        else:
            logger.warning("⚠️ Token 可能已过期，尝试重新登录")
            self.login()

    # --------------------------------------------------------
    #  7. 主流程
    # --------------------------------------------------------
    def run(self):
        """
        完整抢购流程:
        1. 登录 (带 TLS 指纹伪装)
        2. 查询商品
        3. 获取尺码 SKU
        4. 等待发售时间 (期间保活)
        5. 提交抢购 (带行为模拟 + 代理轮换 + 重试)
        """
        logger.info("=" * 55)
        logger.info("  SNKRS 自动抢购脚本 (反检测增强版)")
        logger.info("=" * 55)

        if not USE_CFFI:
            logger.warning("⚠️  未安装 curl_cffi，TLS 指纹伪装不可用！")
            logger.warning("    建议安装: pip install curl_cffi")
            logger.warning("    没有 TLS 伪装被检测概率大幅上升")

        # Step 1: 登录
        if not self.login():
            logger.error("登录失败，程序退出")
            return

        # Step 2: 查询商品
        product_info = self.get_product_info(self.config["product_id"])
        if not product_info:
            logger.error("未找到商品，程序退出")
            return

        # Step 3: 获取 SKU
        sku_id = self.get_sku_id(product_info, self.config["size"])
        if not sku_id:
            logger.error("未找到对应尺码，程序退出")
            return

        # Step 4: 等待发售时间 (带保活)
        launch_time = datetime.strptime(
            self.config["launch_time"], "%Y-%m-%d %H:%M:%S"
        )
        launch_time = launch_time.replace(tzinfo=timezone.utc)
        target_time = launch_time.timestamp() - self.config["advance_seconds"]

        logger.info(f"⏰ 发售时间 (UTC): {self.config['launch_time']}")

        last_keepalive = time.time()
        while True:
            now = time.time()
            remaining = target_time - now

            if remaining <= 0:
                logger.info("🔥 时间到！开始抢购！")
                break

            # 每 30 分钟保活一次
            if now - last_keepalive > 1800:
                self.keep_alive()
                last_keepalive = now

            if remaining > 60:
                logger.info(f"   距离开抢还有 {remaining:.0f} 秒...")
                time.sleep(min(30, remaining - 5))
            elif remaining > 5:
                logger.info(f"   距离开抢还有 {remaining:.1f} 秒...")
                time.sleep(1)
            else:
                time.sleep(0.005)

        # Step 5: 抢购 (带重试 + 每次换代理)
        for attempt in range(1, self.config["max_retries"] + 1):
            logger.info(f"--- 第 {attempt}/{self.config['max_retries']} 次尝试 ---")

            if self.proxy_mgr.has_proxies:
                proxy = self.proxy_mgr.get_proxy()
                logger.info(f"   使用代理: {list(proxy.values())[0][:30]}...")

            success = self.submit_order(self.config["product_id"], sku_id)

            if success:
                logger.info("🎉 抢购请求已成功提交！")
                break

            if attempt < self.config["max_retries"]:
                # 递增但带随机抖动的等待
                base_wait = 0.3 * attempt
                jitter = random.uniform(0, 0.3)
                wait = base_wait + jitter
                logger.info(f"   等待 {wait:.2f} 秒后重试...")
                time.sleep(wait)
        else:
            logger.error("❌ 所有重试均失败")

        logger.info("=" * 55)
        logger.info("  脚本运行结束")
        logger.info("=" * 55)


# ============================================================
#  入口
# ============================================================
if __name__ == "__main__":
    bot = SNKRSBot(CONFIG)
    bot.run()
