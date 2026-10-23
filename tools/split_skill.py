# -*- coding: utf-8 -*-
"""把 SKILL.md 拆成「核心 + 按需取用的子文件」。

原则：内容一条不丢，只做搬家与加指引头。
拆分动机见 docs/TESTING.md —— 原 538 行一次性注入，模型会把七步一次跑完，
首响动辄十几分钟。改为渐进式披露后，首响只需读核心。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "SKILL.md")
LINES = io.open(SRC, encoding="utf-8").read().split("\n")


def rng(a, b):
    """取 1-indexed 闭区间 [a, b]"""
    return "\n".join(LINES[a - 1:b]).strip("\n")


def head(title, when):
    return (f"# {title}\n\n"
            f"> 本文件是 `SKILL.md` 的**按需子文件**。\n"
            f"> **何时读**：{when}\n"
            f"> 不要预先读取——读到才读。\n\n---\n\n")


OUT = {}

OUT["workflow/02-maicalendar.md"] = (
    head("第二步 · 麦历呈报（观象授时）",
         "陛下已点选、臣要开始拟单时才读") + rng(150, 176) + "\n")

OUT["workflow/03-scene-and-store.md"] = (
    head("第三步 · 辨明用膳方式（到店自取 / 麦乐送外送）",
         "要定用膳方式、要查门店时才读") + rng(177, 297) + "\n")

OUT["workflow/04-photos.md"] = (
    head("第三步半 · 御膳图鉴（看图点餐）",
         "候选收敛后要上图时才读") + rng(298, 336) + "\n")

OUT["workflow/05-coupons-price.md"] = (
    head("第四步 · 户部核算 ／ 第五步 · 核对御膳账目",
         "要查券、要核价时才读") + rng(337, 359) + "\n")

OUT["workflow/06-memorial.md"] = (
    head("第六步 · 奏请定夺（呈奏折）",
         "要渲染奏折时才读") + rng(360, 379) + "\n")

OUT["workflow/07-order.md"] = (
    head("第七步（可选）· 代下单",
         "**且仅在**陛下明确说「就按这个下单」时才读") + rng(380, 399)
    + "\n\n---\n\n" + rng(465, 495) + "\n")

OUT["references/voice.md"] = (
    head("语态完整版 + 错误处理话术",
         "陛下 reply 前都要守住语态；出错时照抄话术") + rng(33, 124)
    + "\n\n---\n\n## 错误处理（照抄这些话术）\n\n" + rng(513, 524) + "\n")

OUT["references/preferences.md"] = (
    head("陛下旧例（偏好）",
         "要读或写陛下偏好时才读") + rng(400, 418) + "\n")

OUT["references/coupons.md"] = (
    head("可领券令、代领券与券的三种语义",
         "要处理券（可领 / 代领 / 本单可用）时才读") + rng(419, 464) + "\n")

for rel, content in OUT.items():
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8").write(content)
    print(f"{len(content):6d} 字符  {rel}")
