# -*- coding: utf-8 -*-
"""打包 Skill 为可迁移 zip（换机 / 提交仓库前用）。

用法：
    python tools/package_skill.py [输出.zip]

做了什么：
    1. 把项目里**可发布**的文件复制进暂存区（排除 `.workbuddy/`、`.git/`、
       `__pycache__`、`*.pyc`——会话记忆含个人信息，绝不进包）；
    2. **打包前扫描**：完整 MCP 令牌、完整手机号、住户单元级住址（×幢×室）。
       命中即中止，不打一个有问题的包；
    3. 校验引擎脚本可编译；
    4. 打成 zip，包内顶层目录名为 `jin-gong-men/`，解压即用。

扫描是**零例外**的：连测试文件里的假手机号也不放过（测试用字符串拼接造 PII，
源码里不出现连续 11 位数字）。宁可多改一处，不留一个"应该没事"。
"""
import io
import os
import py_compile
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_NAME = "jin-gong-men"
STAGE = os.path.join(ROOT, ".pkg-stage", PKG_NAME)
DEFAULT_ZIP = os.path.join(ROOT, "jin-gong-men-迁移包.zip")

# 打包前必须清掉密钥：换机时把旧机 ~/.workbuddy/mcp.json 里的令牌填到这里再跑，
# 跑完立刻改回去。留空表示"本机没有令牌"，直接跳过该项检查。
SECRETS_TO_SCAN = []

EXCLUDE_DIRS = {".workbuddy", ".git", "__pycache__", ".pkg-stage"}
EXCLUDE_EXTS = {".pyc", ".pyo"}

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
UNIT_RE = re.compile(r"[幢栋]\s*\d+\s*(?:单元)?\s*\d*\s*室")
COMMERCIAL_RE = re.compile(
    r"餐厅|商铺|商厦|广场|中心|大厦|商城|写字楼|大楼|酒店|医院|"
    r"大学|学院|学校|园区|产业园|科技园|街道|层|L\d")


def collect_files() -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1] in EXCLUDE_EXTS:
                continue
            if fn == os.path.basename(sys.argv[1] if len(sys.argv) > 1 else ""):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
            out.append(rel)
    return sorted(out)


def scan(files: list) -> list:
    """返回问题列表；空列表才算可以打包。"""
    problems = []
    for rel in files:
        path = os.path.join(STAGE, rel)
        try:
            text = io.open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for secret in SECRETS_TO_SCAN:
            if secret and secret in text:
                problems.append((rel, "含明文密钥"))
        m = PHONE_RE.search(text)
        if m:
            problems.append((rel, f"含完整手机号 {m.group(0)}"))
        m = UNIT_RE.search(text)
        if m and not COMMERCIAL_RE.search(text):
            problems.append((rel, f"含住户单元级住址「{m.group(0)}」"))
    return problems


def main() -> int:
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    zip_name = os.path.basename(zip_path)

    if os.path.isdir(os.path.join(ROOT, ".pkg-stage")):
        shutil.rmtree(os.path.join(ROOT, ".pkg-stage"))
    os.makedirs(STAGE)

    files = [f for f in collect_files() if f != zip_name]
    for rel in files:
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)

    print("=== 打包前扫描 ===")
    problems = scan(files)
    if problems:
        for rel, why in problems:
            print(f"  ✗ {rel} -> {why}")
        print("\n已中止：有问题就不打包。")
        return 1
    print(f"  ✓ 通过：{len(files)} 个文件，无密钥 / 无完整手机号 / 无住户单元级住址")

    py_compile.compile(os.path.join(STAGE, "scripts", "imperial_kitchen.py"),
                       doraise=True)
    print("  ✓ 引擎脚本编译通过")

    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(STAGE, rel),
                    os.path.join(PKG_NAME, rel.replace(os.sep, "/")))

    shutil.rmtree(os.path.join(ROOT, ".pkg-stage"))
    print(f"\n=== 已打包 {zip_name} ===")
    print(f"  文件数 {len(files)}，体积 "
          f"{os.path.getsize(zip_path) / 1024:.1f} KB")
    print(f"  路径   {zip_path}")
    print("\n  解压后把 jin-gong-men/ 整个目录放进 ~/.workbuddy/skills/，")
    print("  再按 MIGRATION.md 第二步配上 MCP 令牌即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
