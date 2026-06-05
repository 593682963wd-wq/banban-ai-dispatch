# 带班AI分飞机 · 网页版上公网（Streamlit Community Cloud）

目标：拿到一个**固定公网网址**，发给同事直接用，你电脑关机也能访问。
和你现有『机场障碍物分析』(`*.streamlit.app`) 同款方案。

---

## 已为你准备好的（代码侧，无需再动）

- `requirements.txt` —— 已改成 web-only（pandas / openpyxl / streamlit），去掉了 PySide6
- `requirements-desktop.txt` —— 桌面端单独的依赖（含 PySide6）
- `.gitignore` —— 不会把 `.DS_Store`、`*.xlsx`（真实动态列表）、密钥推上去
- `.streamlit/config.toml` —— 主题
- 本地已 `git init` 并提交首个版本

---

## 你要点的两步

### 第 1 步：在 GitHub 建一个**私有**仓库，并推上去

> 分飞机算法是公司内部 IP，**建私有仓（Private）**，别公开。

1. 打开 https://github.com/new
2. Repository name 填：`banban-ai-dispatch`
3. 选 **Private**（私有）
4. 其它都不用勾（不要勾 Add README，本地已有），点 **Create repository**
5. 回到电脑，在项目目录执行（把下面 URL 换成你刚建的仓库地址）：

```bash
cd /Users/amanda/Documents/banban_ai_dispatch
git remote add origin https://github.com/593682963wd-wq/banban-ai-dispatch.git
git branch -M main
git push -u origin main
```

> 第一次 push 若弹账号/密码：用户名填 GitHub 用户名，密码填 **Personal Access Token**（不是登录密码）。你以前推过 github.io，钥匙串里大概率已缓存，会直接过。

### 第 2 步：在 Streamlit Cloud 部署

1. 打开 https://share.streamlit.io ，用 GitHub 登录（你之前部署障碍物分析的同一个账号）
2. 点 **Create app** → **Deploy a public app from GitHub** / 选已有仓库
3. 选仓库 `593682963wd-wq/banban-ai-dispatch`，Branch `main`，Main file path 填 **`app.py`**
   - 若是私有仓，按提示授权 Streamlit 访问私有仓（Configure GitHub permissions）
4. 点 **Deploy**，等 2~4 分钟装依赖、起服务
5. 部署成功后，浏览器地址栏那个 `https://....streamlit.app` 就是**最终公网网址**

### 第 3 步：把网址发我

部署成功后，把那个 `https://....streamlit.app` 网址发给我，我会：
- 在王迪工具台把 `banban_dispatch_web` 登记成 `web_url`（同事打开走云端，不再是 127.0.0.1）
- 把 `access` 解锁成 `public`（同事能在工具台看到并打开）

---

## 注意

- **私有仓 + Streamlit 免费版**：支持私有仓部署；若提示私有 App 数量到顶，可临时改公开或清理旧 App。
- 云端是**无状态**的：同事每次上传动态列表→在线算→下载 Excel，不留存数据，符合数据安全。
- 以后改了算法：`git push` 后 Streamlit Cloud 会**自动重新部署**，网址不变。
- 记得双端 `core/` 同源（你原有口径），改完桌面端记得同步网页端再 push。
