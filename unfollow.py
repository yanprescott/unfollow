#!/usr/bin/env python3
"""
X (Twitter) 取关管理工具
========================
拉取关注列表与粉丝列表，找出未回关你的用户，排除白名单后一键取关。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

# ── 路径 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
WHITELIST_PATH = BASE_DIR / "whitelist.txt"
STATE_PATH = BASE_DIR / "state.json"

# ── 日志 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("unfollow")

# ── X API 常量 ────────────────────────────────────────────────────────────
_PUBLIC_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

_QUERIES = {
    "UserByScreenName": "2qvSHpkWTMS9i0zJAwDNiA",
    "Following": "eNoXdfXv5rU75RBzlmfuPA",
    "Followers": "4yeuNabfz3qFlfncCAy8Yw",
}

_FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

# ── 配置加载 ──────────────────────────────────────────────────────────────


def load_env() -> dict[str, str]:
    """从 .env 文件加载敏感配置，也支持环境变量覆盖。"""
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip()
    for k in ("X_AUTH_COOKIE", "MY_USERNAME"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


# ── 白名单 ────────────────────────────────────────────────────────────────


def load_whitelist() -> set[str]:
    """从 whitelist.txt 加载白名单用户名（lowercase）。"""
    if not WHITELIST_PATH.exists():
        return set()
    names: set[str] = set()
    with open(WHITELIST_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            names.add(line.lower().lstrip("@"))
    return names


def add_to_whitelist(username: str) -> None:
    """将用户名追加到白名单文件。"""
    clean = username.lower().lstrip("@")
    existing = load_whitelist()
    if clean in existing:
        log.info("  @%s 已在白名单中", clean)
        return
    with open(WHITELIST_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"{clean}\n")
    log.info("  ✅ @%s 已添加到白名单", clean)


# ── 状态持久化（增量取关断点续传）──────────────────────────────────────────


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_state(state: dict[str, Any]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)


# ── X 客户端 ─────────────────────────────────────────────────────────────


class RateLimitTracker:
    """简单的客户端滑动窗口限流器。"""

    def __init__(self, max_requests: int = 800, window_seconds: int = 900) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []

    def wait_if_needed(self) -> None:
        now = time.monotonic()
        cutoff = now - self.window
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_requests:
            oldest = self._timestamps[0]
            wait = oldest + self.window - now + 1.5
            if wait > 0:
                log.info("⏳ 主动限速 (已 %d/%d 次)，等待 %.1fs...",
                         len(self._timestamps), self.max_requests, wait)
                time.sleep(wait)
                return self.wait_if_needed()
        self._timestamps.append(time.monotonic())


class XClient:
    """X (Twitter) 内部 API 客户端 — 仅支持 Cookie 认证。"""

    def __init__(self, auth_cookie: str) -> None:
        self._auth_cookie = auth_cookie
        self.rate_limiter = RateLimitTracker(
            max_requests=800, window_seconds=900,
        )
        self.client = httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://x.com/",
                "Origin": "https://x.com",
                "X-Twitter-Auth-Type": "OAuth2Session",
                "X-Twitter-Active-User": "yes",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            },
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )
        self._setup_cookie()
        self._csrf_token = ""
        m = re.search(r"ct0=([0-9a-f]+)", auth_cookie)
        if m:
            self._csrf_token = m.group(1)

    def _setup_cookie(self) -> None:
        self.client.headers["Cookie"] = self._auth_cookie
        m = re.search(r"ct0=([0-9a-f]+)", self._auth_cookie)
        if m:
            self.client.headers["X-Csrf-Token"] = m.group(1)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {_PUBLIC_BEARER}"}

    def _graphql(self, query_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        """执行 GraphQL POST 请求，含自动重试。"""
        self.rate_limiter.wait_if_needed()
        query_id = _QUERIES[query_name]
        url = f"https://x.com/i/api/graphql/{query_id}/{query_name}"

        body: dict[str, Any] = {"variables": variables}
        if query_name != "UserByScreenName":
            body["features"] = _FEATURES

        headers = {
            **self._auth_headers(),
            "X-Csrf-Token": self._csrf_token,
            "Content-Type": "application/json",
        }
        resp = self.client.post(url, headers=headers, json=body)

        if resp.status_code in (401, 403):
            log.fatal("❌ Cookie 已失效 (HTTP %d)，请更新 .env 中的 X_AUTH_COOKIE",
                      resp.status_code)
            sys.exit(1)

        if resp.status_code == 429:
            wait = int(resp.headers.get("x-rate-limit-reset", 900))
            wait = max(30, wait - int(time.time())) + 3
            log.warning("⚠️  X 限速 (429)，等待 %d 秒...", wait)
            time.sleep(wait)
            resp = self.client.post(url, headers=headers, json=body)

        resp.raise_for_status()
        return resp.json()

    def _rest_post(self, endpoint: str, data: dict[str, str]) -> bool:
        """POST 请求到 REST v1.1 端点。"""
        self.rate_limiter.wait_if_needed()
        url = f"https://x.com/i/api/1.1/{endpoint}"
        headers = {
            **self._auth_headers(),
            "X-Csrf-Token": self._csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = self.client.post(url, headers=headers, data=data)

        if resp.status_code in (401, 403):
            log.error("❌ 取关操作被拒绝 (HTTP %d) — Cookie 可能已失效", resp.status_code)
            return False

        if resp.status_code == 429:
            wait = int(resp.headers.get("x-rate-limit-reset", 900))
            wait = max(30, wait - int(time.time())) + 3
            log.warning("⚠️  取关限速 (429)，等待 %d 秒...", wait)
            time.sleep(wait)
            resp = self.client.post(url, headers=headers, data=data)

        if resp.status_code in (200, 201):
            return True

        log.error("❌ 取关失败 HTTP %d: %s", resp.status_code, resp.text[:200])
        return False

    def resolve_username(self, username: str) -> Optional[dict[str, Any]]:
        """通过用户名解析用户信息。"""
        clean = username.lower().strip("@ ")
        try:
            data = self._graphql("UserByScreenName",
                {"screen_name": clean, "withSafetyModeUserFields": True})
            ur = data.get("data", {}).get("user", {}).get("result", {})
            if not ur:
                log.warning("⚠️  未找到账号 @%s", clean)
                return None
            core = ur.get("core", {})
            return {
                "id": ur["rest_id"],
                "name": core.get("name", clean),
                "username": core.get("screen_name", clean),
            }
        except Exception as e:
            log.error("❌ 解析 @%s 失败: %s", clean, e)
            return None

    def resolve_my_info(self, my_username: str) -> Optional[dict[str, Any]]:
        """通过 MY_USERNAME 解析自己的账号信息。"""
        info = self.resolve_username(my_username)
        if info:
            return info
        log.fatal("❌ 无法解析你的账号 @%s，请检查 .env 中的 MY_USERNAME", my_username)
        return None

    def _get_timeline_users(
        self, query_name: str, user_id: str, max_items: int = 10000
    ) -> list[dict[str, Any]]:
        """通用分页拉取用户列表（Following / Followers）。"""
        users: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        page = 0

        while len(users) < max_items:
            page += 1
            variables: dict[str, Any] = {
                "userId": user_id,
                "count": 100,
                "includePromotedContent": False,
            }
            if cursor:
                variables["cursor"] = cursor

            try:
                data = self._graphql(query_name, variables)
            except Exception as e:
                log.error("❌ %s 第 %d 页失败: %s", query_name, page, e)
                break

            ud = data.get("data", {}).get("user", {}).get("result", {})
            if not ud:
                log.warning("  ⚠️  无法获取用户数据")
                break

            timeline = ud.get("timeline", {}).get("timeline", {})
            instructions = timeline.get("instructions", [])

            # 收集所有 TimelineAddEntries 中的条目
            entries: list[dict[str, Any]] = []
            for instr in instructions:
                if instr.get("type") == "TimelineAddEntries":
                    entries.extend(instr.get("entries", []))

            next_cursor: Optional[str] = None
            page_users = 0
            for entry in entries:
                c = entry.get("content", {})
                etype = c.get("entryType", "")

                # 游标条目
                if etype == "TimelineTimelineCursor":
                    if c.get("cursorType") == "Bottom":
                        next_cursor = c.get("value", "")
                    continue

                # 用户条目
                if etype == "TimelineTimelineItem":
                    ic = c.get("itemContent", {})
                    if ic.get("itemType") != "TimelineUser":
                        continue
                    ur = ic.get("user_results", {}).get("result", {})
                    if not ur:
                        continue
                    rid = ur.get("rest_id", "")
                    core = ur.get("core", {})
                    legacy = ur.get("legacy", {})
                    if not rid:
                        continue
                    users.append({
                        "id": rid,
                        "username": core.get("screen_name", ""),
                        "name": core.get("name", ""),
                        "description": legacy.get("description", ""),
                        "followers_count": legacy.get("followers_count", 0),
                        "friends_count": legacy.get("friends_count", 0),
                        "verified": core.get("verified", False),
                    })
                    page_users += 1

            log.info("  第 %d 页: +%d 人 (累计 %d)", page, page_users, len(users))

            # 无新用户或没有下一页游标则停止
            if page_users == 0:
                log.info("  ✅ 已拉取完毕（无更多用户）")
                break
            if not next_cursor:
                log.info("  ✅ 已拉取完毕（无更多页）")
                break
            cursor = next_cursor
            time.sleep(0.3)  # 页面间短暂间隔

        return users

    def get_following(self, user_id: str) -> list[dict[str, Any]]:
        return self._get_timeline_users("Following", user_id)

    def get_followers(self, user_id: str) -> list[dict[str, Any]]:
        return self._get_timeline_users("Followers", user_id)

    def unfollow_user(self, user_id: str) -> bool:
        """取关单个用户。"""
        return self._rest_post("friendships/destroy.json", {"user_id": user_id})


# ── 交互界面 ──────────────────────────────────────────────────────────────


def print_banner() -> None:
    print()
    print("══════════════════════════════════════════")
    print("  X/Twitter 取关管理工具")
    print("  找出未回关你的人，一键取关")
    print("══════════════════════════════════════════")
    print()


def print_results(
    following_count: int,
    followers_count: int,
    mutual_count: int,
    non_mutual: list[dict[str, Any]],
    whitelist_ids: set[str],
) -> None:
    """显示分析结果摘要。"""
    whitelist_non_mutual = [u for u in non_mutual if u["id"] in whitelist_ids]
    actionable = [u for u in non_mutual if u["id"] not in whitelist_ids]

    print()
    print("──────────────────────────────────────────")
    print(f"📊 分析结果:")
    print(f"  关注了:    {following_count} 人")
    print(f"  粉丝:      {followers_count} 人")
    print(f"  互相关注:  {mutual_count} 人")
    print(f"  未回关你:  {len(non_mutual)} 人")
    if whitelist_non_mutual:
        print(f"  白名单豁免: {len(whitelist_ids)} 人 (其中未回关: {len(whitelist_non_mutual)} 人)")
    else:
        print(f"  白名单:    {len(whitelist_ids)} 人")
    print(f"  ──")
    print(f"  本次可取关: {len(actionable)} 人")
    print("──────────────────────────────────────────")
    print()


def list_non_mutual(non_mutual: list[dict[str, Any]], whitelist_ids: set[str]) -> None:
    """列出未回关用户。"""
    print()
    print(f"{'#':>4}  {'用户名':<20} {'显示名':<25} {'粉丝':>8} {'关注':>8} {'状态'}")
    print("-" * 85)
    for i, u in enumerate(non_mutual, 1):
        status = "⚪ 白名单" if u["id"] in whitelist_ids else "🔴 可取关"
        print(
            f"{i:>4}  @{u['username']:<19} {u['name'][:24]:<25} "
            f"{u['followers_count']:>8,} {u['friends_count']:>8,} {status}"
        )
    print()


def confirm_action(prompt: str) -> bool:
    """用户确认操作。"""
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def execute_unfollow(
    x: XClient,
    actionable: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    """执行批量取关。"""
    total = len(actionable)
    unfollowed = state.get("unfollowed", [])
    errors = state.get("errors", [])

    print(f"\n准备取关 {total} 人...")
    print(f"  已取关: {len(unfollowed)} 人")
    print(f"  剩余:   {total - len(unfollowed)} 人")

    if not confirm_action(f"确定要取关这 {total - len(unfollowed)} 人吗？"):
        print("  已取消。")
        return state

    for i, u in enumerate(actionable):
        uid = u["id"]
        username = u["username"]

        # 跳过已完成的
        if uid in unfollowed:
            continue

        # 进度显示
        progress = f"[{i + 1}/{total}]"
        print(f"  {progress} 取关 @{username}...", end=" ", flush=True)

        if x.unfollow_user(uid):
            print("✅")
            unfollowed.append(uid)
        else:
            print("❌")
            errors.append({"id": uid, "username": username})

        # 保存断点
        state["unfollowed"] = unfollowed
        state["errors"] = errors
        save_state(state)

        # 每 50 人暂停 30 秒
        if (i + 1) % 50 == 0 and i + 1 < total:
            print(f"  ⏸  已取关 {i + 1}/{total}，暂停 30 秒...")
            time.sleep(30)

        # 每次取关间隔 1 秒
        if i + 1 < total:
            time.sleep(1.0)

    print(f"\n✅ 取关完成: {len(unfollowed)} 成功, {len(errors)} 失败")
    return state


# ── 主入口 ────────────────────────────────────────────────────────────────


def main() -> None:
    print_banner()

    # 1. 加载配置
    env = load_env()
    cookie = env.get("X_AUTH_COOKIE", "")
    if not cookie:
        log.fatal("❌ 缺少 X_AUTH_COOKIE，请在 .env 文件中设置")
        sys.exit(1)
    my_username = env.get("MY_USERNAME", "").strip()
    if not my_username:
        log.fatal("❌ 缺少 MY_USERNAME，请在 .env 文件中设置你的 X 用户名")
        sys.exit(1)

    log.info("🔐 使用 Cookie 认证...")
    x = XClient(auth_cookie=cookie)

    # 2. 解析自己的账号
    log.info("正在解析你的账号...")
    my_info = x.resolve_my_info(my_username)
    if not my_info:
        sys.exit(1)
    my_id = my_info["id"]
    log.info("  你的账号: @%s (id=%s)", my_info["username"], my_id)

    # 3. 拉取关注列表
    log.info("正在拉取关注列表（可能较慢，取决于关注人数）...")
    following = x.get_following(my_id)
    following_ids = {u["id"]: u for u in following}
    log.info("  关注了: %d 人", len(following))

    # 4. 拉取粉丝列表
    log.info("正在拉取粉丝列表...")
    followers = x.get_followers(my_id)
    followers_ids = {u["id"] for u in followers}
    log.info("  粉丝: %d 人", len(followers))

    # 5. 加载白名单并解析 user_id
    log.info("正在加载白名单...")
    whitelist_names = load_whitelist()
    log.info("  白名单用户名: %d 个", len(whitelist_names))

    whitelist_ids: set[str] = set()
    for name in whitelist_names:
        # 先在关注列表中查找（无需额外 API 请求）
        found = False
        for uid, uinfo in following_ids.items():
            if uinfo["username"].lower() == name:
                whitelist_ids.add(uid)
                found = True
                break
        if not found:
            # 尝试通过 API 解析
            user_info = x.resolve_username(name)
            if user_info:
                whitelist_ids.add(user_info["id"])
                log.info("  白名单 @%s → id=%s", name, user_info["id"])
            else:
                log.warning("  ⚠️  白名单用户 @%s 未找到", name)
    log.info("  白名单解析: %d 个 user_id", len(whitelist_ids))

    # 6. 计算差集
    mutual_count = sum(1 for uid in following_ids if uid in followers_ids)
    non_mutual = [
        following_ids[uid]
        for uid in following_ids
        if uid not in followers_ids
    ]
    actionable = [u for u in non_mutual if u["id"] not in whitelist_ids]

    print_results(len(following), len(followers), mutual_count, non_mutual, whitelist_ids)

    # 7. 加载断点状态
    state = load_state()
    state.setdefault("unfollowed", [])
    state.setdefault("errors", [])

    # 8. 交互菜单
    while True:
        print()
        print("操作:")
        print("  [L] 列出未回关用户")
        print("  [D] 预览取关（dry-run，不执行）")
        if actionable:
            remaining = len(actionable) - len(state.get("unfollowed", []))
            print(f"  [U] 执行取关 ({remaining} 人待处理)")
        print("  [W] 添加用户到白名单")
        print("  [Q] 退出")
        print()

        try:
            choice = input("> ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break

        if choice == "L":
            list_non_mutual(non_mutual, whitelist_ids)

        elif choice == "D":
            print(f"\n即将取关以下 {len(actionable)} 人（dry-run，不会执行）：")
            for i, u in enumerate(actionable, 1):
                print(f"  {i:>4}. @{u['username']:<20} {u['name'][:30]}")
            print(f"\n(实际执行请输入 U)")

        elif choice == "U":
            if not actionable:
                print("没有需要取关的用户。")
                continue
            remaining = [u for u in actionable if u["id"] not in state.get("unfollowed", [])]
            if not remaining:
                print("所有用户已取关完毕！")
                continue
            state = execute_unfollow(x, remaining, state)
            # 刷新状态
            state = load_state()

        elif choice == "W":
            name = input("输入要加入白名单的用户名: ").strip()
            if name:
                add_to_whitelist(name)

        elif choice == "Q":
            print("退出。")
            break

        else:
            print("无效选项，请重试。")


if __name__ == "__main__":
    main()
