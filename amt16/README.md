# amt16 — 一个 150 行的 Intel AMT 16 命令行工具

`amt16` 是一个**单文件 POSIX shell 脚本**，只依赖 `curl`，用标准 DMTF WS-Man over TLS
操作 Intel AMT（9.0 及以后，含 AMT 16.x）：查电源状态、开机/关机/重启/强制断电、设置下次 PXE 启动。

```sh
export AMT_PASSWORD='你的AMT密码'
./amt16 info  192.168.1.88
./amt16 off   192.168.1.88 192.168.1.89 192.168.1.90
```

整个文件 348 行（含注释与 help）、14 KB，不需要 Go/Node/Python，不需要编译。

---

## 为什么还要自己写一个

AMT 16 上"现代 + 轻量 + 可维护的 vPro CLI"这个位置确实是空的：

| 工具 | 现状 |
|---|---|
| `amtc` / `amtgo`（schnoddelbotz） | 2015/2018 停更；按 2004/01 legacy SOAP 写死，AMT 16 直接 404 |
| MeshCommander | Intel 2022 年底停止支持，EOL |
| MeshCentral | 仍在维护（2026-11 仍有提交），但整套 Node.js，几百 MB |
| Intel Device Management Toolkit | 活跃（`go-wsman-messages` 天天更新），但是库 + 一堆微服务，不是 CLI |
| `amtterm` / `gamT` | 2026-05 还在发版，但只做 SOL 串口重定向 |

但 AMT 9+ 的接口本身就是标准 WS-Man over TLS（16993），做电源控制只需要 3 个 CIM 操作，
所以"轻量 CLI"可以自己用 curl 造，而且比修别人的代码更省事。

### `amt16` 顺手修掉的三个 `amtc` 硬伤

| 问题 | `amtc` | `amt16` |
|---|---|---|
| `<wsa:To>` | 所有 WS-Man 报文里写死 `http://192.168.0.100:16992/wsman` | 按 `-P`/主机实时生成为 `https://<host>:<port>/wsman` |
| Content-Type | `text/xml; charset=utf-8`（注释里自己写着应该用 soap+xml） | `application/soap+xml;charset=UTF-8` |
| TLS 版本 | `CURLOPT_SSLVERSION = TLSv1_0`，AMT 16 要求 TLS 1.2 | 交给 curl 默认（TLS 1.2+） |

---

## 安装

路由器（ImmortalWrt/OpenWrt）上只要有 curl：

```sh
apk add curl ca-bundle           # 24.10 及更早用 opkg install curl ca-bundle
# 或：opkg install curl ca-bundle
```

把脚本扔过去即可，无需打包：

```sh
scp amt16 root@192.168.1.1:/usr/bin/ && ssh root@192.168.1.1 'chmod +x /usr/bin/amt16'
```

---

## 用法

```
amt16 [options] <command> <host> [host...]
```

| 命令 | 动作 | WS-Man PowerState |
|---|---|---|
| `info` | 查当前电源状态（Enumerate→Pull `CIM_AssociatedPowerManagementService`） | — |
| `on` | 开机 | 2 |
| `off` | 直接断电（硬关） | 8 |
| `softoff` | 请求操作系统正常关机 | 12 |
| `cycle` | 断电重启 | 5 |
| `reset` | 复位 | 10 |
| `resetg` | 优雅复位 | 14 |
| `power <N>` | 直接发 `RequestPowerStateChange`，N 自定 | N |
| `pxe` | 下次从 PXE 启动（之后还需 `cycle`/`on`） | `ChangeBootOrder` → Force PXE Boot |
| `hdd` | 下次从硬盘启动 | `ChangeBootOrder` → Force Hard-drive Boot |
| `raw <file>` | 原样 POST 任意 SOAP 报文（调试用） | — |

选项：

