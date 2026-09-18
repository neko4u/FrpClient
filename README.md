# FRPClient

基于 **PyQt6 + frp（定制 fork 版 frpc）** 的内网穿透桌面客户端。

采用「两级连接」模型：**先连接平台（Django）开始计时，再连接 FRP 建立隧道**。平台负责鉴权、计时与端口分配，frps 负责按 uid 管理连接。

- 客户端界面：`sorielconnection`
- 平台地址：`https://sorielflow.com`
- frps 控制端口：`7000`（远程端口由服务器在 `6100-6500` 内动态分配）

---

## 一、环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（x64） |
| Python | 3.11（项目自带虚拟环境 `venv/`） |
| 依赖 | 见 `requirements.txt`（PyQt6 / requests / toml / psutil 等） |

### 安装依赖

```powershell
cd E:\Projects\FRPClient
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 若 `venv/` 不存在，先创建：
> ```powershell
> python -m venv venv
> .\venv\Scripts\python.exe -m pip install -r requirements.txt
> ```

### 运行

```powershell
cd E:\Projects\FRPClient
.\venv\Scripts\python.exe main.py
```

---

## 二、目录结构

```
FRPClient/
├─ main.py                      # 程序入口（token 恢复 → 主界面 / 登录窗）
├─ main.spec                    # PyInstaller 打包配置
├─ requirements.txt
├─ core/
│  ├─ paths.py                  # 资源路径（开发态 / 打包态统一）
│  ├─ token_storage.py          # token 落盘（以 JWT exp 为准）
│  ├─ token_holder.py           # token / uid 内存持有
│  ├─ jwt_utils.py              # 解 JWT payload 取 uid
│  ├─ config_manager.py         # 读写 frpc.toml（serverAddr / token / localPort / remotePort）
│  ├─ api_client.py             # 旧版同步接口（拉 FrpToken）
│  ├─ session_api.py            # 会话 & 端口接口封装（QNetworkAccessManager 异步）
│  ├─ session_manager.py        # 会话状态机 + 30s 心跳 + 倒计时
│  └─ frp_manager.py            # 启动/停止 frpc 进程，采集其日志与状态
├─ services/
│  └─ api_client.py             # 登录接口（异步）
├─ ui/
│  ├─ login_window.py           # 登录窗
│  ├─ main_window.py            # 主窗口
│  └─ widgets/                  # proxy_table / config_form（当前主界面未使用，代码保留）
├─ resources/                   # 运行时资源（见下）
│  ├─ frpc.exe                  # ⚠ 必须是 fork 版（支持 --uid）
│  ├─ origin_frpc.exe           # 原生 v0.65 备份（不可用于本系统）
│  ├─ frpc.toml                 # frpc 配置（远程端口会被服务器下发值覆盖）
│  ├─ config.json               # 平台接口地址等
│  └─ token.json                # 登录凭据（运行时生成，勿提交）
└─ bak/                         # 本地改动备份（不推送）
```

---

## 三、配置说明

### `resources/config.json`

```json
{
  "frp_token_api": "https://sorielflow.com/api/FrpToken",
  "frpc_path": "./bin/frpc",
  "frpc_config_path": "./frpc.toml"
}
```

### `resources/frpc.toml`

frpc 启动配置。**其中 `remotePort` 不是固定的**——每次点「连接」时，客户端会向平台申请一个空闲端口，并覆盖写入该字段，然后才启动 frpc。

```toml
serverAddr = "43.139.151.71"
serverPort = 7000

[[proxies]]
name = "默认链接1"
type = "tcp"
localIP = "127.0.0.1"
localPort = 7777          # 用户可在界面修改（仅数字）
remotePort = 6000         # 占位值，连接时由服务器分配值覆盖

[auth]
method = "token"
token = "..."             # 登录后由平台下发覆盖
```

---

## 四、使用流程

1. **登录** —— 输入账号密码；成功后 token 落盘（有效期与 JWT 一致，当前 3 天）
2. **开启时长** —— 建立平台会话并开始计时，右上角显示剩余时长并实时倒计时
3. **连接** —— 依次执行：申请远程端口 → 写入 `remotePort` → 启动 frpc（带 `--uid`）
4. **获取外网地址** —— 界面显示 `ai.sorielflow.com:<分配的端口>`，可一键复制
5. **断开** —— 停止 frpc 并释放端口
6. **暂停时长** —— 若 FRP 已连接，会**先停 frpc 再结束会话**（结算并退回剩余时长）

> 门禁规则：**必须先开启时长，才能连接 FRP**。

---

## 五、依赖的服务端接口

均需 `Authorization: Bearer <JWT>`（`/token_login/` 除外）。

| 接口 | 方法 | 说明 |
|---|---|---|
| `/token_login/` | POST | 表单 `user` / `pwd` → 返回 JWT 与 `expires_in` |
| `/api/FrpToken` | GET | 获取 frps 的 `config_token`，写入 `frpc.toml` |
| `/api/frp_session/start/` | POST | 开启会话 → `session_id` / `balance_seconds` / `stop_time_ts` |
| `/api/frp_session/heartbeat/` | POST | 心跳（30s 一次，body 带 `session_id`） |
| `/api/frp_session/stop/` | POST | 结束会话并结算 |
| `/api/frp_session/status/` | GET | 查询当前会话与余额 |
| `/api/frp_port/allocate/` | POST | 申请远程端口（需已开启时长） |
| `/api/frp_port/release/` | POST | 释放远程端口 |
| `/api/frp_port/` | GET | 查询当前端口 |

**frpc 启动命令**（由 `core/frp_manager.py` 组装）：

```
frpc.exe -c <resources>/frpc.toml --uid <uid>
```

---

## 六、打包

```powershell
.\venv\Scripts\pyinstaller.exe main.spec
```

- 产物在 `dist/`，`resources/` 下的 `frpc.exe`、`frpc.toml`、`config.json` 会被一并打入
- **若资源路径有问题**，检查 `core/paths.py` 对「打包态」的资源目录解析
- 打包前确认 `resources/frpc.exe` 是 **fork 版**（体积约 24.6 MB，原生版约 16.4 MB）

---

## 七、常见问题

### 1. frpc.exe 被杀毒软件删除

`frp` 类内网穿透工具常被 Windows Defender 等误判为 PUA。处理办法：

- 将程序目录加入杀软排除项；
- 分发时附《误报处理指引》；正式发布建议对 frpc.exe 与打包产物做**代码签名**。

### 2. 登录后所有接口 401 / 提示"请重新登录"

本地 token 已过期。客户端会自动退回登录页，重新登录即可（有效期 3 天）。

### 3. 连接成功但外网访问不通

需要服务器**放行 6100-6500 端口**（腾讯云安全组 + 服务器 firewalld），否则外部无法连入分配到的端口。

### 4. 提示"请先开启时长"

FRP 连接的前提是平台会话处于 active 状态，请先点「开启时长」。

### 5. 查看运行日志

主界面顶部菜单 **关于 → 运行日志**（弹窗显示 frpc 输出，再点一次隐藏）。

---

## 八、开发约定

- **改动前先备份**到 `bak/`（命名如 `xxx.py.bak_MMDD`），`bak/` 不推送
- `resources/token.json` 为运行时产物，**不要提交**
- 端口/时长等业务数字以服务端返回为准，客户端只做展示与倒计时（用服务器时间校准）
- `ui/widgets/` 下组件当前未在主界面使用，代码保留备用
