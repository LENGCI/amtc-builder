# amtc for ImmortalWrt —— GitHub Actions 自编译脚本

在官方 ImmortalWrt SDK 里交叉编译 [schnoddelbotz/amtc](https://github.com/schnoddelbotz/amtc)
（Intel AMT / vPro 批量管理 CLI），产出可直接装到路由器上的包。不需要在本机装 OpenWrt 编译环境。

> **ImmortalWrt 25.12 起不再使用 `.ipk`**：包管理器从 opkg 换成了 apk，官方源和
> ImageBuilder 只认 `.apk`，ipk 在 25.12 上装不上。所以本脚本在 25.12.x 上产出 **`.apk`**；
> 若你要给 24.10.x（opkg）用，把输入 `immortalwrt_version` 填 `24.10.6`，就产出 `.ipk`。

## 文件

```
.
├── .github/workflows/build-amtc.yml     # ← 主角，一个文件就能跑（自包含）
├── package/amtc/Makefile                # 可选的“外置”包定义（workflow 会优先用它）
├── package/amtc/host-tools/xxd          # 构建期 xxd -i 垫片（perl）
└── tools/gen-workflow.py                # 把上面两个文件同步内嵌进 workflow 的生成脚本
```

两种用法，任选其一：

| 用法 | 做法 | 适合 |
| --- | --- | --- |
| **A. 只要一个文件** | 只把 `.github/workflows/build-amtc.yml` 放进你的仓库即可，脚本会自己内联生成包定义 | 最省事 |
| **B. 包定义外置维护** | 同时放 `package/amtc/`；workflow 检测到就直接用仓库里的那份 | 想改版本 / 打补丁 |

用 B 时如果改了 `package/amtc/` 里的东西，跑一下 `python3 tools/gen-workflow.py`，
让 workflow 里内嵌的那份保持同步（不改也行，B 情况下以仓库文件为准）。

## 跑起来

1. 把 `build-amtc.yml` 推到仓库（`main`/`master` 分支）。
2. 仓库 → **Actions** → 左侧 **build-amtc** → **Run workflow**：

   | 输入 | 说明 | 默认 |
   | --- | --- | --- |
   | `immortalwrt_version` | ImmortalWrt 版本号。25.12.2 → apk，24.10.6 → ipk | `25.12.2` |
   | `targets` | 逗号分隔的 `board/subtarget`，可随意增删 | `x86/64, armsr/armv8, mediatek/filogic, ramips/mt7621` |

3. 每个 target 是一个并行 job：下载对应 SDK（约 0.6 GB，走 Actions 缓存）→ 更新 feeds →
   编译 amtc 及其依赖 → 校验包元数据 → 上传 artifact。
4. 结果在 **Artifacts**：`amtc-<版本>-<target>`，内含 `amtc-*.apk`（或 `.ipk`）与依赖 `libcurl4-*.apk`。

## 路由器上安装

**25.12 / apk：**

```sh
apk update
apk add --allow-untrusted --force-non-repository /tmp/amtc-0.8.5-r1.apk
amtc --version          # amtc v0.8.5
```

* 未签名包 → 必须 `--allow-untrusted`；
* 本地文件不在仓库缓存里 → 必须 `--force-non-repository`；
* 依赖 `libcurl4` 会自动从官方源装上；离线环境就把 artifact 里的 `libcurl4-*.apk` 一起装。

**24.10 / opkg：**

```sh
opkg update
opkg install libcurl4
opkg install /tmp/amtc_0.8.5-1_<arch>.ipk
```

## 脚本干了什么

| 步骤 | 内容 |
| --- | --- |
| Build matrix | 把 `targets` 输入拆成 matrix（`board/subtarget` → `board-subtarget`） |
| 清理磁盘 / 装依赖 | 删掉 runner 上没用的 SDK，装 `gawk rsync zstd file python3 perl libncurses-dev` 等 |
| 缓存在 + 下载 SDK | 从 `downloads.immortalwrt.org/releases/<版本>/targets/<target>/` 目录列表里**正则取 SDK 文件名**（不写死 gcc 版本） |
| 解压 SDK / 更新 feeds | `./scripts/feeds update base packages && ./scripts/feeds install -a` |
| Stage package | 仓库有 `package/amtc/` 就用，没有就内联写出来（含 `host-tools/xxd`） |
| 配置 | 最小 `.config`：`CONFIG_ALL=n` + `CONFIG_PACKAGE_amtc=y` + `CONFIG_PACKAGE_libcurl=y` |
| 编译 | `make package/amtc/compile -j$(nproc)`（依赖由包里的 `PKG_BUILD_DEPENDS:=curl` 拉起） |
| 校验 + 产物 | `apk adbdump` 看元数据并写进 job summary；上传 artifact；失败时保留 `build.log` |

## 包定义里的 5 个“坑”（都已绕过）

1. **amtterm 子模块拉不下来**：`.gitmodules` 里的 `git://git.kraxel.org/amtterm` 早已连不通，
   而 OpenWrt 下载器会自动 `git submodule update` 然后失败 → `PKG_SOURCE_SUBMODULES:=skip`，
   改在 `Build/Prepare` 里从 GitHub 镜像 `kraxel/amtterm` 拉取。
2. **amtterm 版本必须是 v1.4**（amtc 仓库里记录的那个 commit）：amtterm 1.8 的 `redir.h` 会
   `#include <stdbool.h>`，跟 amtc 自己的 `typedef enum { false, true } bool;` 直接冲突。
3. **SDK 里的 `xxd` 是残次品**：`staging_dir/host/bin/xxd` 实际是 `scripts/xxdi.pl`，只往 stdout
   打印、不支持 `xxd -i in out` 的输出文件名参数 → 包内自带 perl 垫片并插到 `TARGET_PATH_PKG` 最前。
4. **GCC 14 把隐式函数声明当错误**（`amtc.c` 在定义前调用了 `amtterm_session()`）→
   `-Wno-implicit-function-declaration`。
5. **`DEPENDS:=+libcurl` 只是运行期依赖**，`make package/amtc/compile` 不会先编 curl，
   会报 `curl/curl.h: No such file` → 加 `PKG_BUILD_DEPENDS:=curl`；
   另外 SDK 默认 `CONFIG_ALL=y`（会把全世界的包都编一遍），脚本里换成了最小配置。

## 本机手动编译（不想用 Actions）

```sh
sudo apt install -y build-essential gawk rsync zstd file python3 perl git
wget https://downloads.immortalwrt.org/releases/25.12.2/targets/x86/64/immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst
tar --zstd -xf immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst
cd immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64

cp -a /path/to/package/amtc package/amtc
./scripts/feeds update base packages
./scripts/feeds install -a

printf '%s\n' 'CONFIG_ALL=n' 'CONFIG_ALL_KMODS=n' 'CONFIG_ALL_NONSHARED=n' \
  'CONFIG_PACKAGE_amtc=y' 'CONFIG_PACKAGE_libcurl=y' > .config
make defconfig
make package/amtc/compile V=s -j$(nproc)

ls bin/packages/*/*/amtc-*.apk
```

## 验证情况

* **25.12.2 / x86_64**：用官方 SDK（`immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl`）跑通完整流程
  （feeds → defconfig → `make package/amtc/compile`），得到 `amtc-0.8.5-r1.apk`：
  二进制 `NEEDED: libcurl.so.4 / libgcc_s.so.1 / libc.so`，元数据
  `depends: libc, libcurl4, libpthread`，内含 `usr/bin/amtc` + `usr/share/man/man1/amtc.1`。
  工作流里“内联生成包定义”那一步也是实跑验证过的（生成结果与 `package/amtc/` 逐字节一致）。
* **其他 target**（armsr、mediatek/filogic、ramips/mt7621 …）：已验证 SDK 存在与命名规则，
  实际编译交给 Actions；若某个架构有工具链层面的意外，把 job 日志发我。
* **24.10.x（ipk）**：包定义与流程通用（`TARGET_PATH_PKG`、`SUBMODULES:=skip` 在 24.10 里都支持），
  但没有实测过。

## 说明

* 只打 **amtc 命令行工具**（含 SOL 串口重定向，因为静态链接了 GPL 的 amtterm）。
  上游那个 `amtc-web`（PHP 版 Web 界面）没打包：要 PHP + 数据库 + httpd，路由器上意义不大。
* 许可：amtc 本体 MIT，amtterm GPL-2.0-only，所以二进制整体按 **GPL-2.0-only** 分发。
* 包本身约 20 KB，真正的大头是依赖 `libcurl4`。
