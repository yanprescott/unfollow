# X/Twitter 取关管理工具

找出未回关你的用户，一键批量取关。

## 功能

- 拉取你的关注列表和粉丝列表，计算出**未回关的人**
- 支持**白名单**，保护不想取关的账号
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
- `L` — 列出所有未回关的用户
- `D` — 预览将被取关的人（不会实际执行）
- `U` — 执行批量取关
- `W` — 把某人加入白名单
- `Q` — 退出

## 白名单

编辑 `whitelist.txt`（参考 `whitelist.example.txt`），每行一个用户名。白名单内的用户不会出现在取关列表中。

## 注意事项

- 需要保持 Cookie 有效，如果失效会提示更新 `.env`
- 每取关 50 人会自动暂停 30 秒以避免触发限速
- 取关进度会保存在 `state.json`，中断后可以继续

## 许可

MIT
