# X/Twitter 关注管理工具

取关未回关你的人，回关关注了你但你没回关的人。

## 功能

- **取关** — 找出你关注了但没回关你的人，白名单保护，一键取关
- **回关** — 找出关注了你但你还没回关的人，黑名单跳过，一键回关
- **白名单** — 保护不想取关的账号
- **黑名单** — 屏蔽即使关注了你也不想回关的账号
- 断点续传，中断后可以继续
- 内置限速，避免触发 X API 限制

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取 Cookie

在浏览器中登录 [x.com](https://x.com)，打开开发者工具 → Application → Cookies → x.com，复制 `auth_token` 和 `ct0` 的值。

### 3. 配置

```bash
cp .env.example .env
```

编辑 `.env`，填入 Cookie 和你的用户名：

```
X_AUTH_COOKIE=auth_token=你的auth_token; ct0=你的ct0
MY_USERNAME=你的用户名
```

### 4. 运行

```bash
python unfollow.py
```

进入交互菜单后：

**取关**
- `L` — 列出所有未回关你的人
- `D` — 预览将被取关的人（不会实际执行）
- `U` — 执行批量取关

**回关**
- `LF` — 列出你未回关的粉丝
- `F` — 执行批量回关

**其他**
- `W` — 把某人加入白名单
- `B` — 把某人加入黑名单
- `Q` — 退出

## 白名单 & 黑名单

- **白名单** — 编辑 `whitelist.txt`（参考 `whitelist.example.txt`），每行一个用户名。白名单内的用户即使没回关你也不会被取关。
- **黑名单** — 编辑 `blacklist.txt`（参考 `blacklist.example.txt`），每行一个用户名。黑名单内的用户即使关注了你也不会被回关。

## 注意事项

- 需要保持 Cookie 有效，如果失效会提示更新 `.env`
- 每 50 次操作会自动暂停 30 秒以避免触发限速
- 进度会保存在 `state.json`，中断后可以继续
- 回关功能受黑名单过滤

## 许可

MIT
