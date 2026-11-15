# 校园网 eLearning 自动认证

面向兰州大学校园网的后台工具：按信号选择已保存的 `iLZU` / `LZU`，并在需要时完成 eLearning 认证。认证走 HTTP，浏览器只在必要时兜底，Windows、macOS、Linux 都能运行，不下载 Chromium。

要求：Python 3.8 或更高版本，以及系统中已保存的校园 Wi-Fi 配置。源码位于 `outputs/`，虚拟环境位于仓库根目录 `.venv/`。

## 安装

Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r outputs\requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r outputs/requirements.txt
```

需要验证码兜底时再装 `outputs/requirements-browser.txt`，macOS 上想按信号选网再装 `outputs/requirements-macos.txt`。不要执行 `playwright install`，程序使用本机已装的 Edge 或 Chrome。

## 首次使用

```powershell
.\outputs\campus.cmd setup
```

```bash
./outputs/campus.sh setup
```

在本机窗口输入账号、密码，点击“保存凭据并启动”。没有图形界面时退回终端输入，密码不回显。账号填写 eLearning 账号，不需要加 `@study`。凭据只写入当前用户的凭据存储，不通过命令行参数、环境变量、配置文件或日志传递密码。更新密码也使用此命令。

## 启动、查看、停止及卸载

```powershell
# 无窗口后台启动
.\outputs\campus.cmd start
# 查看监控进程状态
.\outputs\campus.cmd status
# 立即检测互联网
.\outputs\campus.cmd check
# 停止监控（会等待正在进行的操作结束，最多 90 秒）
.\outputs\campus.cmd stop
# 开启当前用户登录后自启动，无需管理员权限
.\outputs\campus.cmd install-startup
# 仅取消自启动
.\outputs\campus.cmd remove-startup
# 卸载：停止进程，删除本工具的自启动项和凭据
.\outputs\campus.cmd uninstall
```

macOS 与 Linux 把 `.\outputs\campus.cmd` 换成 `./outputs/campus.sh`。另有 `auth` 立即尝试一次认证、`logs` 打印日志目录、`run` 供系统服务调用。

`stop` 不取消下次登录自启动。`uninstall` 保留项目文件和日志，不会删除其他文件。自启动分别使用 Windows 的 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`、macOS 的 `~/Library/LaunchAgents/com.lcaa.monitor.plist` 和 Linux 的 `systemd --user` 单元，移动项目后需要重新安装自启动。工具仅在断网恢复时连接已保存的校园 Wi-Fi，不修改其他启动项、代理或防火墙设置。

## 工作方式

- 需要恢复 Wi-Fi 连接时，扫描 `iLZU` 和 `LZU`，从可连接且已保存的配置中选信号较强者；同强度优先保持当前网络。连接请求完成后等待 Wi-Fi 关联及地址分配，再检测互联网，必要时才进行认证。即使候选仍是当前 SSID，也会请求重新连接，处理需要手动点击 Wi-Fi 的情况。

- 正常联网时不切换；已连接其他非校园 Wi-Fi 的接口不改动。不会创建 Wi-Fi 配置或读取 Wi-Fi 密码。扫描受权限限制或接口不可用时，保留原有连接并继续认证流程。Wi-Fi 恢复同样遵循下述退避间隔。

- 每 15 秒并行访问 Microsoft、华为、Cloudflare 三个 HTTPS 检测端点，校验状态码及预期响应内容，拒绝跳转。任意一个成功即视为联网，连续两轮全部失败才尝试认证。单次网络请求超时为 4 秒；DNS 或系统网络栈异常时实际周期可能延长。

- 认证运行在独立线程，监控继续检测网络；正常情况下同一时间只有一次认证。使用用户级单实例锁防止重复运行，停止通过平台事件或信号通知，不按进程名批量杀进程。

- 已检查真实入口和脚本：账号认证标签 `.tab-item[data="account"]`，eLearning 选项 `[data-value="@study"]`，输入框 `#username`、`#password`，提交按钮 `#login-account`。选择后验证底层 select 值，取消记住密码，勾选页面服务协议。若出现验证码，跳过自动提交，需要手动打开校园网页面完成认证。

- 登录后多次检查外网恢复，失败按 60、120、240、480、900 秒退避，之后最多每 15 分钟重试。已联网时不会主动注销或重新登录。只有检测失败并且能操作到认证表单时才提交凭据。

- 每次使用临时浏览器上下文，不保存浏览器配置、Cookie、截图、追踪或 HAR；限制该上下文请求到指定认证主机。日志不记录用户名、密码、网页正文或可能包含密码的异常信息。