| 选项 | 说明 |
|---|---|
| `-u <user>` | AMT 用户（默认 `admin`） |
| `-p <pass>` | 密码；不写则读 `$AMT_PASSWORD`，都没有则交互输入 |
| `-P <port>` | TLS 端口，默认 16993 |
| `-c <cafile>` | 用该 CA/PEM 校验 AMT 证书（默认不校验 —— AMT 是自签证书） |
| `-t <sec>` | curl 超时，默认 30 |
| `-v` | 把请求/响应 XML 全打到 stderr |
| `-V` / `-h` | 版本 / 帮助 |

例子：

```sh
# 批量关机，逐台返回 ok / FAILED，退出码 = 失败台数（>0 即有失败）
AMT_PASSWORD=xxx amt16 off 192.168.1.88 192.168.1.89 192.168.1.90

# 先查状态，再决定做什么
amt16 info 192.168.1.88          # =>   power=on (2)  available=2

# 装机流程：下次 PXE 启动 + 断电重启
amt16 pxe 192.168.1.88 && amt16 cycle 192.168.1.88

# 钉住证书（ACM 模式装了真证书时）
amt16 -c /etc/amt-ca.pem info 192.168.1.88

# 排障：把请求/响应报文全打出来
amt16 -v info 192.168.1.88
```

电源状态对照（`CIM_AssociatedPowerManagementService.PowerState`）：

```
2 开机      3 睡眠(浅)   4 睡眠(深)   5 断电重启      6 硬关
7 休眠      8 软关       9 硬断电重启 10 复位         11 NMI
12 优雅关机 13 优雅硬关  14 优雅复位  15/16 优雅重启
```

---

## 自测（不需要真机）

仓库里带了一个 mock AMT 服务（TLS + HTTP Digest），可以在普通 Linux 上跑完整回归：

```sh
bash test/run_tests.sh
```

覆盖：Enumerate→Pull 两段式枚举、内联枚举、6 个电源动作映射到正确 PowerState、
`ChangeBootOrder` 的 PXE/HDD 目标、SOAP Fault 解析、401/404/连接失败、多主机、`-v`、
`-c` 证书固定与错 CA 拒绝，并校验抓到的每个请求都是合法 XML。

```
total: 38 passed, 0 failed
```

同一套测试在 `bash`、`dash`、`busybox ash`（只给 busybox applet + curl）下都是 38/38，
所以路由器上的 ash 也是安全的。

---

## 已知限制

- 只做**电源 + 启动设备**。SOL 串口用 `amtterm`/`gamT`，硬件资产/KVM 用 MeshCentral。
- 只支持 HTTP Digest（AMT 默认）。Kerberos / 证书双向认证未实现。
- `info` 只读电源状态；要固件版本、UUID、网卡信息需另加 `CIM_SoftwareIdentity` 等枚举。
- 请求报文用的是 amtc / MeshCommander 同款 CIM 载荷（在 mock 上验证过结构），
  **没有在你的 AMT 16.1.30 真机上验证**。第一次跑请用 `-v` 看原始报文；
  如果 AMT 返回 Fault，把 `-v` 的输出和 `raw` 结合起来改模板即可 —— 这正是脚本形式的
  好处：改一行 XML 就能试，不用重编。

## 故障对照

| 现象 | 原因 |
|---|---|
| `HTTP 404` | 打到 legacy `/RemoteControlService` 了，或端口不对（AMT 16 没有 16992 明文） |
| `authentication failed (401)` | 密码错 / 账号被锁 / ACL（Admin 权限）/ ACM 下用户不在允许列表 |
| `TLS handshake failed` | 用了 `-c` 但 CA 不对；或 MEBx 里 AMT TLS 未启用 |
| `connection failed` | 路由不通、16993 没开（AMT 16 默认只开 TLS 端口） |
| `Fault: wsa:ActionNotSupported` | 该固件不支持此 CIM 操作（用 `-v` 看 action URI） |

## License

MIT。XML 载荷结构参考了 MIT 许可的 [schnoddelbotz/amtc](https://github.com/schnoddelbotz/amtc) 与 DMTF CIM 规范。
