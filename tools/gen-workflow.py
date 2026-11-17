#!/usr/bin/env python3
"""
生成自包含的 .github/workflows/build-amtc.yml：
把 package/amtc/Makefile 与 package/amtc/host-tools/xxd 以 heredoc 形式内嵌进
workflow 的 “Stage package” 步骤，这样单个 YAML 文件即可完成编译。
内嵌内容按行原样拼入（TAB 保留），并由 YAML 块标量的缩进规则对齐。
"""
import pathlib
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "package/amtc/Makefile"
XXD = ROOT / "package/amtc/host-tools/xxd"
OUT = ROOT / ".github/workflows/build-amtc.yml"

INDENT = " " * 10          # run: | 块的内容缩进（10 空格）
INDLINE = INDENT           # heredoc 结束符也要保持同样缩进


def embed(path: pathlib.Path) -> str:
    """把文件内容变成可直接放进 YAML 块标量的文本：每行前加 INDENT，空行留空。"""
    lines = []
    for line in path.read_text().splitlines():
        lines.append(INDENT + line if line.strip() else "")
    return "\n".join(lines)


WORKFLOW = f"""\
name: build-amtc

# 在官方 ImmortalWrt SDK 里交叉编译 amtc（Intel AMT / vPro 批量管理 CLI），
# 产出可直接在路由器上安装的包：
#   25.12.x  ->  apk（ImmortalWrt >= 25.12 已经改用 apk，ipk 装不上）
#   24.10.x  ->  ipk（opkg）
#
# 本文件是自包含的：不需要仓库里有其它文件。如果你更愿意把包定义放在
# package/amtc/ 里维护，本 workflow 也会优先使用仓库里的那一份（见 “Stage package”）。
on:
  workflow_dispatch:
    inputs:
      immortalwrt_version:
        description: "ImmortalWrt 版本号（25.12.2 = apk；24.10.6 = ipk）"
        required: true
        default: "25.12.2"
      targets:
        description: "目标平台，逗号分隔的 board/subtarget（例如 x86/64, ramips/mt7621）"
        required: true
        default: "x86/64, armsr/armv8, mediatek/filogic, ramips/mt7621"
  push:
    branches: [main, master]
    paths:
      - ".github/workflows/build-amtc.yml"
      - "package/**"

permissions:
  contents: read

jobs:
  # ---------------------------------------------------------------------------
  # 把逗号分隔的 targets 变成 matrix
  # ---------------------------------------------------------------------------
  prepare:
    runs-on: ubuntu-24.04
    outputs:
      matrix: ${{{{ steps.gen.outputs.matrix }}}}
    steps:
      - name: Build matrix
        id: gen
        shell: bash
        env:
          TARGETS: ${{{{ inputs.targets || 'x86/64, armsr/armv8, mediatek/filogic, ramips/mt7621' }}}}
        run: |
          set -euo pipefail
          python3 - <<'PY' >> "$GITHUB_OUTPUT"
          import json, os
          raw = os.environ.get("TARGETS") or "x86/64"
          items = []
          for t in raw.split(","):
              t = t.strip().strip("/")
              if not t:
                  continue
              if t.count("/") != 1:
                  raise SystemExit(f"目标格式不对: '{{t}}'，应为 board/subtarget，例如 x86/64")
              items.append({{"target": t, "slug": t.replace("/", "-")}})
          print("matrix=" + json.dumps({{"include": items}}))
          PY

  # ---------------------------------------------------------------------------
  # 交叉编译
  # ---------------------------------------------------------------------------
  build:
    needs: prepare
    runs-on: ubuntu-24.04
    name: amtc ${{{{ matrix.target }}}}
    timeout-minutes: 90
    strategy:
      fail-fast: false
      matrix: ${{{{ fromJSON(needs.prepare.outputs.matrix) }}}}
    env:
      IWRT_VERSION: ${{{{ inputs.immortalwrt_version || '25.12.2' }}}}
      TARGET: ${{{{ matrix.target }}}}
      SLUG: ${{{{ matrix.slug }}}}
    steps:
      - uses: actions/checkout@v4

      - name: 清理磁盘空间
        run: |
          sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc \\
                      /opt/hostedtoolcache/CodeQL /usr/local/share/boost \\
                      /usr/lib/jvm /usr/local/lib/node_modules || true
          sudo apt-get clean
          df -h /

      - name: 安装主机构建依赖
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends \\
            build-essential g++ file rsync gawk zstd xz-utils git curl \\
            ca-certificates unzip python3 perl libncurses-dev bc

      # SDK 压缩包约 0.6 GB，缓存起来可以让重跑快很多
      - name: 缓存 SDK 压缩包
        uses: actions/cache@v4
        with:
          path: sdk-dl
          key: iwrt-sdk-${{{{ env.IWRT_VERSION }}}}-${{{{ env.SLUG }}}}

      - name: 下载 ImmortalWrt SDK
        run: |
          set -euo pipefail
          mkdir -p sdk-dl
          base="https://downloads.immortalwrt.org/releases/${{IWRT_VERSION}}/targets/${{TARGET}}/"
          echo "SDK 目录: $base"
          listing=$(curl -fsSL --retry 3 "$base") || {{
            echo "::error::打不开 $base —— 版本号或 target/subtarget 填错了？"; exit 1; }}
          # 不写死 gcc 版本，直接从目录列表里取 SDK 文件名
          sdk=$(printf '%s' "$listing" \\
            | grep -oE 'immortalwrt-sdk-[^"<> ]+\\.Linux-x86_64\\.tar\\.(zst|xz)' \\
            | sort -u | head -n1)
          if [ -z "$sdk" ]; then
            echo "::error::${{TARGET}} 在 ${{IWRT_VERSION}} 下没有 SDK"
            printf '%s' "$listing" | grep -oE 'immortalwrt-sdk[^"<> ]*' | head -n5 || true
            exit 1
          fi
          echo "SDK: $sdk"
          if [ ! -s "sdk-dl/$sdk" ]; then
            curl -fL --retry 3 -o "sdk-dl/$sdk.part" "$base$sdk"
            mv "sdk-dl/$sdk.part" "sdk-dl/$sdk"
          fi
          ls -lh sdk-dl/

      - name: 解压 SDK
        run: |
          set -euo pipefail
          mkdir -p sdk
          shopt -s nullglob
          for f in sdk-dl/*.tar.zst; do tar --zstd -xf "$f" -C sdk; done
          for f in sdk-dl/*.tar.xz;  do tar -xJf   "$f" -C sdk; done
          sdk_dir=$(find sdk -maxdepth 1 -mindepth 1 -type d -name 'immortalwrt-sdk-*' | head -n1)
          [ -n "$sdk_dir" ] || {{ echo "::error::SDK 解压失败"; exit 1; }}
          echo "SDK_DIR=$PWD/$sdk_dir" >> "$GITHUB_ENV"
          if [ -x "$sdk_dir/staging_dir/host/bin/apk" ]; then
            echo "这是 apk 系 SDK（ImmortalWrt >= 25.12），将产出 .apk"
          else
            echo "这是 opkg 系 SDK（ImmortalWrt <= 24.10），将产出 .ipk"
          fi
          df -h /

      - name: 更新 feeds（libcurl 及其依赖来自这里）
        run: |
          set -euo pipefail
          cd "$SDK_DIR"
          ./scripts/feeds update base packages
          # -a 会把两个 feed 里所有包定义都链进 package/feeds/，
          # 这样 libcurl 的依赖链（openssl / zlib / ca-bundle ...）才认得全
          ./scripts/feeds install -a || true
          ls -d package/feeds/*

      # 仓库里没有 package/amtc/ 时，就把包定义内联生成出来（本文件自包含的关键）
      - name: Stage package（仓库里有就用仓库的，没有就内联生成）
        run: |
          set -euo pipefail
          dst="$SDK_DIR/package/amtc"
          rm -rf "$dst"
          if [ -f "$GITHUB_WORKSPACE/package/amtc/Makefile" ]; then
            echo "使用仓库里的 package/amtc/"
            cp -a "$GITHUB_WORKSPACE/package/amtc" "$dst"
          else
            echo "仓库里没有 package/amtc/，使用内联定义"
            mkdir -p "$dst/host-tools"
            cat > "$dst/Makefile" <<'AMTC_MAKEFILE'
{embed(MAKEFILE)}
{INDLINE}AMTC_MAKEFILE

            cat > "$dst/host-tools/xxd" <<'AMTC_XXD'
{embed(XXD)}
{INDLINE}AMTC_XXD
            chmod +x "$dst/host-tools/xxd"
          fi
          ls -l "$dst" "$dst/host-tools"
          head -n 3 "$dst/host-tools/xxd"

      - name: 配置（最小 .config）
        run: |
          set -euo pipefail
          cd "$SDK_DIR"
          # SDK 默认配置带 CONFIG_ALL=y（= 把全世界的包都编一遍），这里换成最小配置
          printf '%s\\n' \\
            'CONFIG_ALL=n' \\
            'CONFIG_ALL_KMODS=n' \\
            'CONFIG_ALL_NONSHARED=n' \\
            'CONFIG_PACKAGE_amtc=y' \\
            'CONFIG_PACKAGE_libcurl=y' > .config
          make defconfig
          grep -E '^CONFIG_PACKAGE_(amtc|libcurl)=y' .config

      - name: 编译
        run: |
          set -euo pipefail
          cd "$SDK_DIR"
          # 包定义里的 PKG_BUILD_DEPENDS:=curl 会先把 curl（以及 openssl/zlib/nghttp2）
          # 编好并装进 staging_dir，然后才编 amtc
          make package/amtc/compile V=s -j"$(nproc)" 2>&1 | tee build.log
          find bin/packages \\( -name 'amtc-*.apk' -o -name 'amtc_*.ipk' \\) | tee /tmp/built.txt
          [ -s /tmp/built.txt ] || {{ echo "::error::没有产出 amtc 包"; exit 1; }}

      - name: 校验并写入任务摘要
        run: |
          set -euo pipefail
          cd "$SDK_DIR"
          {{
            echo "## amtc / ImmortalWrt ${{IWRT_VERSION}} / ${{TARGET}}"
            echo
            echo '```'
            for f in bin/packages/*/*/amtc-*.apk; do
              [ -e "$f" ] || continue
              echo "== $f"
              staging_dir/host/bin/apk adbdump "$f" | sed -n '1,22p'
            done
            for f in bin/packages/*/*/amtc_*.ipk; do
              [ -e "$f" ] || continue
              echo "== $f"; tar -tzf "$f"
            done
            echo '```'
          }} | tee -a "$GITHUB_STEP_SUMMARY"

      - name: 收集产物
        run: |
          set -euo pipefail
          mkdir -p out
          find "$SDK_DIR/bin/packages" \\( -name 'amtc-*.apk' -o -name 'amtc_*.ipk' \\) -exec cp -v {{}} out/ \\;
          # 顺手带上它唯一的非 base 运行期依赖，方便离线安装
          find "$SDK_DIR/bin/packages" \\( -name 'libcurl*.apk' -o -name 'libcurl*.ipk' \\) -exec cp -v {{}} out/ \\; || true
          ls -lh out/

      - name: 上传产物
        uses: actions/upload-artifact@v4
        with:
          name: amtc-${{{{ env.IWRT_VERSION }}}}-${{{{ env.SLUG }}}}
          path: out/*
          if-no-files-found: error

      - name: 失败时保留构建日志
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: buildlog-${{{{ env.IWRT_VERSION }}}}-${{{{ env.SLUG }}}}
          path: |
            ${{{{ env.SDK_DIR }}}}/build.log
            ${{{{ env.SDK_DIR }}}}/logs
          if-no-files-found: ignore
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(WORKFLOW)
print(f"wrote {OUT} ({len(WORKFLOW)} bytes)")