- 日志每份最多 1 MiB，保留 5 份备份。常用事件：`INTERNET_ONLINE`、`RECOVERY_ATTEMPT`、`WIFI_CONNECT`、`WIFI_CONNECTED`、`RECOVERY_VERIFIED`、`HTTP_LOGIN_OK`、`CREDENTIALS_MISSING`、`CAPTCHA_REQUIRED`、`AUTH_ERROR`。

所有外部探测端点都不可达并不必然代表认证失效，因此只有真实登录表单可用时才会尝试提交。学校入口使用 HTTP，本工具遵循该入口，不能为学校的传输协议增加 HTTPS 安全保障。自动认证包含勾选学校页面服务协议。

## 跨平台

认证不依赖浏览器，所以老系统也能用。

| 能力 | Windows 7 / 8 / 8.1 | Windows 10 / 11 | macOS | Linux |
|---|---|---|---|---|
| HTTP 认证 | 完整 | 完整 | 完整 | 完整 |
| 浏览器兜底 | 不可用 | 完整 | 完整 | 完整 |
| Wi-Fi 恢复 | 完整 | 完整 | 需定位权限 | 需 NetworkManager |
| 凭据存储 | 凭据管理器 | 凭据管理器 | 钥匙串 | 密钥环，可降级 |

老 Windows 用 Python 3.8，代码按 3.8 语法写，不使用 3.9 以后才有的写法。凭据在 Windows 上存入凭据管理器（目标名 `CampusAutoAuth/10.10.0.166/eLearning/v1`），macOS 走钥匙串，Linux 走 SecretService；密钥环不可用时退回 0600 权限的 `credentials.json`，并在日志写一次 `CREDENTIALS_FILE_FALLBACK`。

日志位置：Windows `%LOCALAPPDATA%\CampusAutoAuth\logs\monitor.log`，macOS `~/Library/Logs/CampusAutoAuth/monitor.log`，Linux `$XDG_STATE_HOME/campus-autoauth/logs/monitor.log`。

默认 `auth_mode` 为 `auto`：先走 HTTP，验证码或连续两次失败才启用浏览器。在 `outputs/config.json` 里写 `auth_mode` 可以改成 `http` 或 `browser`，也可以用环境变量 `CAMPUS_AUTH_MODE` 临时指定。

## 认证协议

门户是 SRun，流程为取本机 IP、`get_challenge` 取 token、`srun_portal?action=login` 提交。`info` 是 `{"username","password","ip","acid","enc_ver"}` 经 XEncode（XXTEA 变体）后用打乱字母表的 Base64 编码，前缀 `{SRBX1}`；密码字段是 `{MD5}` 加 HMAC-MD5；`chksum` 按固定顺序拼接各字段后取 SHA1。

`ac_id=2`、`n=200`、`type=1`、`enc_ver=srun_bx1`、账号后缀 `@study` 来自门户前端，2020 年与 2026 年两份公开抓包一致。换校区或门户升级后需要重新抓包确认这几个值。请求不使用环境代理，也不跟随跳转，凭据要么到达 `10.10.0.166`，要么不发出去。

## 无人值守

监控不会因为一次异常退出：单次认证出错只记一条日志，整个循环出错等 30 秒重来。macOS 用 launchd 的 `KeepAlive`、Linux 用 systemd 的 `Restart=on-failure`，两者都只在非零退出时重启；`stop` 让进程以 0 退出，所以不会被拉回来。

每轮写一次心跳，`status` 会显示上次检测时间：

```
Running (windows, auth_mode=auto), last check 3s ago, online, 0 failures
```

单次认证超过 5 分钟记 `AUTH_TIMEOUT` 并放弃，恢复流程继续；同时在跑的尝试最多 3 个。连续 3 次被门户拒绝后暂停尝试，暂停时间从 10 分钟翻倍到 1 小时，避免密码错误把账号打死。`status` 运行中返回 0、停止返回 1，`start` 未能在 6 秒内拿到锁返回 1，可以直接用于巡检。

门户本身是 HTTP，密码在 `info` 字段里只经过 XEncode 混淆，不是加密强度的保护，客户端补不上这段传输加密。出现验证码时需要人工完成一次。Windows 没有等价的 init，进程被硬杀后需要重新登录或重启才会恢复。

每位使用者都需要在本机录入自己的凭据。不同网络环境下仍需验证完整重连效果；已联网时不会强制断开现有认证。若学校修改网页结构，浏览器路径会失败并退避，需要重新检查选择器；HTTP 路径不受页面改版影响。
