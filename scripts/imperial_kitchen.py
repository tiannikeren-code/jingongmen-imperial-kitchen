# -*- coding: utf-8 -*-
"""金拱门御膳房 · 本地规则引擎

职责边界（重要）：
    本脚本【只做本地确定性计算】，不联网、不调用任何 MCP 工具、不下单。
    所有餐品、价格、优惠券数据必须由调用方（Skill / Agent）通过 MCP 真实查询后
    以 JSON 传入。本脚本绝不虚构商品名、价格或优惠。

模块划分（对应需求）：
    [1] date_context         日期 / 节气 / 节日 / 法定节假日识别，不可用时优雅降级
    [2] theme_rules          麦历：当日节气/节日主题文案与「今日宜」娱乐彩蛋（禁止吉凶预测）
    [3] preference_profile   用户偏好：区分主动告知与系统推测，支持修改清除
    [4] menu_matching        真实菜单 → 候选方案筛选（预算 / 偏好 / 主题）
    [5] coupon_optimizer     优惠候选组合筛选（本地粗筛，最终以官方核价为准）
    [6] price_verification   官方核价结果核验与标记（区分官方核验价与估算价）
    [7] recommendation_output 古风奏折渲染 + 合规自检

运行环境：仅依赖 Python 3.9+ 标准库。
用法：
    python scripts/imperial_kitchen.py date-context [--date YYYY-MM-DD] [--simulate]
    python scripts/imperial_kitchen.py theme --date YYYY-MM-DD
    python scripts/imperial_kitchen.py match --menu menu.json [--request req.json]
    python scripts/imperial_kitchen.py coupons --coupons c.json --candidates cands.json
    python scripts/imperial_kitchen.py verify-price --verified v.json
    python scripts/imperial_kitchen.py render --plan plan.json
    python scripts/imperial_kitchen.py compliance --text "..."
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date as Date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_PATH = os.path.join(ROOT, "data", "calendar.json")

CST = timezone(timedelta(hours=8))  # Asia/Shanghai，中国全境无夏令时


# ── 金额与单位 ────────────────────────────────────────────────────────
# ⚠️ 真实缺陷（2026-10-23 陛下实测发现）：奏折里餐品显示成「0.10 元」。
# 根因：同一份代码里存在两套单位——
#     calculate-price 返回「分」(1900 = 19 元)；query-meals 返回「元」('28.5')。
# 两套单位过去只靠变量名约定区分，没有任何防线；一旦把已是「元」的值
# 当成「分」再除一次 100，19 元就变成了 0.19 元。
# 故：① 格式化必须显式声明单位；② 显示前必过合理性校验。
UNIT_FEN = "fen"    # 分：calculate-price / 核价相关字段
UNIT_YUAN = "yuan"  # 元：query-meals 的 currentPrice / price

# 麦当劳单品与单笔订单的合理区间，越界即判定为换算错误，宁可不敢报
MONEY_SANE_MIN = 0.5
MONEY_SANE_MAX = 2000.0


def fmt_money(value, unit: str = UNIT_FEN) -> str:
    """按显式单位格式化金额，固定两位小数。取不到就如实说。"""
    if value is None or value == "":
        return "官方未返回价格"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "官方未返回价格"
    if unit == UNIT_FEN:
        v = v / 100.0
    return f"{v:.2f}"


def money_sanity(yuan) -> bool:
    """金额是否落在合理区间。把「元」当「分」会掉到 0.19 元，此校验即为防线。"""
    try:
        v = float(yuan)
    except (TypeError, ValueError):
        return False
    return MONEY_SANE_MIN <= v <= MONEY_SANE_MAX


def safe_money(value, unit: str = UNIT_FEN) -> str:
    """格式化并校验：金额越界时如实说「不敢报」，绝不把 0.19 元端上去。"""
    txt = fmt_money(value, unit)
    if txt == "官方未返回价格":
        return txt
    if not money_sanity(txt):
        return (f"⚠️ {txt}（金额异常，疑为单位换算有误，臣不敢以此报价）")
    return txt


def _yuan(fen) -> str:
    """分 → 元，统一两位小数（旧接口，等价 fmt_money(fen, UNIT_FEN)）。

    官方核价一律以「分」返回；直接 round(...,2) 会打出「6.0 元」这种
    不像钱的写法，金额必须固定两位小数，免得陛下看错一位。
    """
    return fmt_money(fen, UNIT_FEN)

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def today_cst() -> Date:
    return datetime.now(CST).date()


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class DataUnavailable(Exception):
    """日期数据不可用。调用方必须优雅降级，严禁编造节气或节日。"""


def load_calendar(path: str = DATA_PATH) -> dict:
    if not os.path.exists(path):
        raise DataUnavailable(f"日历数据文件不存在：{path}")
    return _load_json(path)


# ===========================================================================
# [1] date_context —— 日期、节气、传统节日、法定节假日
# ===========================================================================

SOLAR_TERM_ORDER = [
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
]

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_date_context(target: Date, simulated: bool = False,
                       calendar: dict | None = None) -> dict:
    """识别某日的节气与传统节日。

    数据缺失时返回 degraded=True 且 solar_term/festival 为 None，
    由调用方降级为普通主题，**绝不编造**。
    """
    if calendar is None:
        try:
            calendar = load_calendar()
        except DataUnavailable as exc:
            return {
                "date": target.isoformat(),
                "weekday": WEEKDAY_CN[target.weekday()],
                "simulated": simulated,
                "solar_term": None,
                "festival": None,
                "legal_holiday": None,
                "degraded": True,
                "degraded_reason": str(exc),
            }

    year = str(target.year)
    iso = target.isoformat()

    solar_term = None
    terms = calendar.get("solar_terms", {}).get(year)
    if terms:
        for name, info in terms.items():
            if info.get("date") == iso:
                solar_term = {"name": name, "moment_cst": info.get("moment_cst")}
                break

    festival = None
    festivals = calendar.get("traditional_festivals", {}).get(year) or {}
    for name, info in festivals.items():
        if info.get("date") == iso:
            festival = {"name": name, "derived_from": info.get("derived_from", "lunar")}
            break

    legal_holiday = None
    hol = calendar.get("legal_holidays", {}).get(year)
    if hol and hol.get("verified"):
        for rng in hol.get("ranges", []):
            if rng["start"] <= iso <= rng["end"]:
                legal_holiday = {"name": rng["name"], "source": hol.get("source")}
                break
        if legal_holiday is None and iso in hol.get("workdays_on_weekend", []):
            legal_holiday = {"name": "调休补班日", "source": hol.get("source")}

    degraded = False
    reason = None
    if terms is None:
        degraded = True
        reason = f"{year} 年节气数据未内置，已跳过节气主题"
    elif not festivals:
        reason = f"{year} 年传统节日数据未内置，已跳过节日主题"

    return {
        "date": iso,
        "weekday": WEEKDAY_CN[target.weekday()],
        "simulated": simulated,
        "solar_term": solar_term,
        "festival": festival,
        "legal_holiday": legal_holiday,
        "degraded": degraded,
        "degraded_reason": reason,
    }


def nearest_solar_term(target: Date, calendar: dict | None = None):
    """返回当前所处的节气区间（上一个已过节气 → 下一个节气）。"""
    if calendar is None:
        calendar = load_calendar()
    terms = calendar.get("solar_terms", {}).get(str(target.year))
    if not terms:
        return None
    ordered = []
    for name in SOLAR_TERM_ORDER:
        info = terms.get(name)
        if info and info.get("date"):
            ordered.append((name, datetime.strptime(info["date"], "%Y-%m-%d").date()))
    if not ordered:
        return None
    # 必须按公历日期升序排列：传统顺序（立春→大寒）里小寒、大寒在 1 月却排在末尾，
    # 直接遍历会让「上一个节气」被年初的节气错误覆盖。
    ordered.sort(key=lambda pair: pair[1])
    prev = None
    nxt = None
    for name, d in ordered:
        if d <= target:
            prev = (name, d)
        elif nxt is None:
            nxt = (name, d)
    if prev is None:  # 年初：取上一年最后一个节气
        py = str(target.year - 1)
        pterms = calendar.get("solar_terms", {}).get(py) or {}
        for name in reversed(SOLAR_TERM_ORDER):
            info = pterms.get(name)
            if info and info.get("date"):
                prev = (name, datetime.strptime(info["date"], "%Y-%m-%d").date())
                break
    return {
        "current": prev[0] if prev else None,
        "current_date": prev[1].isoformat() if prev else None,
        "next": nxt[0] if nxt else None,
        "next_date": nxt[1].isoformat() if nxt else None,
    }


# ===========================================================================
# [2] theme_rules —— 当日主题与「今日宜」娱乐彩蛋
# ===========================================================================

# 四季主题（按节气归属月粗分，仅作文案灵感）
SEASON_BY_TERM = {
    "立春": "春", "雨水": "春", "惊蛰": "春", "春分": "春", "清明": "春", "谷雨": "春",
    "立夏": "夏", "小满": "夏", "芒种": "夏", "夏至": "夏", "小暑": "夏", "大暑": "夏",
    "立秋": "秋", "处暑": "秋", "白露": "秋", "秋分": "秋", "寒露": "秋", "霜降": "秋",
    "立冬": "冬", "小雪": "冬", "大雪": "冬", "冬至": "冬", "小寒": "冬", "大寒": "冬",
}

SEASON_THEMES = {
    "春": {"theme": "春日尝鲜", "tagline": "万物生发，宜尝一口新鲜。",
           "hint": ["新品", "清爽", "轻食"]},
    "夏": {"theme": "清爽一夏", "tagline": "暑气正盛，宜取清凉之物。",
           "hint": ["冷饮", "冰品", "清爽"]},
    "秋": {"theme": "秋日暖心", "tagline": "天凉气爽，宜一份温热御膳。",
           "hint": ["热饮", "暖食", "分享"]},
    "冬": {"theme": "暖冬传膳", "tagline": "寒意渐浓，宜热气腾腾地吃一顿。",
           "hint": ["热食", "热饮", "饱腹"]},
}

FESTIVAL_THEMES = {
    "春节":   {"theme": "新春纳福", "tagline": "岁首更始，宜好好犒赏自己。", "hint": ["分享", "聚餐"]},
    "元宵节": {"theme": "元宵团圆", "tagline": "月上柳梢，宜与亲友同享。", "hint": ["分享", "甜品"]},
    "除夕":   {"theme": "除夕守岁", "tagline": "一夜连双岁，宜从容用膳。", "hint": ["分享", "饱腹"]},
    "龙抬头": {"theme": "春龙抬头", "tagline": "春回大地，宜整顿精神再出发。", "hint": ["饱腹", "提神"]},
    "上巳节": {"theme": "上巳踏青", "tagline": "春水初生，宜出门走走再吃。", "hint": ["清爽", "便携"]},
    "清明":   {"theme": "清明尝春", "tagline": "气清景明，宜一份清淡御膳。", "hint": ["清爽", "轻食"]},
    "端午节": {"theme": "端午佳味", "tagline": "艾叶飘香，宜好好吃一顿。", "hint": ["饱腹", "分享"]},
    "七夕":   {"theme": "七夕小聚", "tagline": "星河迢迢，宜与人分食。", "hint": ["分享", "甜品"]},
    "中元节": {"theme": "中元寄思", "tagline": "秋意初起，宜静静用膳。", "hint": ["暖食"]},
    "中秋节": {"theme": "中秋团圆", "tagline": "月满中天，宜与亲友分享。", "hint": ["分享", "甜品"]},
    "重阳节": {"theme": "重阳敬老", "tagline": "秋高气爽，宜为长辈或自己安排一顿暖心餐。", "hint": ["暖食", "分享"]},
    "下元节": {"theme": "下元安养", "tagline": "冬意将至，宜温补暖身。", "hint": ["热食", "暖食"]},
    "冬至":   {"theme": "冬至团圆", "tagline": "一阳来复，宜与亲友分享一份热腾腾的御膳。", "hint": ["热食", "分享"]},
    "腊八节": {"theme": "腊八暖胃", "tagline": "腊鼓催春，宜来点暖的。", "hint": ["热食", "热饮"]},
    "小年":   {"theme": "小年辞旧", "tagline": "年味渐浓，宜提前犒赏自己。", "hint": ["分享", "甜品"]},
}

# ── 麦历 ────────────────────────────────────────────────────────────────
# 「麦历」是本 Skill 对「当日文化主题」的自造叫法，只做三件事：
#   观节气（二十四节气，天文算法算交节时刻）、记节日（传统农历节日）、定时令（四季默认主题）。
# 它**不是黄历**：不排宜忌、不测吉凶、不算八字、不看风水，
# 也**不代替陛下的判断**——推荐与否只取决于预算、口味与官方价格。
#
# 之所以不叫「黄历」：黄历自带"择吉避凶"的意味，拿来包装点餐推荐，
# 容易被读成"今天宜吃这个、不宜吃那个"的暗示，甚至像在用吉凶推着人花钱。
# 本 Skill 要的是文化氛围，不是决策权威——故改名「麦历」，并把三条边界写死。
MAI_CALENDAR_DISCLAIMER = (
    "以上「麦历」主题为**文化灵感与娱乐表达**："
    "① **不预测吉凶**——不排宜忌、不算运势、不判好坏；"
    "② **不影响消费决策**——今日吃什么只取决于陛下的预算、口味与官方价格，与节气无关；"
    "③ **不冒充官方促销**——非麦当劳官方活动，官方活动另见「礼部呈报」栏目。"
)

# 「今日宜」娱乐彩蛋：仅限饮食相关的轻量表达，不含任何吉凶、运势、财运断言
AUSPICIOUS_POOL = [
    "今日宜尝鲜", "今日宜犒赏自己", "今日宜与亲友分享",
    "今日宜探索新品", "今日宜精打细算", "今日宜慢慢吃一顿",
    "今日宜加一份小食", "今日宜换个口味",
]

BANNED_FORTUNE_WORDS = [
    "财运", "事业", "升官", "转运", "化解", "霉运", "吉凶", "黄道吉日",
    "招财", "辟邪", "旺运", "命理", "八字", "风水", "保佑",
]

COMPLIANCE_BANNED = [
    "全网最低", "绝对最低", "保证最低", "最低价保证",
    "治疗", "疗效", "保健", "药用", "养生功效", "包治",
]


def build_theme(date_ctx: dict, calendar: dict | None = None,
                opt_out: bool = False) -> dict:
    """根据日期上下文生成当日主题。主题只提供灵感，不承诺任何官方活动。

    opt_out=True：陛下明确表示不喜欢当前主题，降级为无主题的常态推荐，
    不再套用节气/节日文案，但保留免责声明。
    """
    festival = date_ctx.get("festival")
    solar_term = date_ctx.get("solar_term")

    if opt_out:
        seed = int(hashlib.md5((date_ctx["date"] + "#plain").encode("utf-8")).hexdigest(), 16)
        return {
            "theme": "四时常态",
            "tagline": "陛下不喜今日主题，臣按常态办理，只论需求与价格。",
            "menu_hint": [],
            "source": "用户关闭主题",
        "auspicious_fun": AUSPICIOUS_POOL[seed % len(AUSPICIOUS_POOL)],
        "disclaimer": (
            "已按陛下旨意关闭麦历主题。以下内容仅基于陛下需求与官方数据。"
        ),
            "opted_out": True,
            "degraded": False,
            "degraded_reason": None,
        }

    if festival and festival["name"] in FESTIVAL_THEMES:
        base = FESTIVAL_THEMES[festival["name"]]
        source = f"传统节日·{festival['name']}"
    elif solar_term and solar_term["name"] in FESTIVAL_THEMES:
        base = FESTIVAL_THEMES[solar_term["name"]]
        source = f"节气·{solar_term['name']}"
    else:
        if calendar is None:
            try:
                calendar = load_calendar()
            except DataUnavailable:
                calendar = {}
        term_name = None
        near = None
        try:
            near = nearest_solar_term(
                datetime.strptime(date_ctx["date"], "%Y-%m-%d").date(), calendar)
        except Exception:
            near = None
        term_name = (near or {}).get("current")
        season = SEASON_BY_TERM.get(term_name, "秋")
        base = SEASON_THEMES[season]
        source = f"节气区间·{term_name}" if term_name else "四季默认主题"

    # 娱乐彩蛋：按日期稳定散列，同一天结果一致，与吉凶无关
    seed = int(hashlib.md5(date_ctx["date"].encode("utf-8")).hexdigest(), 16)
    auspicious = AUSPICIOUS_POOL[seed % len(AUSPICIOUS_POOL)]

    return {
        "theme": base["theme"],
        "tagline": base["tagline"],
        "menu_hint": list(base["hint"]),
        "source": source,
        "auspicious_fun": auspicious,
        "disclaimer": MAI_CALENDAR_DISCLAIMER,
        "degraded": bool(date_ctx.get("degraded")),
        "degraded_reason": date_ctx.get("degraded_reason"),
    }


# ===========================================================================
# [3] preference_profile —— 用户偏好
# ===========================================================================

DEFAULT_PROFILE = {
    "explicit": {},    # 用户主动告知：budget_max / likes / dislikes / priority
    "inferred": {},    # 系统推测：仅作参考，必须标注
    # 能力上**支持**跨会话持久化（存档于用户目录，工作区之外）；
    # 此处描述的是「尚未存档」的默认状态，不可写成"本 Skill 不支持持久化"。
    "history_note": "陛下尚未存档偏好，当前仅本次会话内有效；陛下明示后即可跨会话存档。",
}


def merge_preference(profile: dict, user_input: dict) -> dict:
    """合并偏好。只把用户【明确说出】的内容放进 explicit。"""
    p = json.loads(json.dumps(profile or DEFAULT_PROFILE))
    p.setdefault("explicit", {})
    p.setdefault("inferred", {})

    for key in ("budget_max", "likes", "dislikes", "priority", "people_count"):
        if key in user_input and user_input[key] not in (None, [], ""):
            p["explicit"][key] = user_input[key]

    if user_input.get("clear"):
        for key in user_input["clear"]:
            p["explicit"].pop(key, None)
            p["inferred"].pop(key, None)
    if user_input.get("clear_all"):
        p["explicit"] = {}
        p["inferred"] = {}
    return p


# --- 偏好持久化 -----------------------------------------------------------
# 存放在用户目录（工作区之外），因此不会进入 Git 仓库、不会随作品公开。
# 只记录与点餐有关的偏好，不收集任何敏感个人信息。
def preference_path() -> str:
    base = os.environ.get("IMPERIAL_KITCHEN_HOME") or os.path.expanduser("~")
    return os.path.join(base, ".workbuddy", "user_data",
                        "jin-gong-men", "preferences.json")


def load_persisted_preference(path: str | None = None) -> dict | None:
    """读取已存档偏好。文件不存在或损坏时返回 None（降级为会话内）。"""
    target = path or preference_path()
    if not os.path.exists(target):
        return None
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "explicit" not in data:
        return None
    data.setdefault("inferred", {})
    data["persisted"] = True
    data["storage_path"] = target
    return data


def save_preference(profile: dict, path: str | None = None) -> dict:
    """存档偏好。写入失败时如实返回失败，不假装成功。"""
    target = path or preference_path()
    payload = {
        "explicit": profile.get("explicit") or {},
        "inferred": profile.get("inferred") or {},
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S %z"),
        "note": "仅记录与点餐有关的偏好；不含任何身份信息。",
    }
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        profile["persisted"] = True
        profile["storage_path"] = target
        profile["persist_error"] = None
    except OSError as exc:
        profile["persisted"] = False
        profile["persist_error"] = f"{type(exc).__name__}"
    return profile


def clear_persisted_preference(path: str | None = None) -> bool:
    target = path or preference_path()
    try:
        if os.path.exists(target):
            os.remove(target)
        return True
    except OSError:
        return False


def describe_preference(profile: dict) -> str:
    ex = profile.get("explicit") or {}
    inf = profile.get("inferred") or {}
    if not ex and not inf:
        return "陛下旧例：暂无记录。臣将按陛下本次旨意办理。"
    if profile.get("persisted"):
        scope = (f"陛下旧例（已存档，跨会话有效；存档处："
                 f"{profile.get('storage_path')}）")
    else:
        scope = "陛下旧例（本次会话内有效，未存档）"
    if profile.get("persist_error"):
        scope += f"（⚠️ 存档失败：{profile['persist_error']}，本次仅在会话内有效）"
    lines = [scope + "："]
    if ex.get("budget_max") is not None:
        lines.append(f"  · 预算上限：{ex['budget_max']} 元（陛下明示）")
    if ex.get("likes"):
        lines.append(f"  · 偏好：{'、'.join(ex['likes'])}（陛下明示）")
    if ex.get("dislikes"):
        lines.append(f"  · 忌口：{'、'.join(ex['dislikes'])}（陛下明示）")
    if ex.get("priority"):
        lines.append(f"  · 优先：{ex['priority']}（陛下明示）")
    for key, value in inf.items():
        lines.append(f"  · {key}：{value}（臣之推测，待陛下确认）")
    return "\n".join(lines)


# ===========================================================================
# [4] menu_matching —— 真实菜单 → 候选方案
# ===========================================================================

def _price_yuan(item: dict):
    """统一取价，单位元。取不到返回 None（绝不猜价）。

    兼容三种真实来源口径：
      - price_fen：以「分」为单位的整数（calculate-price 风格）
      - price / currentPrice：以「元」为单位的数值或字符串（query-meals 风格）
    """
    if item.get("price_fen") is not None:
        return round(float(item["price_fen"]) / 100.0, 2)
    for key in ("price", "currentPrice"):
        if item.get(key) is not None:
            try:
                return round(float(item[key]), 2)
            except (TypeError, ValueError):
                continue
    return None


def adapt_mcd_menu(raw: dict) -> dict:
    """把麦当劳 MCP query-meals 的真实返回适配成本引擎的 items 列表。

    真实结构：data.categories[].meals[].code + data.meals.{code}（含 name/currentPrice/...）
    适配失败或结构不符时返回空 items，由上层降级处理，绝不伪造餐品。
    """
    if not isinstance(raw, dict):
        return {"items": [], "adapt_error": "返回不是对象"}
    data = raw.get("data") if "data" in raw else raw
    if not isinstance(data, dict):
        return {"items": [], "adapt_error": "data 字段缺失或类型错误"}

    meals_map = data.get("meals") or {}
    categories = data.get("categories") or []
    if not meals_map:
        return {"items": [], "adapt_error": "meals 映射表为空"}

    items = []
    if categories:
        for cat in categories:
            cat_name = (cat.get("name") or "").replace("\n", "")
            for m in cat.get("meals") or []:
                code = m.get("code")
                detail = meals_map.get(code)
                if not detail:
                    continue
                items.append({
                    "code": code,
                    "productCode": code,
                    "name": detail.get("name"),
                    "price": detail.get("currentPrice"),
                    "originalPrice": detail.get("originalPrice"),
                    "category": cat_name,
                    "tags": m.get("tags") or [],
                    "desc": " ".join(m.get("tags") or []),
                    "discountType": detail.get("discountType"),
                    "image": detail.get("image"),
                })
    else:
        for code, detail in meals_map.items():
            items.append({
                "code": code,
                "productCode": code,
                "name": detail.get("name"),
                "price": detail.get("currentPrice"),
                "originalPrice": detail.get("originalPrice"),
                "category": None,
                "tags": [],
                "desc": None,
                "discountType": detail.get("discountType"),
                "image": detail.get("image"),
            })

    # 去重（同一餐品可出现在多个分类）
    seen, uniq = set(), []
    for it in items:
        if it["code"] in seen:
            continue
        seen.add(it["code"])
        uniq.append(it)
    return {"items": uniq, "adapt_error": None, "store_code": data.get("storeCode")}


def adapt_mcd_price(raw: dict) -> dict:
    """把麦当劳 MCP calculate-price 的真实返回适配成核价行。

    真实结构：data.price / data.discount / data.originalPrice（单位：分）
    返回 official_total_fen，交由 verify_price 统一核验。
    """
    if not isinstance(raw, dict):
        return None
    data = raw.get("data") if "data" in raw else raw
    if not isinstance(data, dict) or data.get("price") is None:
        return None
    names = [p.get("productName") for p in (data.get("productList") or [])]
    # 外送场景会多出配送费 / 打包费 / 餐具费，逐项照收，缺失则不补
    fees = {}
    for out_key, in_key in (("product", "productPrice"),
                            ("delivery", "deliveryPrice"),
                            ("packing", "packingPrice"),
                            ("tableware", "tablewarePrice")):
        if data.get(in_key) is not None:
            fees[out_key] = data[in_key]
    return {
        "name": " + ".join(filter(None, names)) or "官方核价组合",
        "official_total_fen": data.get("price"),
        "official_original_fen": data.get("originalPrice"),
        "official_discount_fen": data.get("discount"),
        "fees_fen": fees,
        "product_fen": data.get("productPrice"),
        "delivery_fen": data.get("deliveryPrice"),
        "packing_fen": data.get("packingPrice"),
        "product_list": data.get("productList") or [],
        "take_way_list": data.get("takeWayList") or [],
    }


# ===========================================================================
# [7] meal_photos —— 御膳图鉴（餐品图片 / 详情）
#
# ⚠️ 已实跑确认的重要事实：
#   query-meals（菜单列表）**不返回图片字段**，无论到店还是外送。
#   餐品图片只能由 query-meal-detail（餐品详情）的 data.image 取得。
#   因此「看图点餐」必须为每个候选餐品额外调一次详情接口，
#   且图片缺失时如实标注，绝不自行拼接 URL 或复用他品之图。
# ===========================================================================

MEAL_DETAIL_TOOL = "query-meal-detail"

# 图片展示上限：每多一张图就多一次真实接口调用，默认只取前 3 道
PHOTO_DEFAULT_LIMIT = 3


def adapt_mcd_meal_detail(raw: dict) -> dict:
    """适配 query-meal-detail 的真实返回。

    真实结构：data.code / data.name / data.image / data.rounds /
              data.supportModify / data.modification.items[].values[]
    图片是官方 CDN 地址（menu-img.mcd.cn），臣只原样引用，不加工、不代存。
    """
    if not isinstance(raw, dict):
        return {"ok": False, "code": None, "name": None, "image": None,
                "message": "餐品详情返回不是对象，臣无法解读。"}
    data = raw.get("data") if "data" in raw else raw
    if not isinstance(data, dict) or not data.get("name"):
        return {"ok": False, "code": None, "name": None, "image": None,
                "message": "官方未返回有效的餐品详情，臣不敢妄绘御膳图。"}

    # 默认搭配：取每轮 isDefault=1 的选项；某轮无默认项则如实留空
    default_combo = []
    for r in data.get("rounds") or []:
        picked = [c for c in (r.get("choices") or []) if c.get("isDefault") == 1]
        for c in picked:
            default_combo.append({
                "round": r.get("name") or f"第{r.get('id')}轮",
                "name": c.get("name"),
                "code": c.get("code"),
                "diff_price": c.get("diffPrice"),
                "support_modify": bool(c.get("supportModify")),
            })
        if not picked:
            default_combo.append({
                "round": r.get("name") or f"第{r.get('id')}轮",
                "name": None,
                "code": None,
                "diff_price": None,
                "support_modify": False,
            })

    # 特调项：官方要求「不要主动展开」，故默认只统计数量，内容按需再取。
    # 但 minValues>=1 的组是**必选**：不选就按官方默认生效（如可乐默认"标准冰"）。
    # 浏览时不展开是对的，下单前再不问，陛下拿到的就是默认口味——
    # 故此处把「必选组」连同其默认项一并摘出，供下单前逐条请陛下定夺。
    mod_groups = []
    for i, item in enumerate(((data.get("modification") or {}).get("items") or [])):
        vals = item.get("values") or []
        names = [v.get("name") for v in vals]
        defaults = [v.get("name") for v in vals
                    if (v.get("selectedQuantity") or 0) >= 1]
        mn = item.get("minValues")
        mx = item.get("maxValues")
        mod_groups.append({
            "key": f"mod{i}",
            "count": len(vals),
            "names": names,
            "default_names": defaults,
            "min_values": mn,
            "max_values": mx,
            "required": bool(mn is not None and mn >= 1),
            "label": "、".join(names) + (f"（{len(names)} 选 {mx}）" if mx else ""),
        })

    image = data.get("image")
    return {
        "ok": True,
        "code": data.get("code"),
        "name": data.get("name"),
        "image": image,
        "image_source": ("官方 query-meal-detail 返回（menu-img.mcd.cn）"
                         if image else None),
        "support_modify": bool(data.get("supportModify")),
        "rounds_count": len(data.get("rounds") or []),
        "default_combo": default_combo,
        "modification_groups": mod_groups,
        "modification_summary": (
            f"可特调 {len(mod_groups)} 组（官方要求不主动展开，"
            f"陛下回复「查看特调」臣再逐项呈上）" if mod_groups else "该膳品无可特调项"),
        "message": None if image else "官方未返回该膳品图片。",
    }


def _as_detail(detail) -> dict:
    """把入参统一成已适配的详情结构（兼容原始返回与已适配结果）。"""
    if not isinstance(detail, dict):
        return {}
    if "modification_groups" in detail or "default_combo" in detail:
        return detail
    return adapt_mcd_meal_detail(detail)


def required_mod_groups(detail) -> list:
    """取出「必须选一项」的特调组（官方 minValues>=1）。

    返回空列表 = 这道膳品没有必选口味，臣不必多问。
    """
    d = _as_detail(detail)
    return [g for g in (d.get("modification_groups") or []) if g.get("required")]


def build_pending_checklist(details: list) -> dict:
    """下单前的「待定清单」：哪几道还有选配轮次 / 必选口味没定。

    官方展示规则要求"不要主动展开特调"，那是**浏览时**不刷屏；
    但进入下单环节，默认值一旦落单就改不了，所以必须逐条问清楚。
    本函数只负责把"该问什么"列出来，问与不问由陛下定的流程决定。
    """
    rows = []
    for det in details or []:
        d = _as_detail(det)
        if not d.get("ok"):
            continue
        rounds = d.get("rounds_count") or 0
        req = required_mod_groups(d)
        if not rounds and not req:
            continue
        rows.append({
            "code": d.get("code"),
            "name": d.get("name"),
            "rounds_to_confirm": rounds,
            "default_combo": d.get("default_combo") or [],
            "required_mods": [
                {"key": g["key"], "label": g["label"],
                 "options": g["names"], "default": (g["default_names"] or [None])[0]}
                for g in req],
        })
    return {
        "ok": True,
        "rows": rows,
        "count": len(rows),
        "note": ("以上为官方详情中「有选配轮次」或「有必选口味」的膳品。"
                 "下单前须逐条请陛下定夺；未定夺者臣按官方默认搭配落单，"
                 "默认项已一并列出，陛下可回复「按官方默认」放行。"),
    }


def render_pending_checklist(checklist: dict) -> list:
    """渲染「待定清单」——古风口吻，逐条列出该问什么。"""
    L = []
    if not checklist.get("ok"):
        L.append(f"- ⚠️ {checklist.get('message') or '臣未能取得官方详情，不敢列单。'}")
        return L
    if not checklist.get("rows"):
        L.append("- 所点膳品均为单品且无必选口味，臣不必再多问。")
        return L
    for i, r in enumerate(checklist["rows"], 1):
        L.append(f"- **{i}. {r['name']}**（编码 {r['code']}）")
        if r["rounds_to_confirm"]:
            L.append(f"  - 选配轮次 {r['rounds_to_confirm']} 轮，须逐轮定夺。")
            for c in r["default_combo"]:
                L.append(f"    - {c['round']} → "
                         f"{c['name'] or '⚠️ 官方未给默认项，须陛下指定'}")
        for g in r["required_mods"]:
            L.append(f"  - 必选口味（{g['key']}）：{g['label']}"
                     + (f"，官方默认「{g['default']}」" if g.get("default") else ""))
    L.append(f"- {checklist['note']}")
    return L


def attach_photos(candidates: dict, details: list) -> dict:
    """把详情接口的图片按 code 回写到候选方案上。

    只回填官方真实返回的图片；未取得详情的餐品保持 image=None，不复用他品之图。
    """
    if not candidates:
        return candidates
    by_code = {}
    for d in details or []:
        d = d if isinstance(d, dict) else {}
        code = d.get("code")
        if code and d.get("image"):
            by_code[str(code)] = d
    out = json.loads(json.dumps(candidates)) if isinstance(candidates, dict) else {}
    for c in out.get("candidates", []):
        hit = by_code.get(str(c.get("code")))
        if hit:
            c["image"] = hit["image"]
            c["image_source"] = hit.get("image_source")
            c["default_combo"] = hit.get("default_combo") or []
            c["support_modify"] = hit.get("support_modify")
        elif "image" not in c:
            c["image"] = None
            c["image_source"] = None
    if out.get("candidates"):
        got = sum(1 for c in out["candidates"] if c.get("image"))
        out["photos_note"] = (
            f"已为 {got}/{len(out['candidates'])} 道膳品取得官方图片"
            f"（来源：{MEAL_DETAIL_TOOL}）；未取得者不配图，不以他品之图充数。")
    return out


def render_photo_gallery(candidates: dict, limit: int = PHOTO_DEFAULT_LIMIT) -> list:
    """渲染「御膳图鉴」：让陛下先看见菜，再谈价。

    只渲染官方真实返回的图片链接；无图者如实写明，不假造。
    """
    L = []
    cands = (candidates or {}).get("candidates") or []
    if not cands:
        return ["- 官方未返回候选餐品，无图可呈。"]

    shown = [c for c in cands if c.get("image")][:max(1, limit)]
    missing = [c for c in cands if not c.get("image")]

    if not shown:
        L.append("- 臣未取得任何官方餐品图片"
                 "（`query-meals` 菜单列表不返回图片，须逐道调用 "
                 "`query-meal-detail`），故不配图，亦不以他品之图充数。")
        return L

    for i, c in enumerate(shown, 1):
        price_txt = f"{c['price']} 元" if c.get("price") is not None else "官方未返回价格"
        title = f"**{i}. {c.get('name')}**" + (
            "【可特调】" if c.get("support_modify") else "")
        L.append(f"### {title}　{price_txt}")
        L.append("")
        L.append(f"![{c.get('name')}]({c['image']})")
        L.append("")
        combo = [x for x in (c.get("default_combo") or []) if x.get("name")]
        if combo:
            L.append("- 官方默认搭配：" + "；".join(
                f"{x['round']}→{x['name']}"
                + (f"（{x['diff_price']}）" if x.get("diff_price") else "")
                for x in combo))
        L.append(f"- 图片来源：{c.get('image_source') or '官方返回'}")

    if missing:
        names = "、".join(m["name"] for m in missing[:5])
        L.append(f"- ⚠️ 以下 {len(missing)} 道官方未返回图片，臣不配图：{names}")
    L.append("- ⚠️ 图片为麦当劳官方 CDN 原图，臣未作任何修改；"
             "菜品以实物为准，图片仅供参考。")
    return L


def render_meal_detail_card(detail: dict, show_modification: bool = False) -> list:
    """渲染单道膳品的详情卡（供陛下说「查看某道膳品详情」时使用）。"""
    L = []
    if not detail or not detail.get("ok"):
        return [f"- ⚠️ {((detail or {}).get('message') or '官方未返回该膳品详情。')}"]

    name = detail.get("name")
    L.append(f"### {name}" + ("【可特调】" if detail.get("support_modify") else ""))
    if detail.get("image"):
        L.append("")
        L.append(f"![{name}]({detail['image']})")
        L.append("")
        L.append(f"- 图片来源：{detail.get('image_source')}")
    else:
        L.append("- 官方未返回该膳品图片。")

    if detail.get("rounds_count"):
        L.append(f"- 选配轮次：{detail['rounds_count']} 轮")
        for x in detail.get("default_combo", []):
            if x.get("name"):
                L.append(f"  - 默认：{x['round']} → {x['name']}"
                         + (f"（{x['diff_price']}）" if x.get("diff_price") else ""))
            else:
                L.append(f"  - {x['round']}：官方未返回默认选项")
    L.append(f"- 特调：{detail.get('modification_summary')}")
    if show_modification:
        for g in detail.get("modification_groups", []):
            if g.get("names"):
                L.append(f"  - 可选（{g['count']} 项，"
                         f"必选 {g.get('min_values')} / 至多 {g.get('max_values')}）："
                         + "、".join(g["names"]))
    return L


def _hit_any(text: str, keywords) -> bool:
    low = str(text or "").lower()
    for kw in keywords or []:
        if str(kw).lower() in low:
            return True
    return False


def build_candidates(menu: dict, request: dict, theme: dict | None = None) -> dict:
    """从真实菜单筛选候选方案。

    入参 menu 必须是 MCP query-meals 的真实返回（原样传入）。
    任何缺失字段一律标注 unknown，绝不补默认值。
    """
    items = (menu or {}).get("items") or (menu or {}).get("data", {}).get("items") or []
    if not items and ((menu or {}).get("categories")
                      or (menu or {}).get("data", {}).get("categories")
                      or (menu or {}).get("data", {}).get("meals")):
        items = adapt_mcd_menu(menu).get("items", [])
    if not items:
        return {
            "ok": False,
            "reason": "empty_menu",
            "message": "臣未能从官方数据中查得可售餐品，不敢妄拟御膳。",
            "candidates": [],
            "warnings": ["官方菜单返回为空，未生成任何候选方案"],
        }

    budget = request.get("budget_max")
    people = request.get("people_count") or 1
    likes = request.get("likes") or []
    dislikes = request.get("dislikes") or []
    wants = request.get("wants") or []
    priority = request.get("priority") or "综合"

    theme_hint = (theme or {}).get("menu_hint") or []
    normalized, unknown_price = [], []
    for raw in items:
        name = raw.get("name") or raw.get("productName")
        if not name:
            continue
        price = _price_yuan(raw)
        if price is None:
            unknown_price.append(name)
        normalized.append({
            "code": raw.get("code") or raw.get("productCode"),
            "name": name,
            "price": price,
            "category": raw.get("category") or raw.get("categoryName"),
            "desc": raw.get("desc") or raw.get("description"),
            "raw": raw,
        })

    scored = []
    for it in normalized:
        reasons = []
        score = 0.0
        if it["price"] is None:
            reasons.append("官方未返回价格，无法核算")
        else:
            if budget is not None:
                if it["price"] <= budget:
                    score += 40
                    reasons.append(f"符合预算（{it['price']} 元 ≤ {budget} 元）")
                else:
                    over = round(it["price"] - budget, 2)
                    score -= 25
                    reasons.append(f"超出预算 {over} 元")
        if likes and _hit_any(it["name"], likes):
            score += 25
            reasons.append("符合陛下明示偏好")
        if dislikes and _hit_any(it["name"], dislikes):
            score -= 60
            reasons.append("命中陛下忌口")
        if wants and _hit_any(it["name"], wants):
            score += 30
            reasons.append("符合陛下本次点名需求")
        if theme_hint and _hit_any(
            " ".join(filter(None, [it["name"], it.get("category") or "", it.get("desc") or ""])),
            theme_hint,
        ):
            score += 12
            reasons.append(f"与今日主题「{(theme or {}).get('theme')}」相合")
        if priority == "价格优先" and it["price"] is not None:
            score += max(0, 30 - it["price"] / 2)
        scored.append({"item": it, "score": round(score, 2), "reasons": reasons})

    usable = [s for s in scored if not (dislikes and _hit_any(s["item"]["name"], dislikes))]
    usable.sort(key=lambda s: (-s["score"], s["item"]["price"] is None,
                               s["item"]["price"] if s["item"]["price"] is not None else 0))
    top = usable[: max(1, min(6, request.get("candidate_limit", 6)))]

    warnings = []
    if unknown_price:
        warnings.append(f"以下餐品官方未返回价格，未纳入排序：{'、'.join(unknown_price[:5])}")
    if dislikes:
        removed = len(scored) - len(usable)
        if removed:
            warnings.append(f"已剔除 {removed} 项命中忌口的餐品")

    cheapest = None
    priced = [s for s in usable if s["item"]["price"] is not None]
    if priced:
        cheapest = min(priced, key=lambda s: s["item"]["price"])
    budget_feasible = budget is None or cheapest is not None and cheapest["item"]["price"] <= budget

    return {
        "ok": True,
        "candidates": [{
            "code": s["item"]["code"],
            "name": s["item"]["name"],
            "price": s["item"]["price"],
            "category": s["item"]["category"],
            "score": s["score"],
            "reasons": s["reasons"],
        } for s in top],
        "people_count": people,
        "budget_max": budget,
        "budget_feasible": budget_feasible,
        "cheapest": ({
            "name": cheapest["item"]["name"],
            "price": cheapest["item"]["price"],
        } if cheapest else None),
        "warnings": warnings,
        "note": "候选方案均来自官方返回数据；价格为官方标价，非最终成交价。",
    }


# ===========================================================================
# [5] coupon_optimizer —— 优惠候选筛选（本地粗筛）
# ===========================================================================

def adapt_mcd_available_coupons(raw) -> dict:
    """解析 available-coupons 的返回。

    ⚠️ 官方该工具返回的是**格式化文本**而非 JSON（已实跑确认），
    因此这里做文本解析；解析不出内容时如实返回 empty，绝不编造券名。

    重要边界：这里拿到的是「可领取」的券，官方明确说明它**不承诺可用于本单**；
    本单可用券只能来自 `query-store-coupons`。二者不得混为一谈。
    领取动作本身有副作用，本项目一律不代领。
    """
    if isinstance(raw, dict):
        text = raw.get("text") or raw.get("content") or ""
    else:
        text = str(raw or "")

    coupons, cur = [], None
    for line in text.splitlines():
        s = line.strip().rstrip("\\").strip()
        m = re.search(r"优惠券标题[：:]\s*(.+)", s)
        if m:
            if cur:
                coupons.append(cur)
            cur = {"title": m.group(1).strip(), "status": None}
            continue
        m = re.search(r"^状态[：:]\s*(.+)", s)
        if m and cur is not None:
            cur["status"] = m.group(1).strip()
    if cur:
        coupons.append(cur)

    if not coupons:
        return {"ok": True, "empty": True, "coupons": [],
                "message": "官方未返回当前可领取的券令。"}
    return {"ok": True, "empty": False, "coupons": coupons,
            "caveat": "以下为官方「可领取」券令，尚未领取，"
                      "且官方未承诺可用于本单；臣不代领。"}


def adapt_mcd_store_coupons(raw: dict) -> dict:
    """解析 `query-store-coupons` 的真实返回（本项目首个非空门店券数据）。

    真实结构：data[] = {title, couponId, couponCode, tradeDateTime,
                        products[{productCode, productName}], promotionId}

    ⚠️ 三种券的语义必须分清，本项目绝不混用：
      - `available-coupons`  → **可领取**的券（尚未拥有）
      - `query-my-coupons`   → 卡包里的券（已拥有，但官方明确不校验门店/渠道）
      - `query-store-coupons`→ **本店 + 本场景可用**的券（唯一可用于本单的依据）
    券只能来自这里才算「本单可用」。
    """
    if not isinstance(raw, dict):
        return {"ok": False, "empty": True, "coupons": [],
                "message": "门店券返回不是对象，臣不敢据此断言有券。"}
    data = raw.get("data") if "data" in raw else raw
    if raw.get("success") is False:
        return {"ok": False, "empty": True, "coupons": [],
                "message": raw.get("message") or "门店券查询未成功。"}
    rows = data if isinstance(data, list) else (data or {}).get("coupons") or []
    if not rows:
        return {"ok": True, "empty": True, "coupons": [],
                "message": "本店本场景官方未返回可用券令（真实空结果，非查询失败）。"}

    coupons = []
    for r in rows:
        coupons.append({
            "title": r.get("title") or "（官方未返回券名）",
            "coupon_id": r.get("couponId"),
            "coupon_code": r.get("couponCode"),
            "validity": r.get("tradeDateTime"),
            "promotion_id": r.get("promotionId"),
            "products": [{"code": p.get("productCode"), "name": p.get("productName")}
                         for p in (r.get("products") or [])],
        })
    return {"ok": True, "empty": False, "coupons": coupons,
            "message": f"本店本场景官方返回 {len(coupons)} 张可用券令。",
            "note": "这是唯一能证明「本单可用」的依据；"
                    "可领券与卡包券均不承诺可用于本单。"}


def verify_coupon_price(with_coupon_raw: dict,
                        without_coupon_raw: dict | None = None) -> dict:
    """券效核验：用**两次真实官方核价**对比出这张券到底减了多少。

    臣不自己算差价——必须带券一次、不带券一次，都交给官方算，再比对。

    ⚠️ 实测异常（2026-10-22）：商品 1440 不带券时 `productPrice=0`、
       `productList` 为空（只剩配送费）。臣已用 901100 做对照实验排除接口故障，
       但官方未说明原因，故此处记为 `baseline_unavailable`，
       **不据此断言减免金额**。
    """
    def _pick(raw):
        if not isinstance(raw, dict):
            return None
        d = raw.get("data") if "data" in raw else raw
        return d if isinstance(d, dict) else None

    a = _pick(with_coupon_raw)
    if not a or a.get("price") is None:
        return {"ok": False, "message": "带券核价未取得官方结果，臣不敢妄称优惠。"}

    result = {
        "ok": True,
        "with_coupon_fen": a.get("price"),
        "with_coupon_discount_fen": a.get("discount"),
        "with_coupon_product_fen": a.get("productPrice"),
        "with_coupon_original_fen": a.get("originalPrice"),
        "official_discount_fen": a.get("discount"),
        "product_names": [p.get("productName") for p in (a.get("productList") or [])
                          if p.get("productName")],
        "baseline": None,
        "saving_fen": None,
        "message": None,
        "caveats": [],
    }

    b = _pick(without_coupon_raw) if without_coupon_raw else None
    if not b or b.get("price") is None:
        result["baseline"] = "not_queried"
        result["message"] = (
            "臣只做了带券核价。官方给出的优惠金额为 "
            f"{_yuan(a.get('discount') or 0)} 元"
            "（以官方 `discount` 字段为准）。")
        result["caveats"].append(
            "未做不带券的对照核价，故「减免金额」只有官方 discount 字段这一个依据。")
        return result

    # 对照基线不可用：商品不带券时官方核不出价（实测存在此情形）
    if not (b.get("productList") or []) or not b.get("productPrice"):
        result["baseline"] = "baseline_unavailable"
        result["message"] = (
            "⚠️ 不带券时官方对本商品的核价返回为空（商品价 0、商品列表为空），"
            "臣无法据此算出「省了多少」。"
            f"带券应付 {_yuan(a['price'])} 元"
            f"（官方 discount {_yuan(a.get('discount') or 0)} 元）。")
        result["caveats"].append(
            "臣已用另一商品做对照实验排除核价接口故障，"
            "但官方未说明该商品为何不带券时核不出价，臣不作断言。")
        return result

    result["baseline"] = "ok"
    result["without_coupon_fen"] = b.get("price")
    saving = b["price"] - a["price"]
    result["saving_fen"] = saving
    result["message"] = (
        f"同一组合官方两次核价：不带券 "
        f"{_yuan(b['price'])} 元 → 带券 "
        f"{_yuan(a['price'])} 元，"
        f"**实省 {_yuan(saving)} 元**。")
    result["caveats"].append(
        "减免额来自官方两次 `calculate-price` 的差额，臣未自行推算。")
    return result


def reconcile_claim_result(claimed: list | None, wallet: list | None) -> dict:
    """领券后对账：领了几张、卡包里实际几张，差异如实列出。

    ⚠️ 实测（2026-10-22）：`auto-bind-coupons` 回报「成功 3 张」，
       而 `query-my-coupons` 只查到 2 张。臣不假设领券接口一定对，
       也不假设卡包一定准——只把差异摆出来，请陛下自行核对官方 App。
    """
    claimed = [str(c).strip() for c in (claimed or []) if str(c).strip()]
    wallet = [str(w).strip() for w in (wallet or []) if str(w).strip()]
    if not claimed and not wallet:
        return {"ok": False, "message": "臣未取得领券结果与卡包数据，无从对账。"}

    missing = [c for c in claimed if c not in wallet]
    extra = [w for w in wallet if w not in claimed]
    return {
        "ok": True,
        "claimed_count": len(claimed),
        "wallet_count": len(wallet),
        "missing": missing,
        "extra": extra,
        "consistent": not missing and not extra,
        "message": (
            f"领券回报 {len(claimed)} 张，卡包实查 {len(wallet)} 张。"
            + ("数目一致。" if not missing and not extra
               else f"**不一致**：{len(missing)} 张未见于卡包"
                    + (f"，另有 {len(extra)} 张卡包中有而本次未报" if extra else "")
               + "。")),
        "caveats": [
            "卡包接口官方明确不校验门店/渠道，**在卡包里不等于本单可用**。",
            "差异可能来自同步延迟或券的分类归属，臣未核实具体原因，不作断言；"
            "请陛下以麦当劳官方 App 为准。",
        ],
    }


def build_coupon_claim_plan(available_coupons: dict, confirmed: bool = False) -> dict:
    """编排「代领券令」。

    已查证的官方约束（来自工具声明原文，非臣臆测）：
      - `auto-bind-coupons` **无需参数**，领取的是「当前可领的**全部**券」，
        **不支持指定单张**，也没有 couponId 入参。
      - 官方声明的触发场景正是「当用户说"帮我领券"时使用」。

    臣据此的设计（分级治理第二档）：
      1. 默认**不领**，只列券、把话说明白；
      2. 陛下明示后，臣先把「将要领取的全部券」逐张复述一遍再执行；
      3. 领完必须回查 `query-my-coupons` 确认入包；
      4. 入了包也**不等于本单可用**——仍须 `calculate-price` 核价才算数。

    ⚠️ 诚实标注：臣**未核实**领券是否消耗领取资格/次数，官方声明中未提及。
    """
    plan = {
        "tool": COUPON_CLAIM_TOOL,
        "tier": "confirm",
        "tier_note": "第二档写操作：复述并获陛下明示确认后，方可由调用方执行。",
        "status": None,
        "auto_call_allowed": False,
        "granularity": "all_or_nothing",
        "granularity_note": (
            "官方该工具**只能一键领取当前可领的全部券**，无 couponId 入参，"
            "**不支持只领其中某一张**。陛下若只想领其中一张，臣做不到，"
            "需陛下自行在麦当劳官方渠道操作——臣不会假称可以挑选。"),
        "coupons": [],
        "confirm_prompt": None,
        "after_claim": [
            "query-my-coupons（回查卡包，确认券是否真的入包）",
            "calculate-price（验证本单能否使用、实际减免多少）",
        ],
        "caveats": [
            "领券**不等于**本单可用：券有门槛、范围与互斥规则，"
            "最终须以官方核价为准。",
            "臣未核实领券是否消耗领取资格或次数（官方声明中未提及），"
            "请陛下自行权衡。",
            "券有有效期，领取后不使用会过期；臣不代为决策该不该领。",
        ],
        "message": None,
    }

    if not available_coupons:
        plan["status"] = "blocked"
        plan["message"] = "臣尚未查得可领券令，无从代领。"
        return plan

    if not available_coupons.get("ok"):
        plan["status"] = "blocked"
        plan["message"] = (available_coupons.get("message")
                           or "可领券令查询未成功，臣不敢代领。")
        return plan

    coupons = available_coupons.get("coupons") or []
    if not coupons:
        plan["status"] = "nothing_to_claim"
        plan["message"] = "官方显示当前无可领券令，无需代领。"
        return plan

    plan["coupons"] = [{"title": c.get("title") or "（官方未返回券名）",
                        "status": c.get("status") or "未返回"} for c in coupons]
    plan["count"] = len(coupons)

    if not confirmed:
        plan["status"] = "need_confirm"
        listing = "\n".join(f"  {i}. {c['title']}（{c['status']}）"
                            for i, c in enumerate(plan["coupons"], 1))
        plan["confirm_prompt"] = (
            f"臣可代陛下领取当前可领的 **{len(coupons)} 张**券令：\n"
            f"{listing}\n"
            f"确认请回复「领」；臣收到明示后方会执行。")
        plan["message"] = "待陛下确认，臣未代领。"
        return plan

    plan["status"] = "ready"
    plan["message"] = (
        f"已获陛下明示，可由调用方执行 {COUPON_CLAIM_TOOL}，"
        f"领取当前可领的全部 {len(coupons)} 张券令。")
    return plan


def render_coupon_claim_section(plan: dict) -> list:
    """渲染「代领券令」段落：把限制、风险与后续步骤全部摊开。"""
    L = []
    status_text = {
        "need_confirm": "候陛下示下（臣未代领）",
        "ready": "已获明示，可执行",
        "nothing_to_claim": "无可领券令",
        "blocked": "暂不可代领",
    }
    L.append(f"- 代领状态：{status_text.get(plan.get('status'), '未知状态')}"
             f"（{plan.get('tier_note')}）")
    if plan.get("message"):
        L.append(f"- {plan['message']}")
    if plan.get("granularity_note"):
        L.append(f"- ⚠️ {plan['granularity_note']}")
    if plan.get("confirm_prompt"):
        for line in plan["confirm_prompt"].splitlines():
            L.append(f"- {line}" if not line.startswith("  ")
                     else f"  {line.strip()}")
    if plan.get("status") == "ready":
        L.append("- 领完之后臣会接着做两件事：")
        for step in plan.get("after_claim", []):
            L.append(f"  - {step}")
    for c in plan.get("caveats", []):
        L.append(f"- ⚠️ {c}")
    return L


def _combo_text(det: dict) -> list:
    """把官方默认搭配压成一句话，供臣复述「按官方默认」到底是什么。"""
    out = []
    for c in det.get("default_combo") or []:
        out.append(f"{c['round']} → {c['name'] or '官方未给默认项'}")
    return out


def build_order_plan(store: dict | None, items: list | None,
                     price: dict | None = None,
                     delivery: dict | None = None,
                     confirmed_steps: list | None = None,
                     item_details: list | None = None) -> dict:
    """编排「代下单」——第三档写操作，须三重复述全部点头。

    三个复述步骤（ORDER_CONFIRM_STEPS）：
      content  订单内容：门店 / 商品 / **选配** / **口味** / 数量 / 所用券令
      amount   金额明细：餐品 / 配送费 / 打包费 / 优惠 / **应付总额**
      delivery 交付方式：配送地址 或 取餐方式，并声明这是**待支付订单**

    item_details：各商品的 `query-meal-detail` 真实返回。有它，臣才知道
      这道膳品有几轮选配、有没有**必选口味**——
      套餐选配没定、必选口味没选，一律不许出单（否则陛下拿到的就是官方默认，
      例如可乐默认"标准冰"，去冰根本没问）。

    已查证的官方事实（见 WRITE_TIER_CONFIRM_STRICT 处注释）：
      `create-order` 创建的是**待支付订单**，支付须由陛下自行扫码或开 App 完成。
      ⇒ 臣可以配单、可以创建订单，但**绝不代付**——这一条没有任何例外。
    """
    plan = {
        "tool": ORDER_CREATE_TOOL,
        "tier": "confirm_strict",
        "tier_note": ("第三档写操作：订单内容 / 金额明细 / 交付方式"
                      "**三重复述全部确认后**，方可由调用方创建【待支付订单】。"),
        "status": None,
        "auto_call_allowed": False,
        "required_steps": list(ORDER_CONFIRM_STEPS),
        "confirmed_steps": [s for s in (confirmed_steps or [])
                            if s in ORDER_CONFIRM_STEPS],
        "recitals": {},
        "payment_note": ("臣创建的是**待支付订单**，支付须由陛下自行扫码"
                         "或打开麦当劳官方 APP 完成，**臣绝不代付**。"),
        "cancel_note": (f"若订单有误，可用官方 `{ORDER_CANCEL_TOOL}` 撤销，"
                        "或任其超时自动取消——撤单亦须陛下明示。"),
        "message": None,
        "blockers": [],
    }

    store = store or {}
    items = [i for i in (items or []) if (i or {}).get("product_code")]

    # ── 阻塞校验：缺了关键信息，臣连复述都无从复述 ──
    if not store.get("store_code"):
        plan["blockers"].append("未取得门店编码（storeCode），臣无从下单。")
    if not items:
        plan["blockers"].append("订单中没有任何商品，臣不创建空单。")
    if plan["blockers"]:
        plan["status"] = "blocked"
        plan["message"] = "下单信息不全，臣不敢妄拟御膳之单。"
        return plan

    # ── 第一复述：订单内容 ──
    content = [f"门店：**{store.get('name') or '（未返回店名）'}**"
               f"（storeCode {store.get('store_code')}"
               + (f"，beCode {store.get('be_code')}" if store.get("be_code") else "")
               + "）"]
    content.append(f"用餐方式：{store.get('scene_name') or '（未指定）'}"
                   f"（beType={store.get('be_type')}, orderType={store.get('order_type')}）")
    # 有官方详情时，臣才知道每道膳品该问什么
    detail_map = {}
    for det in item_details or []:
        d = _as_detail(det)
        if d.get("ok") and d.get("code"):
            detail_map[str(d["code"])] = d

    for i, it in enumerate(items, 1):
        name = it.get('name') or it.get('product_code')
        line = f"{i}. {name} × {it.get('quantity') or 1}"
        if it.get("coupon_title"):
            line += f"　用券：{it['coupon_title']}"
        content.append(line)

        det = detail_map.get(str(it.get("product_code")))
        if det is None:
            if it.get("modification_note"):
                content.append(f"  - 口味：{it['modification_note']}")
            continue

        # 选配轮次：套餐必须逐轮写清楚，不许只写「汉堡包」三个字
        rounds_given = [r for r in (it.get("rounds") or [])
                        if isinstance(r, dict) and (r.get("choice") or r.get("name"))]
        total_rounds = det.get("rounds_count") or 0
        if total_rounds:
            if rounds_given and len(rounds_given) < total_rounds:
                plan["blockers"].append(
                    f"「{name}」共 {total_rounds} 轮选配，臣只拿到 "
                    f"{len(rounds_given)} 轮，不敢替陛下补齐其余。")
            elif not rounds_given and not it.get("rounds_default_ok"):
                plan["blockers"].append(
                    f"「{name}」是套餐，{total_rounds} 轮选配尚未定夺"
                    f"（官方默认：{'；'.join(_combo_text(det))}）。"
                    "臣不敢拿默认搭配当圣旨——请陛下逐轮定夺，或明示「按官方默认」。")
            for r in rounds_given:
                content.append(f"  - {r.get('round') or '选配'}："
                               f"**{r.get('choice') or r.get('name')}**")
            if not rounds_given and it.get("rounds_default_ok"):
                content.append("  - 选配：**按官方默认**（"
                               + "；".join(_combo_text(det)) + "）")

        # 必选口味：不看就不问，落单即官方默认（可乐默认"标准冰"）
        chosen = {}
        for m in it.get("mods") or []:
            if isinstance(m, dict) and m.get("value"):
                chosen[m.get("group") or m.get("key")] = m["value"]
        for g in required_mod_groups(det):
            val = chosen.get(g["key"]) or chosen.get(g["label"])
            if val:
                content.append(f"  - {g['label']}：**{val}**")
            elif it.get("mods_default_ok"):
                content.append(f"  - {g['label']}：**按官方默认"
                               f"（{g['default_names'][0] if g['default_names'] else '未知'}）**")
            else:
                plan["blockers"].append(
                    f"「{name}」的必选口味尚未定夺：{g['label']}"
                    + (f"（官方默认「{g['default_names'][0]}」）"
                       if g.get("default_names") else "")
                    + "。臣不敢拿默认口味落单。")
        if it.get("modification_note"):
            content.append(f"  - 其他交代：{it['modification_note']}")
    plan["recitals"]["content"] = content

    # ── 第二复述：金额明细 ──
    amount = []
    pr = (price or {}).get("data") if isinstance(price, dict) else None
    pr = pr if isinstance(pr, dict) else (price if isinstance(price, dict) else {})
    fen = {k: pr.get(k) for k in ("productPrice", "deliveryPrice", "packingPrice",
                                  "tablewarePrice", "discount", "price")}
    labels = (("productPrice", "餐品小计"), ("deliveryPrice", "配送费"),
              ("packingPrice", "打包费"), ("tablewarePrice", "餐具费"),
              ("discount", "优惠减免"), ("price", "应付总额"))
    for key, label in labels:
        v = fen.get(key)
        if v is not None:
            amount.append(f"{label}：**{safe_money(v, UNIT_FEN)} 元**")
    if not amount:
        amount.append("⚠️ 臣尚未取得官方核价结果，不敢报出金额。"
                      "须先由 `calculate-price` 核价，方可进入下一步。")
        plan["blockers"].append("缺少官方核价结果，臣不敢在金额不明时创建订单。")
    plan["recitals"]["amount"] = amount
    # 应付总额（分）：供奏折卡片直接取用，省得再去字符串里抠数字
    plan["total_fen"] = fen.get("price")

    # ── 第三复述：交付方式 ──
    dl = delivery or {}
    dlv = []
    if dl.get("mode") == "delivery":
        dlv.append(f"麦乐送外送 → {dl.get('address') or '⚠️ 未指定配送地址'}")
        if not dl.get("address_id"):
            plan["blockers"].append("外送订单缺少 addressId，臣不敢下单到不明之处。")
    elif dl.get("mode") == "pickup":
        dlv.append(f"到店自取 → 取餐方式：{dl.get('take_way') or '⚠️ 未指定'}")
        if not dl.get("take_way_code"):
            plan["blockers"].append(
                "到店订单缺少 takeWayCode（须取自 `calculate-price` 的 takeWayList），"
                "臣不敢臆测取餐方式。")
    else:
        plan["blockers"].append("未指定交付方式（外送 or 到店自取），臣不敢擅断。")
        dlv.append("⚠️ 未指定")
    dlv.append("**这是待支付订单**——臣只拟单、不收钱，"
               "支付须由陛下自行完成（详见本节末支付边界）。")
    plan["recitals"]["delivery"] = dlv

    if plan["blockers"]:
        plan["status"] = "blocked"
        plan["message"] = "下单信息仍有缺失，臣不敢创建订单。"
        return plan

    pending = [s for s in ORDER_CONFIRM_STEPS if s not in plan["confirmed_steps"]]
    plan["pending_steps"] = pending
    if pending:
        plan["status"] = "need_confirm"
        plan["message"] = (
            f"还差 {len(pending)} 项复述未获陛下确认"
            f"（{'、'.join(pending)}）。臣未创建任何订单。")
    else:
        plan["status"] = "ready"
        plan["message"] = (
            "三重复述均已获陛下确认，可由调用方创建【待支付订单】。"
            "**支付仍须陛下自行完成。**")
    return plan


def render_order_section(plan: dict) -> list:
    """渲染「代下单」段落：三重复述逐条摊开，支付边界写死。"""
    L = []
    status_text = {
        "need_confirm": "候陛下逐项确认（臣未创建任何订单）",
        "ready": "三重复述已毕，可创建待支付订单",
        "blocked": "信息不全，臣不敢下单",
    }
    L.append(f"- 下单状态：{status_text.get(plan.get('status'), '未知状态')}")
    L.append(f"- {plan.get('tier_note')}")
    if plan.get("message"):
        L.append(f"- {plan['message']}")
    for b in plan.get("blockers", []):
        L.append(f"- ⚠️ {b}")

    titles = {"content": "① 订单内容", "amount": "② 金额明细",
              "delivery": "③ 交付方式"}
    for step in ORDER_CONFIRM_STEPS:
        lines = (plan.get("recitals") or {}).get(step)
        if not lines:
            continue
        done = step in (plan.get("confirmed_steps") or [])
        L.append(f"- **{titles[step]}**"
                 + ("　✅ 陛下已确认" if done else "　⬜ 待确认"))
        for ln in lines:
            L.append(f"  - {ln}")

    L.append(f"- ⚠️ {plan.get('payment_note')}")
    L.append(f"- {plan.get('cancel_note')}")
    if plan.get("status") == "ready":
        L.append("- 臣创建订单后会回传支付链接，陛下自行扫码或开 App 支付；"
                 "臣不代付、不代查支付结果以外的任何操作。")
    return L


# ── 拟旨下单·奏折卡片 ──────────────────────────────────────────────────
# 这是一次性交付物：只在三重复述齐备、陛下点头那一刻生成一次 HTML，
# 之后陛下看的是浏览器渲染结果，对话不再为它付一个 token。
# 与奏折文本同源同据：卡片上的每一个数字都来自官方返回，不另起一套口径。
SCROLL_TITLE = "拟旨下单"
SCROLL_SEAL = "御膳"

# 卡片样式抽成常量：奏折卡片与拟旨下单卡片共用同一套视觉，避免两处走样
_SCROLL_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#F1EFE8;padding:32px 16px;font-family:"Songti SC","SimSun","Noto Serif CJK SC",serif;color:#2C2C2A}
.scroll{max-width:560px;margin:0 auto;background:#FBF6EC;border:1px solid rgba(163,45,45,.22);border-radius:4px;padding:32px 30px;position:relative}
.head{display:flex;gap:18px;align-items:flex-start}
.title-v{writing-mode:vertical-rl;font-size:19px;font-weight:700;letter-spacing:.34em;color:#A32D2D;line-height:1}
.rule{width:2px;background:rgba(163,45,45,.3);align-self:stretch;flex:0 0 auto;min-height:96px}
.head-body{flex:1 1 auto;min-width:0}
.sub{font-size:13px;color:#5F5E5A;line-height:1.7}
.sub b{font-weight:400;color:#A32D2D}
.seal{position:absolute;top:26px;right:26px;width:52px;height:52px;border:2px solid #A32D2D;border-radius:50%;color:#A32D2D;display:flex;align-items:center;justify-content:center;font-size:15px;letter-spacing:.06em;line-height:1.15;text-align:center;transform:rotate(-7deg);opacity:.9}
.sec{margin-top:22px;padding-top:18px;border-top:1px solid rgba(163,45,45,.16)}
.sec-title{font-size:14px;font-weight:700;display:flex;align-items:center;gap:8px}
.sec-title::before{content:"";width:6px;height:6px;background:#A32D2D;flex:0 0 auto}
.sec-body{margin-top:8px}
.sec-body li{list-style:none;font-size:13px;color:#444441;line-height:1.75;padding-left:14px;position:relative}
.sec-body li::before{content:"—";position:absolute;left:0;color:#B4B2A9}
.clause{font-size:11px;color:#888780;line-height:1.7;margin-top:8px;padding:8px 10px;background:rgba(163,45,45,.05);border-radius:3px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:10px}
.card{display:flex;gap:10px;align-items:center;background:#FDFAF3;border:1px solid rgba(163,45,45,.12);border-radius:3px;padding:10px}
.card-img{width:64px;height:64px;object-fit:cover;border-radius:3px;background:#F1EFE8;flex:0 0 auto}
.card-body{min-width:0}
.card-name{font-size:13px;font-weight:700;line-height:1.4}
.card-price{font-size:12px;color:#A32D2D;margin-top:2px}
.card-why{font-size:11px;color:#888780;margin-top:3px;line-height:1.5}
.dish{display:flex;gap:14px;align-items:center;margin-top:12px}
.dish-img{width:84px;height:84px;object-fit:cover;border-radius:3px;background:#F1EFE8;flex:0 0 auto}
.dish-body{min-width:0}
.dish-name{font-size:15px;font-weight:700}
.dish-price{font-size:13px;color:#5F5E5A;margin-top:3px}
.dish-mod{font-size:12px;color:#888780;margin-top:4px;line-height:1.6}
.recital{margin-top:14px}
.recital-head{display:flex;align-items:center;gap:8px}
.tick{width:13px;height:13px;flex:0 0 auto}
.recital-title{font-size:14px;font-weight:700}
.recital-state{font-size:12px;color:#888780;margin-left:auto}
.recital-body{list-style:none;margin-top:6px}
.recital-body li{font-size:13px;color:#444441;line-height:1.75;padding-left:14px;position:relative}
.recital-body li::before{content:"—";position:absolute;left:0;color:#B4B2A9}
.blockers{margin-top:18px;padding:12px 14px;background:#FCEBEB;border-radius:3px}
.blockers-head{font-size:13px;font-weight:700;color:#A32D2D}
.blockers ul{list-style:none;margin-top:6px}
.blockers li{font-size:13px;color:#791F1F;line-height:1.7}
.total{margin-top:20px;padding-top:16px;border-top:1px solid rgba(163,45,45,.16);display:flex;align-items:baseline;justify-content:space-between}
.total-label{font-size:13px;color:#5F5E5A}
.total-num{font-size:28px;font-weight:700}
.pick{margin-top:18px;padding-top:16px;border-top:1px solid rgba(163,45,45,.16)}
.pick-title{font-size:13px;color:#5F5E5A}
.pick-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.btn{font-family:inherit;font-size:12px;padding:7px 13px;border:1px solid rgba(163,45,45,.5);background:#FDFAF3;color:#A32D2D;border-radius:3px;cursor:pointer;line-height:1.3}
.btn:hover{background:#A32D2D;color:#FDFAF3}
.btn[data-done="1"]{border-color:#0F6E56;color:#0F6E56}
.pick-note{font-size:11px;color:#888780;margin-top:8px;line-height:1.6}
.seal-line{margin-top:10px;font-size:13px;color:#A32D2D;line-height:1.7}
.foot{margin-top:22px;padding-top:14px;border-top:1px solid rgba(163,45,45,.16);font-size:12px;color:#888780;line-height:1.8}
.muted{font-size:13px;color:#888780;margin-top:14px}
"""

# 陛下点选区：卡片上的按钮点击即复制对应回复，省得陛下再手打一遍。
# 真正的点选入口仍是对话里的选项卡片（点击直接生效，零打字）；
# 卡片按钮只是把话备好，陛下粘回对话即可。
_SCROLL_PICK_JS = """
<script>
document.querySelectorAll('.btn[data-say]').forEach(function(b){
  b.addEventListener('click',function(){
    var t=this.getAttribute('data-say');
    try{navigator.clipboard.writeText(t);}catch(e){
      var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);
      ta.select();document.execCommand('copy');document.body.removeChild(ta);}
    var old=this.textContent;this.textContent='已复制：'+t;
    this.setAttribute('data-done','1');
    var self=this;setTimeout(function(){self.textContent=old;self.removeAttribute('data-done');},1600);
  });
});
</script>"""



def _esc(s) -> str:
    """HTML 转义：餐品名等外来字符串一律先转义再入卡，避免破坏结构。"""
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


_SENSITIVE_PATTERNS = (
    (re.compile(r"MCD[A-Z0-9]{15,}"), "***券码已隐去***"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "***手机号已隐去***"),
    (re.compile(r"(?<!\d)\d{25,}(?!\d)"), "***地址 ID 已隐去***"),
)


def _desensitize(html: str) -> str:
    """卡片里不得落下券码、手机号、完整地址 ID——与仓库隐私守卫同一口径。"""
    for pat, repl in _SENSITIVE_PATTERNS:
        html = pat.sub(repl, html)
    return html


def render_order_scroll(plan: dict, theme: dict | None = None,
                        date_ctx: dict | None = None,
                        photos: list | None = None,
                        store: dict | None = None,
                        picks: tuple | list | None = None) -> str:
    """生成「拟旨下单」奏折卡片（自包含 HTML，无外部依赖）。

    只呈现已核价、已复述的内容；图片只引用官方 CDN 原地址，不下载不转存。
    """
    plan = plan or {}
    theme = theme or {}
    date_ctx = date_ctx or {}
    status = plan.get("status") or "unknown"
    recitals = plan.get("recitals") or {}
    confirmed = plan.get("confirmed_steps") or []

    # ── 抬头 ──
    st = date_ctx.get("solar_term") or {}
    sub = []
    sub.append(_esc(date_ctx.get("date") or "日期未明"))
    if date_ctx.get("weekday"):
        sub[-1] += " " + _esc(date_ctx["weekday"])
    if st.get("name"):
        sub.append(f"麦历·{_esc(st['name'])}")
    if theme.get("theme") and not theme.get("opted_out"):
        sub.append(_esc(theme["theme"]))
    if store and store.get("name"):
        sub.append(_esc(store["name"]))

    # ── 膳品（只有官方给了图才上图，无图不占位） ──
    photos = photos or []
    dish_rows = []
    for c in photos:
        if not isinstance(c, dict) or not c.get("image"):
            continue
        price_txt = (f"{safe_money(c['price'], UNIT_YUAN)} 元"
                     if c.get("price") is not None else "官方未返回价格")
        mods = []
        for m in c.get("mods") or []:
            if isinstance(m, dict) and m.get("value"):
                mods.append(f"{_esc(m.get('group') or '交代')}·{_esc(m['value'])}")
        for x in (c.get("default_combo") or []):
            if x.get("name"):
                mods.append(f"{_esc(x.get('round') or '搭配')}·{_esc(x['name'])}")
        dish_rows.append(
            f'<div class="dish">'
            f'<img class="dish-img" src="{_esc(c["image"])}" alt="{_esc(c.get("name"))}">'
            f'<div class="dish-body">'
            f'<div class="dish-name">{_esc(c.get("name"))}</div>'
            f'<div class="dish-price">{price_txt}</div>'
            + (f'<div class="dish-mod">{"；".join(mods)}</div>' if mods else "")
            + f'</div></div>')
    if photos and not dish_rows:
        dish_rows.append('<p class="muted">官方未返回餐品图片，臣不配图，'
                         '亦不以他品之图充数。</p>')

    # ── 三重复述 ──
    titles = {"content": "订单内容", "amount": "金额明细",
              "delivery": "交付方式"}
    recital_html = []
    for i, step in enumerate(ORDER_CONFIRM_STEPS, 1):
        lines = recitals.get(step) or []
        if not lines:
            continue
        done = step in confirmed
        mark = ('<svg class="tick" viewBox="0 0 13 13" aria-hidden="true">'
                '<circle cx="6.5" cy="6.5" r="6.5" fill="%s"/>'
                '<path d="M3.5 6.8 L5.4 8.7 L9.5 4.3" stroke="%s" stroke-width="1.4" '
                'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
                % ("#E1F5EE" if done else "#F1EFE8",
                   "#0F6E56" if done else "#888780"))
        body = "".join(
            f'<li>{_esc(ln).replace("**", "")}</li>' for ln in lines)
        recital_html.append(
            f'<div class="recital"><div class="recital-head">{mark}'
            f'<span class="recital-title">{i}. {titles[step]}</span>'
            f'<span class="recital-state">'
            f'{"已确认" if done else "待陛下确认"}</span></div>'
            f'<ul class="recital-body">{body}</ul></div>')

    # ── 阻塞项 ──
    blockers = plan.get("blockers") or []
    blocker_html = "".join(f"<li>{_esc(b)}</li>" for b in blockers)
    if blockers:
        blocker_html = (f'<div class="blockers"><div class="blockers-head">'
                        f'臣不敢落单，尚缺：</div><ul>{blocker_html}</ul></div>')

    # ── 总额 ──
    total = plan.get("total_fen")
    total_html = ""
    if total is not None:
        total_html = (f'<div class="total"><span class="total-label">应付</span>'
                      f'<span class="total-num">¥{safe_money(total, UNIT_FEN)}</span></div>')
    elif not blockers:
        total_html = ('<div class="total"><span class="total-label">'
                      '臣尚未取得官方核价，不敢报数</span></div>')

    status_html = ""
    if status == "ready":
        status_html = ('<p class="seal-line">三重复述已毕，可创建【待支付订单】。'
                       '</p>')
    elif status == "need_confirm":
        status_html = ('<p class="seal-line">臣未创建任何订单，'
                       '静候陛下逐项点头。</p>')

    # 御前请旨：选项跟着状态走，陛下点即可，不必打字
    if picks is None:
        if status == "ready":
            picks = ("确认，就按这个下单", "再改改", "算了，不下单")
        elif status == "need_confirm":
            pending = plan.get("pending_steps") or []
            step_word = {"content": "订单内容无误", "amount": "金额明细无误",
                         "delivery": "交付方式无误"}
            picks = tuple(step_word[s] for s in pending if s in step_word) \
                or ("订单内容无误", "金额明细无误", "交付方式无误")
        else:
            picks = ("补齐所缺信息", "换个门店", "算了，不下单")
    picks = tuple(picks)
    pick_html = (
        f'<div class="pick"><div class="pick-title">御前请旨'
        f'（点击即复制，粘回对话即可；对话下方的选项卡片点了直接生效）</div>'
        f'<div class="pick-row">'
        + "".join(f'<button class="btn" data-say="{_esc(p)}">{_esc(p)}</button>'
                  for p in picks)
        + '</div></div>')

    return _desensitize(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{SCROLL_TITLE} · 御膳房奏折</title>
<style>{_SCROLL_CSS}</style></head><body>
<div class="scroll">
<div class="seal">{SCROLL_SEAL}</div>
<div class="head">
<div class="title-v">{SCROLL_TITLE}</div>
<div class="rule"></div>
<div class="head-body"><p class="sub">{"　·　".join(sub)}</p></div>
</div>
{"".join(dish_rows)}
{blocker_html}
{"".join(recital_html)}
{total_html}
{status_html}
{pick_html}
<div class="foot">臣创建的是待支付订单，支付须由陛下自行扫码或开 App 完成——<b style="color:#A32D2D;font-weight:400">臣绝不代付、不代收款。</b><br>餐品、价格、图片均取自麦当劳官方返回（图片为官方 CDN 原址，臣未作加工）；麦历主题仅为文化灵感，不预测吉凶、不影响消费决策、不冒充官方促销。</div>
</div>{_SCROLL_PICK_JS}</body></html>""")


SCROLL_MEMORIAL_TITLE = "御膳奏折"

# 御前请旨：默认给陛下的点选项（卡片按钮点击即复制，对话里另有真选项卡片）
DEFAULT_PICKS = ("就按这个下单", "换个更省的", "换个新品", "调整预算")


def render_memorial_scroll(date_ctx: dict, theme: dict, candidates: dict,
                           coupons: dict | None = None,
                           price: dict | None = None,
                           campaigns: list | None = None,
                           delivery: dict | None = None,
                           store: dict | None = None,
                           order_plan: dict | None = None,
                           picks: tuple | list | None = None) -> str:
    """渲染整篇「御膳奏折」卡片（自包含 HTML，与拟旨下单卡片同一套视觉）。

    与 Markdown 奏折同源同据：卡片上的每个数字、每张图都来自官方返回，
    未取得者如实留白，绝不编造。
    """
    date_ctx = date_ctx or {}
    theme = theme or {}
    candidates = candidates or {}
    coupons = coupons or {}
    price = price or {}
    order_plan = order_plan or {}

    # ── 抬头 ──
    st = date_ctx.get("solar_term") or {}
    sub = [f"{_esc(date_ctx.get('date') or '日期未明')}"
           + (f" {_esc(date_ctx['weekday'])}" if date_ctx.get("weekday") else "")]
    if date_ctx.get("simulated"):
        sub[0] += "（指定日期模拟）"
    if st.get("name"):
        sub.append(f"麦历·{_esc(st['name'])}")
    if theme.get("theme") and not theme.get("opted_out"):
        sub.append(_esc(theme["theme"]))
    if store and store.get("name"):
        sub.append(_esc(store["name"]))

    # ── 一、麦历 ──
    mai = []
    if theme.get("opted_out"):
        mai.append("麦历主题已按陛下旨意关闭。")
    else:
        if st.get("name"):
            mai.append(f"节气：{_esc(st['name'])}"
                       + (f"（交节 {_esc(st.get('moment_cst'))}）"
                          if st.get("moment_cst") else ""))
        fest = date_ctx.get("festival")
        if fest:
            mai.append(f"节日：{_esc(fest.get('name'))}")
        if theme.get("theme"):
            mai.append(f"今日主题：**{_esc(theme['theme'])}**"
                       + (f" —— {_esc(theme['tagline'])}"
                          if theme.get("tagline") else ""))
        if theme.get("auspicious_fun"):
            mai.append(f"今日宜（娱乐彩蛋）：{_esc(theme['auspicious_fun'])}")
    secs = [("麦历呈报（观象授时·文化灵感）", mai,
             theme.get("disclaimer") if not theme.get("opted_out") else None)]

    # ── 二、御膳图鉴（只有官方给了图才上图） ──
    cands = candidates.get("candidates") or []
    gallery = None
    cards = []
    for c in cands[:6]:
        img = c.get("image")
        price_txt = ("¥" + safe_money(c['price'], UNIT_YUAN)
                     if c.get("price") is not None else "官方未返回价格")
        why = "；".join(_esc(r) for r in (c.get("reasons") or [])[:2])
        cards.append(
            f'<div class="card">'
            + (f'<img class="card-img" src="{_esc(img)}" alt="{_esc(c.get("name"))}">'
               if img else
               '<div class="card-img" style="display:flex;align-items:center;'
               'justify-content:center;font-size:11px;color:#888780">无官方图</div>')
            + f'<div class="card-body"><div class="card-name">{_esc(c.get("name"))}</div>'
            f'<div class="card-price">{price_txt}</div>'
            + (f'<div class="card-why">{why}</div>' if why else "")
            + '</div></div>')
    if cands:
        got = sum(1 for c in cands if c.get("image"))
        note = (candidates.get("photos_note")
                or f"官方图片 {got}/{len(cands)} 道；未取得者不配图，不以他品之图充数。")
        gallery = (("".join(cards) and f'<div class="grid">{"".join(cards)}</div>')
                   + f'<p class="muted">{_esc(note)}</p>')
        secs.append(("御膳图鉴（官方 CDN 原图）", None, None))
    elif candidates.get("ok") is False:
        secs.append(("御膳图鉴（官方 CDN 原图）",
                     [candidates.get("message") or "臣未取得官方餐品数据。"], None))

    # ── 三、礼部呈报（官方活动，与麦历分栏） ──
    if campaigns:
        items = []
        for c in campaigns[:5]:
            if isinstance(c, dict):
                items.append(_esc(c.get("title") or c.get("name") or ""))
        secs.append(("礼部呈报（麦当劳官方活动，非臣杜撰）", items,
                     "以上来自官方活动日历，与麦历节气主题无关。"))

    # ── 四、户部精算（券） ──
    cpn = []
    if coupons.get("ok") is False:
        cpn.append(coupons.get("message") or "券令查询失败。")
    else:
        lst = coupons.get("coupons") or []
        if lst:
            for c in lst[:5]:
                nm = c.get("title") or c.get("name") or "券令"
                cpn.append(f"{_esc(nm)}"
                           + (f"（{_esc(c.get('desc') or c.get('description'))}）"
                              if c.get("desc") or c.get("description") else ""))
        else:
            cpn.append(coupons.get("message") or "本次未查得可用券令。")
    secs.append(("户部精算", cpn, None))

    # ── 五、御膳账目（官方核价） ──
    pr = price.get("data") if isinstance(price.get("data"), dict) else price
    labels = (("productPrice", "餐品小计"), ("deliveryPrice", "配送费"),
              ("packingPrice", "打包费"), ("tablewarePrice", "餐具费"),
              ("discount", "优惠减免"), ("price", "应付总额"))
    acc = []
    for k, lb in labels:
        v = pr.get(k)
        if v is not None:
            acc.append(f"{lb}：¥{safe_money(v, UNIT_FEN)}")
    if not acc:
        acc.append("臣尚未取得官方核价，不敢报数。")
    secs.append(("御膳账目（官方核价）", acc,
                 "金额单位为分，已按官方返回值换算；未经核价者不作推荐依据。"))

    # ── 六、交付方式 ──
    if delivery:
        dl = []
        mode = delivery.get("mode")
        if mode == "delivery":
            dl.append(f"麦乐送外送 → {_esc(delivery.get('address') or '⚠️ 未指定地址')}")
        elif mode == "pickup":
            dl.append(f"到店自取 → {_esc(delivery.get('take_way') or '⚠️ 未指定取餐方式')}")
        if delivery.get("status") and delivery.get("status") != "ready":
            dl.append(f"链路状态：{_esc(delivery.get('message') or delivery['status'])}")
        secs.append(("驿站传膳（交付方式）", dl, None))

    # ── 拼装章节 ──
    body = []
    for title, lines, note in secs:
        if lines is None and note is None and title.startswith("御膳图鉴"):
            body.append(f'<div class="sec"><div class="sec-title">{_esc(title)}</div>'
                        + (gallery or "") + '</div>')
            continue
        li = "".join(f"<li>{_esc(x).replace('**','')}</li>" for x in (lines or []))
        body.append(
            f'<div class="sec"><div class="sec-title">{_esc(title)}</div>'
            + (f'<ul class="sec-body">{li}</ul>' if li else "")
            + (f'<div class="clause">{_esc(note)}</div>' if note else "")
            + "</div>")

    # ── 七、拟旨下单（三重复述） ──
    if order_plan.get("recitals"):
        titles = {"content": "订单内容", "amount": "金额明细",
                  "delivery": "交付方式"}
        confirmed = order_plan.get("confirmed_steps") or []
        rec = []
        for i, step in enumerate(ORDER_CONFIRM_STEPS, 1):
            lines = order_plan["recitals"].get(step) or []
            if not lines:
                continue
            done = step in confirmed
            li = "".join(f"<li>{_esc(ln).replace('**','')}</li>" for ln in lines)
            rec.append(
                f'<div class="recital"><div class="recital-head">'
                f'<span class="recital-title">{i}. {titles[step]}</span>'
                f'<span class="recital-state">'
                f'{"已确认" if done else "待陛下确认"}</span></div>'
                f'<ul class="recital-body">{li}</ul></div>')
        if rec:
            body.append('<div class="sec"><div class="sec-title">拟旨下单</div>'
                        + "".join(rec) + "</div>")
        if order_plan.get("blockers"):
            bl = "".join(f"<li>{_esc(b)}</li>"
                         for b in order_plan["blockers"])
            body.append(f'<div class="blockers"><div class="blockers-head">'
                        f'臣不敢落单，尚缺：</div><ul>{bl}</ul></div>')
        if order_plan.get("total_fen") is not None:
            body.append(
                f'<div class="total"><span class="total-label">应付</span>'
                f'<span class="total-num">¥{_yuan(order_plan["total_fen"])}</span></div>')

    # ── 御前请旨（点击即复制；对话里另有真选项卡片） ──
    picks = tuple(picks or DEFAULT_PICKS)
    btns = "".join(
        f'<button class="btn" data-say="{_esc(p)}">{_esc(p)}</button>'
        for p in picks)
    body.append(
        f'<div class="pick"><div class="pick-title">御前请旨'
        f'（点击即复制，粘回对话即可；对话下方的选项卡片点了直接生效）</div>'
        f'<div class="pick-row">{btns}</div>'
        f'<div class="pick-note">臣不会自动下单、自动付款。'
        f'以上均为已查询、已核价、已推荐，未下单、未付款。</div></div>')

    return _desensitize(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{SCROLL_MEMORIAL_TITLE} · 御膳房</title>
<style>{_SCROLL_CSS}</style></head><body>
<div class="scroll">
<div class="seal">{SCROLL_SEAL}</div>
<div class="head">
<div class="title-v">{SCROLL_MEMORIAL_TITLE}</div>
<div class="rule"></div>
<div class="head-body"><p class="sub">{"　·　".join(sub)}</p></div>
</div>
{"".join(body)}
<div class="foot">餐品、价格、图片均取自麦当劳官方返回（图片为官方 CDN 原址，臣未作加工）；
麦历主题仅为文化灵感，不预测吉凶、不影响消费决策、不冒充官方促销。
请陛下自行前往麦当劳官方点餐渠道完成购买——<b style="color:#A32D2D;font-weight:400">臣绝不代付、不代收款。</b></div>
</div>{_SCROLL_PICK_JS}</body></html>""")


# ── 陛下点选（不给开放式填空）────────────────────────────────────────
# 陛下实测反馈：收到奏折后还得自己打字。根因是臣只在结尾丢一句"陛下可回复：
# A／B／C"——那仍是让陛下打字。故改为由引擎直接产出**结构化选项**，
# 调用方照此呈成选项卡片，陛下点一下即可，零打字。
PICK_QUESTION = {
    "opening": "陛下万安，御膳房已候旨。今日想用何膳？",
    "scene": "敢问陛下今日如何传膳？",
    "budget": "敢问陛下今日用度几何？",
    "people_budget": "敢问陛下今日用度几何、几位用膳？",
    "delivery_plan": "敢问陛下今日如何传膳、膳送至何处？",
    "after_memorial": "奏折已呈，陛下意下如何？",
    "order_confirm": "三重复述已毕，请陛下逐项点头：",
    "ice": "敢问陛下要几分冰？",
    "coupon": "券令当前可领，臣是否代领？",
    "address": "敢问膳送至何处？",
    "store_area": "敢问陛下要在哪一带取膳？",
}

# 开场一次呈完三问（陛下钦定，2026-10-22）：
# 起因是"一个个问题追问，效率太低"。三问一卡，陛下点完即可开拟，不必再等第二轮。
OPENING_BUNDLE_HEADERS = {
    "opening": "今日何膳",
    "people_budget": "用度人数",
    "delivery_plan": "传膳与送处",
}

# 陛下上朝的头一问：四项，前两项固定且不可换序（陛下钦定，臣不得增删挪位）
OPENING_REQUIRED = ("按预算拟单", "今日推荐")
OPENING_GREETING = (
    "陛下万安，御膳房已候旨。今日想用何膳？"
    "臣可按预算、口味、人数与当日时令，为您拟定御膳方案。"
)

# 选项卡片怎么呈——写进返回里，免得调用方把选项当文字念出去。
# （真实教训：SKILL.md 第一步只说「四项全部可点」，却没说用哪个工具呈，
#   机制只写在 references/voice.md 里，而 voice.md 的读取时机又把开场漏掉了，
#   于是严格按主文件执行恰好读不到机制，退化成「陛下可回复：A／B／C」。）
PICK_RENDER_TOOL = "AskUserQuestion"
PICK_RENDER_NOTE = (
    "把本对象里的 question / multiSelect / options **原样**填进提问工具"
    "（WorkBuddy 里是 AskUserQuestion，其它宿主用它的等价提问工具）；"
    "不得改写成文字让陛下打字。"
)
PICK_FALLBACK_NOTE = (
    "命令行末尾那段编号文字只是「没有选项卡片时」的降级兜底，"
    "**不得**直接粘给陛下——正常路径一律走提问工具呈卡片。"
)
PICK_RENDER_BANNER = (
    f"⚠️ 以下编号文字**不是**给陛下的回话——它是「宿主没有选项卡片」时的降级兜底。\n"
    f"正常路径：把上面 JSON 的选项结构（`questions` 整组，或单问的 "
    f"question / multiSelect / options）原样填进{PICK_RENDER_TOOL}"
    f"（其它宿主用等价的提问工具）呈卡片。"
)


def render_opening() -> dict:
    """陛下唤起本技能时的开场：一句问候 + 四个可点选项。

    前两项恒为「按预算拟单」「今日推荐」，顺序不得变；其余两项可随版本增补，
    但总数恒为四项，且**全部可点**，不出现需要陛下打字的项。
    """
    picks = suggest_picks("opening")
    return {
        "greeting": OPENING_GREETING,
        "question": picks["question"],
        "multiSelect": False,
        "options": picks["options"],
        "required_options": list(OPENING_REQUIRED),
        "render_via": PICK_RENDER_TOOL,
        "render_note": PICK_RENDER_NOTE,
        "fallback_note": PICK_FALLBACK_NOTE,
        "note": ("前两项为陛下钦定的固定项，臣不得增删挪位；"
                 "四项皆可点选，不必打字。"),
    }


def _with_render_hint(picks: dict) -> dict:
    """给结构化选项补上「怎么呈」的说明。

    为什么必须写进返回里而不是只写在文档里：曾经只写在 `references/voice.md`，
    而 SKILL.md 第一步又注明「不用额外读」——结果严格照主文件执行的调用方
    在最需要机制的那一刻读不到机制，把选项念成了文字。机制跟着数据走，才不会丢。
    """
    out = dict(picks)
    out["render_via"] = PICK_RENDER_TOOL
    out["render_note"] = PICK_RENDER_NOTE
    out["fallback_note"] = PICK_FALLBACK_NOTE
    return out


def render_opening_bundle() -> dict:
    """开场：**三问一卡**，陛下点完即可开拟。

    起因（2026-10-22 陛下反馈）：原先一项一项追问，效率太低。
    现在三问合成**同一张卡片**，一次点完，不再等第二轮：

    1. **今日想用何膳** —— 四项，前两项固定不可换序（陛下钦定）
    2. **用度与人数** —— 预设档位，全可点；要自定走卡片「其他」
    3. **传膳方式与去处** —— 外送 / 自取两条岔路 + 地址，合成一问

    返回的 `questions` 可直接**整组**填进 `AskUserQuestion` 的 `questions` 参数。
    """
    q1 = suggest_picks("opening")
    q2 = suggest_picks("people_budget")
    q3 = suggest_picks("delivery_plan")
    questions = [
        {"header": OPENING_BUNDLE_HEADERS["opening"],
         "question": q1["question"], "multiSelect": q1["multiSelect"],
         "options": q1["options"]},
        {"header": OPENING_BUNDLE_HEADERS["people_budget"],
         "question": q2["question"] + "（" + q2["custom_hint"] + "）",
         "multiSelect": False, "options": q2["options"]},
        {"header": OPENING_BUNDLE_HEADERS["delivery_plan"],
         "question": q3["question"],
         "multiSelect": False, "options": q3["options"]},
    ]
    return {
        "greeting": OPENING_GREETING,
        "questions": questions,
        "required_options": list(OPENING_REQUIRED),
        "render_via": PICK_RENDER_TOOL,
        "render_note": ("把 questions **整组**原样填进 AskUserQuestion 的 "
                        "questions 参数，一次呈出三问；不得拆成多轮追问，"
                        "也不得改写成文字让陛下打字"),
        "fallback_note": PICK_FALLBACK_NOTE,
        "note": ("前两项为陛下钦定的固定项，臣不得增删挪位；三问皆可点选，不必打字。"
                 "呈上后本轮到此为止——陛下点选前不得读 workflow/、不得调 MCP。"),
    }


def suggest_picks(stage: str, **kw) -> dict:
    """产出结构化选项，供调用方直接呈成选项卡片（陛下点选，不打字）。

    返回 {stage, question, multiSelect, options:[{label, description}],
    render_via, render_note, fallback_note}。
    调用方把 question / multiSelect / options 原样填进提问工具即可，
    不要改写成"陛下可回复：…"。
    """
    return _with_render_hint(_suggest_picks_raw(stage, **kw))


def _suggest_picks_raw(stage: str, **kw) -> dict:
    """`suggest_picks` 的本体：只产 {stage, question, multiSelect, options}。"""
    def opt(label, desc):
        return {"label": label, "description": desc}

    if stage == "opening":
        # 陛下刚上朝的头一问：四项，**前两项固定不可换序**
        opts = [
            opt(OPENING_REQUIRED[0],
                "按陛下点选的用度与人数，以官方价格拟一折"),
            opt(OPENING_REQUIRED[1],
                "跳过用度推敲，按当日节气/节日主题与官方活动直接呈一折"),
            opt("看看今日优惠", "先呈礼部呈报与陛下可用券，再决定吃什么"),
            opt("换换口味·看新品", "优先官方活动里的新品与限定"),
        ]
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False, "options": opts}

    if stage == "scene":
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False,
                "options": [
                    opt("麦乐送外送", "送到府上，含配送费与打包费（默认）"),
                    opt("到店自取", "需陛下告知城市与地段，臣再按位置找门店"),
                    opt("得来速车道取餐", "驾车取餐，门店会带 beCode"),
                ]}

    if stage == "budget":
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False,
                "options": [
                    opt("20 元以内", "轻食小点为主"),
                    opt("30 元以内", "一份套餐的量"),
                    opt("50 元以内", "套餐加小食或双人份"),
                    opt("不限", "由臣按口味与当日主题拟"),
                ]}

    if stage == "people_budget":
        # 用度与人数合成一问：都是点选，不给陛下留空白。
        # （起因：陛下要求开场把预算、人数一次问清，别再一轮一轮追问。）
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False,
                "options": [
                    opt("1 人 · 30 元以内", "独自用膳，一份套餐的量"),
                    opt("2 人 · 50 元以内", "两人分享，套餐加小食"),
                    opt("3 人及以上 · 80 元以内", "家宴或同席，量足些"),
                    opt("人数与用度都不限", "由臣按口味与当日主题拟"),
                ],
                "custom_hint": "若要自定，如「2 人 45 元」，在卡片里选「其他」"
                               "直接填即可，臣照此核价"}

    if stage == "delivery_plan":
        # 传膳方式 + 去处合成一问：四种点选覆盖外送/自取两条岔路，
        # 免得先问"外送还是自取"、再问"地址"——那是两轮。
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False,
                "options": [
                    opt("麦乐送外送 · 送至默认地址",
                        "陛下地址簿第一处，含配送费与打包费（默认）"),
                    opt("麦乐送外送 · 另换一处",
                        "在卡片里选「其他」告知臣新地址，臣先建地址再查可配送门店"),
                    opt("到店自取 · 按默认地址附近",
                        "以外送收货地反推地段；若只切到区县，臣会提醒偏粗"),
                    opt("到店自取 · 另指一处地段",
                        "在卡片里选「其他」给句路名/门牌/地标，臣按位置寻店"),
                ]}

    if stage == "after_memorial":
        names = [str(c.get("name")) for c in (kw.get("candidates") or [])[:2]]
        cheapest = kw.get("cheapest")
        opts = [
            opt("就按这个下单", "进入三重复述，臣再逐项请陛下点头"),
            opt("换个更省的", "优先带券与低价组合"
                + (f"，如「{cheapest}」" if cheapest else "")),
            opt("换个新品", "优先官方活动里的新品"),
            opt("调整预算", "重设用度后再拟"),
        ]
        for n in names:
            opts.append(opt(f"看看「{n}」", "取该膳品详情与官方图"))
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False, "options": opts}

    if stage == "order_confirm":
        pending = kw.get("pending") or ["content", "amount", "delivery"]
        word = {"content": "订单内容无误", "amount": "金额明细无误",
                "delivery": "交付方式无误"}
        opts = [opt(word[s], f"确认第{i}项复述")
                for i, s in enumerate(pending, 1) if s in word]
        if not opts:
            opts = [opt("确认，就按这个下单", "三重复述皆已点头，可出待支付订单"),
                    opt("再改改", "回到拟单，臣重新编排")]
        opts.append(opt("算了，不下单", "臣不创建任何订单"))
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False, "options": opts}

    if stage == "ice":
        values = kw.get("values") or ["标准", "去冰", "多冰", "少冰"]
        name = kw.get("name") or "此膳"
        return {"stage": stage, "question": f"「{name}」{PICK_QUESTION[stage]}",
                "multiSelect": False,
                "options": [opt(v, f"选「{v}」" + ("（官方默认）" if i == 0 else ""))
                            for i, v in enumerate(values)]}

    if stage == "coupon":
        n = kw.get("count") or 0
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False,
                "options": [
                    opt("领", f"一键领取当前可领的 {n} 张（官方只能全领，臣挑不出单张）"),
                    opt("不领", "臣不去动陛下的券包"),
                ]}

    if stage == "address":
        addrs = kw.get("addresses") or []
        opts = [opt(str(a.get("label") or a.get("fullAddress") or "地址"),
                    "送至此处")
                for a in addrs[:3]]
        opts.append(opt("新增地址", "陛下提供字段后臣再创建，不予擅拟"))
        opts.append(opt("改到店自取", "不外送，臣另问陛下城市与地段"))
        return {"stage": stage, "question": PICK_QUESTION[stage],
                "multiSelect": False, "options": opts}

    if stage == "store_area":
        city = kw.get("city") or ""
        keyword = kw.get("keyword") or ""
        coarse = bool(kw.get("coarse"))
        opts = []
        if city:
            if coarse:
                # 关键词只到区县/城市一级：**不推荐**直接查，先请陛下给具体地标
                opts.append(opt("给个更准的地标",
                                f"「{keyword}」太粗，区中心可能离陛下很远——"
                                "给个路名或门牌，臣再查（推荐）"))
                opts.append(opt(f"就先按「{keyword}」查",
                                "凑合看看，不满意臣再换个地段"))
            else:
                opts.append(opt(f"就按「{keyword}」",
                                "以陛下收货地所在位置就近寻店（推荐）"))
                opts.append(opt("换一个地段",
                                "臣按陛下外送地址切的，未必是陛下此刻所在——换个地标更准"))
        if not city:
            # 连城市都没有：先请陛下给地段，再给一条退路
            opts.append(opt("告诉臣地段", "一句路名/门牌/地标即可，臣按位置查"))
        opts.append(opt("改回麦乐送外送", "不自取，改送府上，无需选门店"))
        return {"stage": stage,
                "question": PICK_QUESTION[stage] if not city else
                            (f"臣只切到「{keyword}」这一级，就近恐怕不准——"
                             f"陛下给个路名或地标更妥，或先按此查？" if coarse else
                             f"臣拟按陛下收货地「{keyword}」就近寻店，陛下是否准奏？"),
                "multiSelect": False, "options": opts}

    return {"stage": stage, "question": "请陛下点选", "multiSelect": False,
            "options": [opt("继续", "按当前方案往下办"),
                        opt("重来", "回到上一步重新拟")]}


def optimize_coupons(coupons: dict, candidates: list, request: dict) -> dict:
    """本地粗筛可用优惠组合。

    原则：
      - 无法从官方返回确认适用条件的券，一律标记 unverified，不承诺可用。
      - 不做叠加假设；除非官方明确返回可叠加，否则按互斥处理。
      - 只返回少量候选，交由官方 calculate-price 核验。
    """
    # 注意：空列表 [] 表示「官方确认无券」，与「查询失败」是两回事，不能用 or 短路
    raw_list = (coupons or {}).get("coupons")
    if raw_list is None:
        raw_list = ((coupons or {}).get("data") or {}).get("coupons")
    if raw_list is None:
        return {
            "ok": False,
            "reason": "coupon_query_failed",
            "message": "户部券令查询未返回结果，臣不敢妄称有优惠。",
            "plans": [],
            "warnings": ["优惠查询失败或返回为空，本次不提供优惠方案"],
        }
    if not raw_list:
        return {
            "ok": True,
            "message": "户部查得：当前无可用券令。",
            "plans": [],
            "warnings": ["官方返回优惠券列表为空"],
        }

    budget = request.get("budget_max")
    plans = []
    for cand in candidates:
        price = cand.get("price")
        if price is None:
            continue
        applicable = []
        for c in raw_list:
            cname = c.get("name") or c.get("couponName") or "未命名券"
            threshold = c.get("threshold") or c.get("minAmount") or c.get("thresholdFen")
            if threshold is not None and float(threshold) > 0:
                # 阈值可能以「分」为单位，统一尝试归一到元
                thr = float(threshold)
                if thr > 500:
                    thr = thr / 100.0
                if price + 1e-9 < thr:
                    continue
            applicable.append({
                "coupon_id": c.get("couponId") or c.get("id"),
                "coupon_code": c.get("couponCode") or c.get("code"),
                "name": cname,
                "verified": bool(c.get("verified", False)),
                "condition": c.get("condition") or c.get("ruleText") or "未返回适用条件",
            })
        plans.append({
            "code": cand.get("code"),
            "name": cand.get("name"),
            "list_price": price,
            "coupons": applicable,
            "within_budget": (budget is None or price <= budget),
        })

    plans.sort(key=lambda p: (-len(p["coupons"]), p["list_price"]))
    unverified = sum(
        1 for p in plans for c in p["coupons"] if not c["verified"])
    return {
        "ok": True,
        "plans": plans[: max(1, min(3, request.get("plan_limit", 3)))],
        "warnings": (
            [f"有 {unverified} 张券的适用条件未核实（官方返回中未确认），"
             f"须以官方核价结果为准"] if unverified else []
        ),
        "note": "这里只是本地粗筛。最终能否使用、减免多少，一律以官方核价为准。",
    }


# ===========================================================================
# [6] price_verification —— 官方核价结果核验
# ===========================================================================

def verify_price(verified: dict) -> dict:
    """核验官方 calculate-price 的返回。

    接受两种入参：
      - 已适配：{"plans":[{"name":..., "official_total_fen":..., ...}]}
      - 原始返回：{"success":true,"data":{...price...}}，此处自动适配
    官方未返回的项目标记为 estimated=False 且 price_source="未核验"。
    """
    if not ((verified or {}).get("plans")):
        adapted = adapt_mcd_price(verified or {})
        if adapted:
            verified = {"plans": [adapted]}
    plans = (verified or {}).get("plans") or []
    if not plans:
        return {
            "ok": False,
            "reason": "price_verification_failed",
            "message": "御膳账目未能核验，臣不敢报出实价。",
            "rows": [],
            "warnings": ["官方核价未返回结果"],
        }

    rows = []
    for p in plans:
        fen = p.get("official_total_fen")
        yuan = p.get("official_total")
        if fen is not None:
            total = round(float(fen) / 100.0, 2)
            src = "官方核价（calculate-price）"
        elif yuan is not None:
            total = round(float(yuan), 2)
            src = "官方核价（calculate-price）"
        else:
            total = None
            src = "未核验"
        rows.append({
            "name": p.get("name"),
            "total": total,
            "discount": p.get("discount"),
            "coupon": p.get("coupon"),
            "price_source": src,
            "estimated": total is None,
            "raw": p,
        })

    confirmed = [r for r in rows if r["total"] is not None]
    result = {
        "ok": True,
        "rows": rows,
        "confirmed_count": len(confirmed),
        "warnings": [],
    }
    if len(confirmed) < len(rows):
        result["warnings"].append(
            f"有 {len(rows) - len(confirmed)} 个方案未能取得官方核价，已标记为未核验，不作为推荐依据")
    if confirmed:
        best = min(confirmed, key=lambda r: r["total"])
        result["best"] = best
        result["summary"] = (
            f"在本次查询到的官方餐品、优惠与可核验方案范围内，"
            f"臣已为陛下比较当前可确认的价格。"
        )
    else:
        result["summary"] = "本次未能取得任何官方核价结果，臣不敢妄称价格。"
    return result


# ===========================================================================
# [8] scene_router —— 用餐场景路由（到店自取 / 麦乐送外送 / 得来速 / 企业团餐）
#
# 本模块【只做参数编排与流程指引】，不发起任何网络请求。
# 外送链路与到店链路的真实差异（均已由真实调用验证）：
#   1. 到店自取 beType=1 无需 beCode；麦乐送 beType=2 必传 beCode，
#      否则官方返回 code=600048「外送场景下，beType=2/5/6时必传beCode」。
#   2. 外送多一道前置：delivery-query-addresses → delivery-query-stores，
#      由后者返回 storeCode + beCode，才能进入 query-meals / calculate-price。
#   3. delivery-create-address 是写操作，本项目一律不自动调用。
# ===========================================================================

SCENE_PRESETS = {
    "dine_in": {
        "key": "dine_in",
        "name": "到店自取",
        "palace": "御膳房当值",
        "beType": 1,
        "orderType": 1,
        "needs_be_code": False,
        "implemented": True,
        "entry_tool": "query-nearby-stores",
        "chain": [
            "query-nearby-stores（取 storeCode）",
            "query-meals（beType=1, orderType=1）",
            "query-store-coupons（可选）",
            "calculate-price（可选核价）",
        ],
    },
    "delivery": {
        "key": "delivery",
        "name": "麦乐送外送",
        "palace": "驿站传膳",
        "beType": 2,
        "orderType": 2,
        "needs_be_code": True,
        "implemented": True,
        "entry_tool": "delivery-query-addresses",
        "chain": [
            "delivery-query-addresses（取 addressId）",
            "delivery-query-stores（beType=2，取 storeCode + beCode）",
            "query-meals（beType=2, orderType=2, 必传 beCode）",
            "query-store-coupons（beType=2, orderType=2）",
            "calculate-price（beType=2, orderType=2）",
        ],
    },
    "drive_thru": {
        "key": "drive_thru",
        "name": "得来速",
        "palace": "车驾传膳",
        "beType": 5,
        "orderType": None,
        "needs_be_code": True,
        "implemented": False,
        "entry_tool": None,
        "chain": [],
        "note": "需 beCode，本版未实现，遇此需求如实告知并建议改用官方渠道。",
    },
    "group_meal": {
        "key": "group_meal",
        "name": "企业团餐",
        "palace": "百官会膳",
        "beType": 6,
        "orderType": None,
        "needs_be_code": True,
        "implemented": False,
        "entry_tool": None,
        "chain": [],
        "note": "需 beCode 且涉及预算/人数，本版未实现。",
    },
}

# 场景识别关键词。冲突时以更具体的（外送）优先。
SCENE_KEYWORDS = {
    "delivery": ["外送", "外卖", "麦乐送", "配送", "送到", "送到家", "送到公司",
                 "上门", "叫外卖", "点外卖", "送餐", "宅急送"],
    "drive_thru": ["得来速", "车道", "开车买", "不下车"],
    "group_meal": ["团餐", "企业订餐", "公司订餐", "员工餐", "会议餐"],
    "dine_in": ["到店", "自取", "堂食", "门店吃", "店里吃", "去店里", "附近门店"],
}

# ──────────────────────────────────────────────────────────────────────
# 写操作分级治理
#
# 原先把「领券」和「下单」混为一档「一律禁止」，过于粗放——二者的风险量级
# 根本不同：下单不可逆且要花钱，领券免费且几乎无损失。一律禁止的结果是
# 陛下还得自己打开小程序去领，链路断在这里，推荐也就白做了。
#
# 现改为三档：
#   第一档 NEVER           —— 永不执行。消耗账号资产且无撤销路径。
#   第二档 CONFIRM         —— 臣先把要做什么逐字复述一遍，陛下明示确认后才执行。
#                            免费或可撤销，风险可承受。
#   第三档 CONFIRM_STRICT  —— 下单类。比第二档再严一档：须「三重复述」
#                            （订单内容 / 金额明细 / 交付方式）全部点头才执行。
#
# 为何下单可以进 CONFIRM_STRICT 而不是 NEVER（已查证官方工具声明）：
#   `create-order` 官方声明的下一步是「引导用户通过支付链接扫码或打开麦当劳 APP
#   完成支付」——即它创建的只是**待支付订单**，支付这一刀由官方切给了用户。
#   故「创建订单」与「付款」是两件事，不该同等对待；臣绝不代付这一条不变。
#
# 下列仅为「分级清单」声明，不是调用；测试扫描时会剥离本声明块。
# ──────────────────────────────────────────────────────────────────────
WRITE_TIER_NEVER = ("draw-lottery",)

WRITE_TIER_CONFIRM = ("auto-bind-coupons", "delivery-create-address",
                      "cancel-order")

WRITE_TIER_CONFIRM_STRICT = ("create-order", "mall-create-order",
                             "party-order-create")

# 兼容旧字段：全部受管控的写操作（三档合计）
DELIVERY_WRITE_TOOLS = (WRITE_TIER_NEVER + WRITE_TIER_CONFIRM
                        + WRITE_TIER_CONFIRM_STRICT)

# 下单三重复述的步骤键（顺序即复述顺序）
ORDER_CONFIRM_STEPS = ("content", "amount", "delivery")

# 代下单的工具名（第三档：三重复述后方可执行）
ORDER_CREATE_TOOL = "create-order"

# 撤单工具名（第二档：可撤销，但须陛下确认）
ORDER_CANCEL_TOOL = "cancel-order"

# 挂起中的写工具名：仅在用户明确提供全部字段并确认后，才由调用方决定是否调用。
PENDING_ADDRESS_CREATE_TOOL = "delivery-create-address"

# 代领券令的工具名（第二档：确认后可执行）
COUPON_CLAIM_TOOL = "auto-bind-coupons"


def detect_scene(text: str, explicit: str | None = None) -> dict:
    """识别用餐场景。

    explicit：调用方显式指定的场景 key，优先级最高。
    无法判断时默认**麦乐送外送**（陛下实测：多数时候就是要外送），
    并标注为「默认推断」而非用户明示。
    """
    if explicit:
        preset = SCENE_PRESETS.get(explicit)
        if preset:
            return {**preset, "source": "explicit", "confidence": "high"}
        return {"key": None, "name": "未知场景", "source": "explicit",
                "confidence": "low", "implemented": False,
                "message": f"未知场景标识：{explicit}"}

    low = str(text or "").lower()
    for key in ("delivery", "drive_thru", "group_meal", "dine_in"):
        if _hit_any(low, SCENE_KEYWORDS[key]):
            preset = dict(SCENE_PRESETS[key])
            preset["source"] = "inferred"
            preset["confidence"] = "high" if key != "dine_in" else "medium"
            return preset

    preset = dict(SCENE_PRESETS["delivery"])
    preset["source"] = "default"
    preset["confidence"] = "low"
    preset["message"] = ("陛下未言明用膳方式，臣暂按**麦乐送外送**办理"
                         "（陛下可点选改为到店自取）。")
    return preset


# ── 到店取餐：官方不提供定位，只能问陛下 ──────────────────────────────
# 已核对官方工具声明：query-nearby-stores 只有 beType / searchType / city / keyword，
#   searchType=1（默认）= 查「收藏餐厅」——不按位置，所以返回的店可能很远；
#   searchType=2 = 按位置搜索，city 与 keyword 必填。
# **没有经纬度参数，也不按 IP 定位**，故臣无法自行得知陛下在哪。
# 唯一正确做法：问陛下「哪个城市、哪一带」，再以 searchType=2 查询。
STORE_SEARCH_TOOL = "query-nearby-stores"

# 关于「IP 定位」的结论（2026-10-22 实跑核实，写在此处以免后来者再绕一圈）：
#   ① 臣（智能体）拿不到陛下 IP —— 对话里没有这个字段，宿主也不提供；
#   ② 也不需要：query-nearby-stores 虽只收 city / keyword 两个**文本**入参，
#      但服务端会拿 keyword 做地理编码，返回 distance（米）并已由近及远排序
#      （实测："西湖区"→最近 2545m；换"黄龙体育中心"→188m、"天目山路148号"→410m）；
#   ③ IP 定位本身也不可靠：粒度只到城市，移动网络 / 宽带出口 / VPN 常定位到隔壁城市。
# 所以臣要做的不是"找到陛下在哪"，而是"把关键词说具体"。
# 零打扰的位置线索：陛下已有的麦乐送地址（含市、区/县）可反推出默认关键词。
IP_GEO_NOTE = (
    "臣拿不到陛下 IP，也不需要：官方门店接口按关键词地理编码返回「到店距离」，"
    "臣只需把地段关键词说具体，不必（也无法）读取陛下位置。"
)

_PROVINCE_SUFFIX = ("省", "自治区")
_CITY_SUFFIX = "市"
_DISTRICT_SUFFIX = ("区", "县", "旗")


# 关键词精度分级。**区县一级不能拿来当"就近"**——区中心离陛下可能几公里，
# 2026-10-23 实测（同一查询点，公开门牌）：keyword 用「西湖区」最近 2545m，
# 用「天目山路148号」410m、「黄龙体育中心」188m——区县一级直接被送到区中心，差 13.5 倍。
KEYWORD_LEVEL_STREET = "street"      # 路名 + 门牌号，最准
KEYWORD_LEVEL_LANDMARK = "landmark"  # 小区 / 大厦 / 广场
KEYWORD_LEVEL_DISTRICT = "district"  # 区县——偏粗，须如实提醒
KEYWORD_LEVEL_CITY = "city"          # 只剩城市，几乎等于没有

_ROAD_SUFFIX = "路|街|大道|巷|弄|条|胡同|道|里"
_LANDMARK_SUFFIX = ("小区|大厦|广场|中心|公寓|花园|苑|家园|府|园区|写字楼"
                    "|大厦|商城|商厦|大楼|科技园|产业园|万达|银泰|天街")
_STREET_RE = re.compile(rf"[\u4e00-\u9fa5A-Za-z0-9]{{2,10}}(?:{_ROAD_SUFFIX})\s*\d+\s*号")
_ROAD_RE = re.compile(rf"[\u4e00-\u9fa5A-Za-z0-9]{{2,10}}(?:{_ROAD_SUFFIX})")
_LANDMARK_RE = re.compile(rf"[\u4e00-\u9fa5A-Za-z0-9]{{2,14}}(?:{_LANDMARK_SUFFIX})")


def extract_street_keyword(rest: str) -> tuple[str, str] | tuple[None, None]:
    """从「区县之后的那一段」里切出可地理编码的街道级关键词。

    返回 (关键词, 精度等级)；切不出返回 (None, None)，由调用方降级到区县。
    门牌号优先于小区名优先于路名——门牌号地理编码最准。
    """
    if not rest:
        return None, None
    m = _STREET_RE.search(rest)
    if m:
        return m.group(0).strip(), KEYWORD_LEVEL_STREET
    m = _LANDMARK_RE.search(rest)
    if m:
        return m.group(0).strip(), KEYWORD_LEVEL_LANDMARK
    m = _ROAD_RE.search(rest)
    if m:
        return m.group(0).strip(), KEYWORD_LEVEL_LANDMARK
    return None, None


def parse_address_location(full_address: str) -> dict:
    """从中文地址文本里切出「城市 / 区县 / 街道级关键词」，供按位置查门店用。

    ⚠️ 区县一级**不得**当作"就近"用：区中心离陛下可能几公里。
    故本函数尽量切到路名 + 门牌号；切不出才降级，并如实标注精度等级。
    例：「浙江省杭州市西湖区天目山路148号…」→ city=杭州, district=上城区,
        keyword=天目山路148号, keyword_level=street
    """
    if not isinstance(full_address, str) or not full_address.strip():
        return {"ok": False, "city": None, "district": None, "keyword": None,
                "keyword_level": None, "reason": "empty",
                "note": "地址为空，臣无从反推。"}

    text = full_address.strip()
    city = district = None
    rest_after_city = ""

    # 直辖市：北京/上海/天津/重庆 直接以市名为城市，后接区名
    for m in ("北京市", "上海市", "天津市", "重庆市"):
        if text.startswith(m):
            city = m[:-1]
            rest_after_city = text[len(m):]
            for suf in _DISTRICT_SUFFIX:
                idx = rest_after_city.find(suf)
                if 0 < idx <= 6:
                    district = rest_after_city[: idx + len(suf)]
                    break
            break

    if city is None:
        idx_city = text.find(_CITY_SUFFIX)
        if idx_city > 0:
            city = text[idx_city - 2: idx_city] if idx_city >= 2 else None
            # 内蒙古等地市名可达 3~4 字，向前取到省名之后为止
            head = text[:idx_city]
            for sep in _PROVINCE_SUFFIX:
                p = head.find(sep)
                if p >= 0:
                    city = head[p + len(sep):]
                    break
            rest_after_city = text[idx_city + 1:]
            for suf in _DISTRICT_SUFFIX:
                idx = rest_after_city.find(suf)
                if 0 < idx <= 6:
                    district = rest_after_city[: idx + len(suf)]
                    break

    city = city.strip() if city else None
    district = district.strip() if district else None
    if not city:
        return {"ok": False, "city": None, "district": None, "keyword": None,
                "keyword_level": None, "reason": "unparsed",
                "note": "地址里未能切出城市，臣不敢妄断，请陛下明示。"}

    # 区县之后那一段才是"陛下真正所在的位置"
    street_rest = rest_after_city
    if district:
        pos = street_rest.find(district)
        if pos >= 0:
            street_rest = street_rest[pos + len(district):]

    keyword, level = extract_street_keyword(street_rest)
    if not keyword:
        keyword, level = (district or city), (
            KEYWORD_LEVEL_DISTRICT if district else KEYWORD_LEVEL_CITY)

    return {
        "ok": True,
        "city": city,
        "district": district,
        "keyword": keyword,
        "keyword_level": level,
        "source": "address",
        "confidence": {"street": "high", "landmark": "medium",
                       "district": "low", "city": "very_low"}.get(level, "low"),
        "from_address": text,
        "street_rest": street_rest.strip(),
        "note": _keyword_level_note(level, keyword),
    }


def _keyword_level_note(level: str, keyword: str) -> str:
    if level == KEYWORD_LEVEL_STREET:
        return (f"已按陛下外送地址切到街道门牌（{keyword}），"
                "就近较准；此为收货地，非陛下此刻位置。")
    if level == KEYWORD_LEVEL_LANDMARK:
        return (f"按陛下外送地址切到地标（{keyword}）就近寻店；"
                "此为收货地，非陛下此刻位置。")
    if level == KEYWORD_LEVEL_DISTRICT:
        return (f"⚠️ 只切到区县一级（{keyword}）——**区中心离陛下可能很远**，"
                "就近不准。陛下给个路名或地标（如「天目山路148号」），臣立刻重查。")
    return (f"⚠️ 只切到城市一级（{keyword}），就近几乎无效；"
            "请陛下给个具体地标，臣才查得准。")


def guess_store_location(addresses) -> dict:
    """从 delivery-query-addresses 的结果里反推城市与地段。

    接受三种形态：adapt_mcd_addresses 的输出、{"addresses": [...]}、
    或裸列表。取第一个能解析出城市的地址。
    """
    items = []
    if isinstance(addresses, dict):
        items = addresses.get("addresses") or []
        if not items:
            # 官方原始返回：地址在 data.addresses 下
            data = addresses.get("data")
            if isinstance(data, dict):
                items = data.get("addresses") or []
    elif isinstance(addresses, (list, tuple)):
        items = list(addresses)
    for a in items:
        if not isinstance(a, dict):
            continue
        # 兼容两种形态：adapt_mcd_addresses 的 snake_case，与官方原始 camelCase
        full = (a.get("fullAddress") or a.get("full_address")
                or a.get("label") or a.get("address") or "")
        parsed = parse_address_location(str(full))
        if parsed.get("ok"):
            parsed["address_id"] = a.get("addressId") or a.get("address_id")
            return parsed
    return {"ok": False, "city": None, "district": None, "keyword": None,
            "keyword_level": None, "reason": "no_address",
            "note": "陛下账户下暂无可用地址，臣无法反推位置。"}


def build_store_request(city: str | None = None,
                        keyword: str | None = None,
                        be_type: int = 1,
                        addresses=None) -> dict:
    """编排「到店取餐」的门店查询。

    位置线索的优先级：
      ① 陛下明示的 city + keyword   → status=ready，可直接查；
      ② 由已有外送地址反推的 city/keyword → status=need_confirm，
         附点选项让陛下**点一下确认**，不必打字；
      ③ 都没有                      → status=need_ask，请陛下点选/补一句地段。
    """
    be_type = be_type if be_type in (1, 5) else 1
    name = "到店自取" if be_type == 1 else "得来速车道取餐"

    base = {
        "tool": STORE_SEARCH_TOOL,
        "be_type": be_type,
        "be_type_name": name,
        "caveat": ("⚠️ 官方门店接口不读取陛下 IP，返回的 longitude/latitude 恒为 0.0；"
                   "「就近」由服务端拿 keyword 做地理编码算 distance（米）并排好序——"
                   "**所以关键词越具体越准，IP 帮不上忙**。"),
        "ip_geo_note": IP_GEO_NOTE,
        "distance_note": STORE_DISTANCE_NOTE,
    }

    if city and keyword:
        base.update({
            "ok": True, "status": "ready", "city": city, "keyword": keyword,
            "keyword_level": KEYWORD_LEVEL_STREET, "source": "user",
            "confidence": "high",
            "params": {"beType": be_type, "searchType": 2,
                       "city": city, "keyword": keyword},
            "message": f"臣已备好门店查询口径：{city} · {keyword}（{name}）。",
            "ask": None,
        })
        return base

    guess = guess_store_location(addresses) if addresses is not None else None
    if guess and guess.get("ok"):
        g_city, g_kw = guess["city"], guess["keyword"]
        level = guess.get("keyword_level") or KEYWORD_LEVEL_DISTRICT
        coarse = level in (KEYWORD_LEVEL_DISTRICT, KEYWORD_LEVEL_CITY)
        base.update({
            "ok": False, "status": "need_confirm",
            "city": g_city, "keyword": g_kw,
            "district": guess.get("district"),
            "keyword_level": level,
            "coarse_keyword": coarse,
            "source": "address", "confidence": guess.get("confidence", "low"),
            "params": None,
            "from_address": guess.get("from_address"),
            "message": (guess.get("note") or "")
                      + ("　" if guess.get("note") else "")
                      + ("**点一下即可**，不必打字。"
                         if not coarse else
                         "**陛下若肯给一句路名或地标，就近立刻准得多。**"),
            "ask": {
                "question": (f"臣拟按陛下收货地「{g_kw}」就近寻店，陛下是否准奏？"
                             if not coarse else
                             f"臣只切到「{g_kw}」这一级，就近恐怕不准——"
                             f"陛下给个路名或地标更妥，或先按此查？"),
                "picks": suggest_picks("store_area", city=g_city,
                                       keyword=g_kw, coarse=coarse),
                "fields": [
                    {"key": "city", "label": "城市", "example": g_city},
                    {"key": "keyword", "label": "路名 / 门牌 / 地标",
                     "example": g_kw if not coarse else "天目山路148号、黄龙体育中心"},
                ],
                "note": ("此为陛下**外送收货地**，非实时定位，也未必是陛下此刻所在；"
                         "陛下点「换一个地段」即可改。"),
            },
        })
        return base

    base.update({
        "ok": False, "status": "need_ask",
        "city": None, "keyword": None, "keyword_level": None,
        "source": None, "confidence": "low",
        "params": None,
        "message": ("官方门店接口不按陛下位置自动定位——默认只查「收藏餐厅」，"
                    "所以返回的门店往往很远。臣需陛下一句地段，"
                    "方可按位置就近查找。"),
        "ask": {
            "question": "敢问陛下要在哪一带取膳？",
            "fields": [
                {"key": "city", "label": "城市", "example": "杭州"},
                {"key": "keyword", "label": "地段 / 地标",
                 "example": "西湖文化广场、钱江新城、滨江星光大道"},
            ],
            "note": "两项齐备臣才好按位置查（searchType=2）；只给城市则仍可能偏远。",
        },
    })
    return base


def adapt_mcd_addresses(raw: dict) -> dict:
    """适配 delivery-query-addresses 的真实返回。

    真实结构（已实跑验证）：data.addresses[]，字段含
    addressId / contactName / fullAddress / phone。
    空列表是真实结果，代表账户下暂无配送地址，不得伪造地址。
    """
    if not isinstance(raw, dict):
        return {"ok": False, "reason": "invalid_response", "addresses": [],
                "message": "地址接口返回异常，臣不敢妄拟地址。"}
    data = raw.get("data") if "data" in raw else raw
    if not isinstance(data, dict):
        return {"ok": False, "reason": "invalid_response", "addresses": [],
                "message": "地址接口返回结构异常，臣不敢妄拟地址。"}
    if raw.get("success") is False:
        return {"ok": False, "reason": "api_error", "addresses": [],
                "message": f"地址查询失败：{raw.get('message') or '未提供原因'}"}

    raw_list = data.get("addresses")
    if raw_list is None:
        return {"ok": False, "reason": "missing_field", "addresses": [],
                "message": "官方返回中未含 addresses 字段，臣无法确认配送地址。"}

    addresses = []
    for i, a in enumerate(raw_list or [], 1):
        addresses.append({
            "index": i,
            "address_id": a.get("addressId"),
            "contact_name": a.get("contactName"),
            "full_address": a.get("fullAddress"),
            "phone": a.get("phone"),
        })

    if not addresses:
        return {"ok": True, "empty": True, "addresses": [],
                "message": "陛下账户下暂无已保存的配送地址（官方返回空列表）。"}
    return {"ok": True, "empty": False, "addresses": addresses}


def adapt_mcd_delivery_stores(raw: dict) -> dict:
    """适配 delivery-query-stores 的真实返回。

    字段口径取自官方工具声明：storeName / address / storeCode / beCode / reservation。
    ⚠️ 本函数【未经真实返回验证】——当前账户无配送地址，无法取得 addressId，
       故该接口未实跑成功。字段缺失时一律标注 unknown，绝不补全。
    """
    if not isinstance(raw, dict):
        return {"ok": False, "reason": "invalid_response", "stores": [],
                "message": "可配送门店接口返回异常。", "verified_by_real_call": False}
    if raw.get("success") is False:
        return {"ok": False, "reason": "api_error", "stores": [],
                "message": f"可配送门店查询失败：{raw.get('message') or '未提供原因'}",
                "verified_by_real_call": True}

    data = raw.get("data")
    raw_list = data if isinstance(data, list) else (
        (data or {}).get("stores") if isinstance(data, dict) else None)
    if raw_list is None:
        return {"ok": False, "reason": "missing_field", "stores": [],
                "message": "官方返回中未含门店列表，臣无法确认可配送门店。",
                "verified_by_real_call": False}

    stores = []
    for s in raw_list or []:
        be_code = s.get("beCode")
        stores.append({
            "store_code": s.get("storeCode"),
            "be_code": be_code,
            "name": s.get("storeName"),
            "address": s.get("address"),
            "reservation": s.get("reservation"),
            "be_code_known": bool(be_code),
        })
    return {"ok": True, "stores": stores, "verified_by_real_call": True}


# ── 到店门店：官方自带「到店距离」 ──────────────────────────────────
# 2026-10-22 实跑核实（traceId f4aa4001… / 83a57ea1…）：
#   query-nearby-stores 返回里**有 distance 字段（单位：米）**，且已由近及远排序；
#   distance 是**服务端拿 keyword 做地理编码后算的**，不是拿陛下位置算的——
#   同一城市换关键词，排序立刻变（"上城区"→最近 245m；"杭州大厦501城市广场"→98m）。
#   longitude / latitude 恒为 0.0，不可用于本地算距。
# 结论：**不需要 IP 定位**。臣真正要做的不是找陛下在哪，而是把 keyword 说具体。
STORE_DISTANCE_NOTE = (
    "官方返回自带「到店距离」（米），由服务端按关键词地理编码计算，"
    "且已由近及远排序——关键词越具体，就近越准。"
)


def adapt_mcd_nearby_stores(raw: dict) -> dict:
    """适配 query-nearby-stores 的真实返回（含官方 distance）。"""
    if not isinstance(raw, dict):
        return {"ok": False, "reason": "invalid_response", "stores": [],
                "message": "门店接口返回异常，臣不敢妄报。",
                "verified_by_real_call": False}
    if raw.get("success") is False:
        return {"ok": False, "reason": "api_error", "stores": [],
                "message": f"门店查询失败：{raw.get('message') or '未提供原因'}",
                "verified_by_real_call": True}

    data = raw.get("data")
    raw_list = data if isinstance(data, list) else (
        (data or {}).get("stores") if isinstance(data, dict) else None)
    if raw_list is None:
        return {"ok": False, "reason": "missing_field", "stores": [],
                "message": "官方返回中未含门店列表。", "verified_by_real_call": False}

    stores = []
    for s in raw_list or []:
        if not isinstance(s, dict):
            continue
        dist = s.get("distance")
        # distance 缺失或非法时不臆造；经纬度恒为 0.0，不参与换算
        try:
            dist = int(dist) if dist is not None else None
        except (TypeError, ValueError):
            dist = None
        stores.append({
            "store_code": s.get("storeCode"),
            "be_code": s.get("beCode"),
            "name": s.get("storeName"),
            "address": s.get("address"),
            "distance_m": dist,
            "open": s.get("businessStatus"),
            "hours": ((s.get("businessStartTime") or "") + "-"
                      + (s.get("businessEndTime") or ""))
                     if s.get("businessStartTime") else None,
            "reservation": s.get("reservation"),
        })
    # 官方已排序；本地再排一次只为兜底，不改变官方口径
    stores.sort(key=lambda x: (x["distance_m"] is None, x["distance_m"] or 0))
    return {"ok": True, "stores": stores,
            "nearest": stores[0] if stores else None,
            "distance_note": STORE_DISTANCE_NOTE,
            "verified_by_real_call": True}


def fmt_distance(meters) -> str:
    """距离显示：官方单位是米。"""
    if meters is None:
        return "距离官方未返回"
    try:
        m = int(meters)
    except (TypeError, ValueError):
        return "距离官方未返回"
    if m < 0:
        return "距离官方未返回"
    return f"{m} 米" if m < 1000 else f"{m / 1000:.1f} 公里"


def render_store_list(adapted: dict, limit: int = 5, be_type: int = 1) -> str:
    """把门店列表呈成陛下能点的一段话（官方要求完整展示 storeCode / beCode）。"""
    if not adapted.get("ok"):
        return f"- ⚠️ {adapted.get('message') or '门店未查得'}"
    stores = (adapted.get("stores") or [])[:limit]
    if not stores:
        return "- 该地段未查得门店，陛下可换个地标，臣再跑一趟。"
    lines = [f"- 臣按陛下给的地段寻得 {len(stores)} 处就近门店"
             f"（官方已按距离由近及远排好）："]
    for i, s in enumerate(stores, 1):
        tail = []
        if s.get("hours"):
            tail.append(f"营业 {s['hours']}")
        if s.get("open") is False:
            tail.append("**此刻打烊**")
        lines.append(
            f"  {i}. **{s.get('name') or '未具名门店'}**　"
            f"{fmt_distance(s.get('distance_m'))}"
            f"{'　' + '　'.join(tail) if tail else ''}")
        lines.append(f"     {s.get('address') or '地址未返回'}"
                     f"　storeCode `{s.get('store_code')}`"
                     + (f"　beCode `{s.get('be_code')}`" if s.get("be_code")
                        else ""))
    lines.append(f"- {STORE_DISTANCE_NOTE}")
    return "\n".join(lines)


# 最近门店超过这个距离，就说明关键词太粗或陛下不在收货地附近，该提醒换关键词
NEARBY_TOO_FAR_M = 1500


def assess_nearby_result(adapted: dict,
                         too_far_m: int = NEARBY_TOO_FAR_M) -> dict:
    """看一眼查出来的门店：最近那家有多远？太远就建议陛下换关键词。

    臣不猜陛下在哪，只看官方返回的距离——远就是远，如实说。
    """
    if not adapted.get("ok"):
        return {"ok": False, "nearest_m": None, "too_far": False,
                "advice": adapted.get("message") or "门店未查得。"}
    nearest = adapted.get("nearest")
    if not nearest:
        return {"ok": True, "nearest_m": None, "too_far": False,
                "advice": "该地段未查得门店，陛下换个地标，臣再跑一趟。"}
    m = nearest.get("distance_m")
    too_far = bool(m is not None and m > too_far_m)
    return {
        "ok": True,
        "nearest_m": m,
        "nearest_name": nearest.get("name"),
        "nearest_store_code": nearest.get("store_code"),
        "too_far": too_far,
        "threshold_m": too_far_m,
        "advice": (
            f"最近一家是「{nearest.get('name')}」，"
            f"{fmt_distance(m)}——**超出 {fmt_distance(too_far_m)}**，"
            "多半是关键词太粗，或陛下此刻不在收货地附近。"
            "给臣一个路名/门牌/地标，臣立刻重查。"
            if too_far else
            f"最近一家「{nearest.get('name')}」{fmt_distance(m)}，就近可用。"),
    }


def build_delivery_plan(addresses: dict | None = None,
                        stores: dict | None = None,
                        chosen_address_id: str | None = None) -> dict:
    """编排麦乐送外送链路，返回下一步应调用的工具与阻塞项。

    不发起调用、不写入、不猜值。所有「未能核实」项显式列出。
    """
    preset = dict(SCENE_PRESETS["delivery"])
    plan = {
        "scene": preset,
        "status": None,
        "next_tool": None,
        "next_params": None,
        "blockers": [],
        "unverified": [],
        "notes": [],
        "guidance": [],
        "write_ops": {"auto_call_allowed": False,
                      "forbidden_tools": list(DELIVERY_WRITE_TOOLS),
                      "note": "创建地址与下单均为写操作，本项目一律不自动执行。"},
    }

    # 第一步：配送地址
    if addresses is None:
        plan["status"] = "need_address_query"
        plan["next_tool"] = "delivery-query-addresses"
        plan["next_params"] = {}
        plan["guidance"].append("臣先查阅陛下的配送地址簿。")
        return plan

    if not addresses.get("ok"):
        plan["status"] = "address_unavailable"
        plan["blockers"].append(addresses.get("message") or "地址查询失败")
        plan["guidance"].append(
            "地址未能确认，臣无法继续查询可配送门店。请陛下稍后重试，"
            "或自行在麦当劳官方渠道确认配送地址。")
        return plan

    addr_list = addresses.get("addresses") or []
    if not addr_list:
        plan["status"] = "need_address_create"
        plan["blockers"].append(
            "账户下暂无配送地址（官方 delivery-query-addresses 真实返回空列表），"
            "因此无法取得 addressId，也就无法查询可配送门店与 beCode。")
        plan["guidance"].append(
            "请陛下提供城市、联系人、电话与详细地址，臣方可代为创建配送地址。"
            "此为写入操作，臣会在您确认后逐字复述一遍再执行。")
        plan["pending_write_tool"] = PENDING_ADDRESS_CREATE_TOOL
        plan["required_fields"] = ["city", "contactName", "gender", "phone",
                                   "address", "addressDetail"]
        return plan

    if not chosen_address_id:
        plan["status"] = "need_address_choice"
        plan["next_tool"] = "delivery-query-stores"
        plan["guidance"].append("请陛下指定用哪一处方（配送地址）。")
        plan["address_options"] = addr_list
        return plan

    chosen = next((a for a in addr_list if a.get("address_id") == chosen_address_id), None)
    if not chosen:
        plan["status"] = "address_mismatch"
        plan["blockers"].append(
            f"指定的 addressId 不在官方返回的地址列表中：{chosen_address_id}")
        return plan

    plan["chosen_address"] = chosen

    # 第二步：可配送门店 + beCode
    if stores is None:
        plan["status"] = "need_store_query"
        plan["next_tool"] = "delivery-query-stores"
        plan["next_params"] = {"beType": 2, "addressId": chosen_address_id}
        return plan

    if not stores.get("ok"):
        plan["status"] = "store_unavailable"
        plan["blockers"].append(stores.get("message") or "可配送门店查询失败")
        plan["guidance"].append(
            "未能确认可配送门店，臣不敢凭空拟价。请陛下稍后重试或改用到店自取。")
        return plan

    store_list = stores.get("stores") or []
    usable = [s for s in store_list if s.get("be_code_known")]
    if not usable:
        plan["status"] = "need_be_code"
        plan["blockers"].append(
            "官方返回的门店中缺少 beCode；而外送场景（beType=2）调用 "
            "query-meals / calculate-price 必须携带 beCode，"
            "否则官方返回 code=600048。")
        plan["guidance"].append("臣暂无法完成外送核价，请陛下稍后重试或改用到店自取。")
        return plan

    plan["status"] = "ready"
    plan["stores"] = usable
    plan["next_tool"] = "query-meals"
    plan["next_params"] = {
        "beType": 2,
        "orderType": 2,
        "storeCode": usable[0]["store_code"],
        "beCode": usable[0]["be_code"],
    }

    # 起送价：麦乐送外送不设起送门槛（陛下明示；官方返回中亦无该字段），
    # 因此不再输出「未能核实」，也不作任何起送价提示。
    plan["notes"].append(
        "起送价：麦乐送外送**不设起送门槛**（陛下明示；"
        "官方 calculate-price 返回中亦无该字段），臣不作任何起送价提示。")
    plan["unverified"].append(
        "配送费与打包费：以官方 `calculate-price` 返回为准，臣不在核价前预估。")
    plan["unverified"].append(
        "外送餐品价格与到店自取不同（已实跑验证：同组合外送更高），"
        "一切以官方核价结果为准。")
    return plan


def render_delivery_section(plan: dict) -> list:
    """渲染奏折中的「驿站传膳」章节（外送场景）。"""
    L = []
    scene = plan.get("scene") or {}
    L.append(f"- 用膳方式：**{scene.get('name', '麦乐送外送')}**"
             f"（beType={scene.get('beType')}, orderType={scene.get('orderType')}）")

    guidance = {
        "need_address_query": "臣正查阅陛下的配送地址簿。",
        "address_unavailable": "地址簿未能确认，外送链路暂止于此。",
        "need_address_create": "陛下名下暂无配送地址，需先添置一处，方可查询可配送门店。",
        "need_address_choice": "请陛下指定送膳之处。",
        "address_mismatch": "指定的地址与官方地址簿不符。",
        "need_store_query": "地址已定，臣正查询可配送门店。",
        "store_unavailable": "可配送门店未能确认。",
        "need_be_code": "可配送门店缺少 beCode，外送核价无法进行。",
        "ready": "外送链路已通，可查询外送菜单并核价。",
    }
    L.append(f"- 链路状态：{guidance.get(plan.get('status'), '未知状态')}")

    if plan.get("chosen_address"):
        a = plan["chosen_address"]
        L.append(f"- 送膳之处：{a.get('full_address') or '（官方未返回完整地址）'}"
                 f"（联系人 {a.get('contact_name') or '未知'}）")

    if plan.get("address_options"):
        for a in plan["address_options"]:
            L.append(f"  - [{a['index']}] {a.get('full_address')} "
                     f"｜addressId {a.get('address_id')}")

    if plan.get("stores"):
        for s in plan["stores"][:3]:
            L.append(f"- 可配送门店：**{s.get('name')}**（storeCode {s.get('store_code')}，"
                     f"beCode {s.get('be_code')}）")

    for b in plan.get("blockers", []):
        L.append(f"- ⚠️ {b}")
    for u in plan.get("unverified", []):
        L.append(f"- ⚠️ {u}")
    for n in plan.get("notes", []):
        L.append(f"- {n}")
    for g in plan.get("guidance", []):
        L.append(f"- {g}")

    if plan.get("required_fields"):
        L.append(f"- 待补字段：{'、'.join(plan['required_fields'])}"
                 "（须由陛下提供，臣不代为编造）")

    L.append("- 臣不会自动创建地址、自动下单或自动付款；"
             "以上任一写入操作均须陛下明示并确认。")
    return L


# ── 专有名词：只可改语气，不可改业态 ──────────────────────────────────
# 真实教训：门店曾被古风包装成「面馆」。麦当劳门店不是卖面的——
# 这不是文风问题，是把陛下指向了错误的地方。故立禁译词表，输出前必扫。
MISTRANSLATION_BANNED = (
    "面馆", "酒楼", "饭庄", "食肆", "大排档",
    "面铺", "粥铺", "包子铺", "粉面店",
)
MISTRANSLATION_ALLOW = ("门店", "餐厅", "麦乐送", "麦当劳", "麦咖啡")


def scan_mistranslation(text: str) -> dict:
    """禁译自检：命中即告警。古风只改语气，不改事实。"""
    hits = [w for w in MISTRANSLATION_BANNED if w in (text or "")]
    return {
        "passed": not hits,
        "hits": hits,
        "note": ("门店就是门店，不得翻成面馆等别的业态——"
                 "古风只改语气，不改地方。") if hits else None,
    }


def compliance_scan(text: str) -> dict:
    """合规自检：命中即告警。宁可少说，不可乱说。"""
    hits_fortune = [w for w in BANNED_FORTUNE_WORDS if w in text]
    hits_claim = [w for w in COMPLIANCE_BANNED if w in text]
    return {
        "passed": not hits_fortune and not hits_claim,
        "fortune_words": hits_fortune,
        "exaggerated_claims": hits_claim,
    }


def render_memorial(date_ctx: dict, theme: dict, candidates: dict,
                    coupons: dict | None, price: dict | None,
                    profile: dict | None, campaigns: dict | None = None,
                    delivery: dict | None = None,
                    available_coupons: dict | None = None,
                    meal_details: list | None = None,
                    claim_confirmed: bool = False,
                    extras: dict | None = None) -> str:
    """extras 可含三项，均为真实官方返回驱动，缺任一项就不渲染对应章节：
        store_coupons   —— query-store-coupons 的真实返回（本单可用券的唯一依据）
        coupon_verify   —— verify_coupon_price() 的结果（两次核价对比）
        claim_reconcile —— reconcile_claim_result() 的结果（领券对账）
    """
    """渲染「奏折」。只输出已核实内容，未核实项显式标注。

    meal_details：query-meal-detail 的真实返回列表（可混合原始返回与已适配结果），
    用于生成「御膳图鉴」。不传则不配图——绝不凭空造图。
    """
    L = []
    L.append("# 御膳房奏折")
    L.append("")
    L.append(f"**日期**：{date_ctx['date']} {date_ctx.get('weekday','')}"
             + ("（指定日期模拟，非当前真实日期）" if date_ctx.get("simulated") else ""))

    cn = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    sec = [0]

    def heading(title):
        L.append("")
        L.append(f"## {cn[sec[0]]}、{title}")
        sec[0] += 1

    # 麦历（原"黄历"叫法已弃用：黄历自带择吉避凶意味，易被读成用吉凶推着人花钱）
    heading("麦历呈报（观象授时·文化灵感）")
    term = date_ctx.get("solar_term")
    fest = date_ctx.get("festival")
    hol = date_ctx.get("legal_holiday")
    if term:
        L.append(f"- 节气：**{term['name']}**（交节时刻 {term.get('moment_cst') or '未返回'}）")
    if fest:
        L.append(f"- 传统节日：**{fest['name']}**")
    if hol:
        L.append(f"- 法定节假日：**{hol['name']}**（来源：{hol.get('source')}）")
    if not term and not fest and not hol:
        L.append("- 今日无节气与传统节日，按四时常态办理。")
    if date_ctx.get("degraded"):
        L.append(f"- ⚠️ {date_ctx.get('degraded_reason') or '日期数据不完整'}，已降级为主题灵感，未编造节气。")
    L.append(f"- 今日主题：**{theme['theme']}** —— {theme['tagline']}")
    L.append(f"- 今日宜（娱乐彩蛋）：{theme['auspicious_fun']}")
    L.append(f"- {theme['disclaimer']}")
    if theme.get("opted_out"):
        L.append("- 麦历主题已按陛下旨意关闭。")

    # 外送（麦乐送）专线：与到店自取互斥呈现，明确列出阻塞与未核实项
    if delivery is not None:
        heading("驿站传膳（麦乐送外送）")
        L.extend(render_delivery_section(delivery))

    # 官方真实活动（来自 campaign-calendar），与文化主题严格分列
    if campaigns is not None:
        heading("礼部呈报（麦当劳官方活动，非臣杜撰）")
        items = campaigns.get("items") or []
        if campaigns.get("ok") is False:
            L.append(f"- ⚠️ {campaigns.get('message')}")
        elif not items:
            L.append("- 官方活动日历本次未返回可展示的活动。")
        else:
            for c in items[:5]:
                L.append(f"- **{c.get('title')}**（{c.get('date', '')}）")
                if c.get("summary"):
                    L.append(f"  - {c['summary']}")
            L.append("- 以上为麦当劳官方活动日历返回内容，与上方节气主题无关，"
                     "臣未将二者混为一谈。")

    # 户部
    if coupons is not None:
        heading("户部精算")
        if not coupons.get("ok"):
            L.append(f"- ⚠️ {coupons.get('message')}")
        elif not coupons.get("plans"):
            L.append(f"- {coupons.get('message') or '本次未查得可用券令。'}")
        else:
            for i, p in enumerate(coupons["plans"], 1):
                tag = "符合预算" if p.get("within_budget") else "超出预算"
                L.append(f"- 候选{i}：**{p['name']}** 标价 {p['list_price']} 元（{tag}）")
                if p["coupons"]:
                    for c in p["coupons"]:
                        mark = "已核实" if c["verified"] else "⚠️ 条件未核实，以官方核价为准"
                        L.append(f"  - 券：{c['name']}｜{c['condition']}｜{mark}")
                else:
                    L.append("  - 该组合未匹配到可用券令")
        for w in coupons.get("warnings", []):
            L.append(f"- ⚠️ {w}")
        if coupons.get("note"):
            L.append(f"- {coupons['note']}")

    # 可领取券令（available-coupons）：与「本单可用券」严格区分，且臣不代领
    if available_coupons is not None:
        heading("户部呈报·可领券令")
        if not available_coupons.get("ok"):
            L.append(f"- ⚠️ {available_coupons.get('message')}")
        elif available_coupons.get("empty"):
            L.append(f"- {available_coupons.get('message')}")
        else:
            for c in available_coupons["coupons"]:
                L.append(f"- **{c.get('title')}**（状态：{c.get('status') or '未返回'}）")
            L.append(f"- {available_coupons['caveat']}")
            L.append("- ⚠️ 以上为「可领取」券令，**非本单可用券**。"
                     "本单能否使用须以官方核价与门店券校验为准。")
            # 代领券令：第二档写操作，须逐张复述并由陛下明示
            L.append("")
            L.append("**代领券令**")
            L.extend(render_coupon_claim_section(
                build_coupon_claim_plan(available_coupons, claim_confirmed)))

    # 本店可用券令：唯一能证明「本单可用」的依据
    if (extras or {}).get("store_coupons") is not None:
        sc = extras["store_coupons"]
        if isinstance(sc, dict) and "coupons" not in sc:
            sc = adapt_mcd_store_coupons(sc)
        heading("户部呈报·本店可用券令")
        if not sc.get("ok"):
            L.append(f"- ⚠️ {sc.get('message')}")
        elif sc.get("empty"):
            L.append(f"- {sc.get('message')}")
        else:
            for c in sc["coupons"]:
                L.append(f"- **{c['title']}**（有效期 {c.get('validity') or '未返回'}）")
                for p in c.get("products") or []:
                    L.append(f"  - 适用商品：{p.get('name')}（编码 {p.get('code')}）")
            if sc.get("note"):
                L.append(f"- {sc['note']}")
            L.append("- ⚠️ 券码属陛下私有资产，臣**不写入任何文件**；"
                     "核价须由调用方实时传入，臣不代存、不复用。")

    # 券效核验：两次官方核价对比，不自行推算减免
    if (extras or {}).get("coupon_verify") is not None:
        cv = extras["coupon_verify"]
        heading("券效核验（官方两次核价对比）")
        if not cv.get("ok"):
            L.append(f"- ⚠️ {cv.get('message')}")
        else:
            names = "、".join(filter(None, cv.get("product_names")))
            if names:
                L.append(f"- 核验组合：{names}")
            wc = cv.get("with_coupon_fen")
            if wc is not None:
                L.append(f"- 带券应付：**{_yuan(wc)} 元**")
            if cv.get("without_coupon_fen") is not None:
                L.append(f"- 不带券应付：{_yuan(cv['without_coupon_fen'])} 元")
            if cv.get("saving_fen") is not None:
                L.append(f"- **实省 {_yuan(cv['saving_fen'])} 元**"
                         "（官方两次核价之差，非臣推算）")
            if cv.get("message"):
                L.append(f"- {cv['message']}")
            for c in cv.get("caveats", []):
                L.append(f"- ⚠️ {c}")

    # 领券对账：领了几张 vs 卡包实有几张
    if (extras or {}).get("claim_reconcile") is not None:
        rc = extras["claim_reconcile"]
        heading("领券对账")
        if not rc.get("ok"):
            L.append(f"- ⚠️ {rc.get('message')}")
        else:
            L.append(f"- {rc['message']}")
            for m in rc.get("missing", []):
                L.append(f"  - ⚠️ 回报已领但卡包未见：**{m}**")
            for e in rc.get("extra", []):
                L.append(f"  - 卡包中有而本次未报：{e}")
            for c in rc.get("caveats", []):
                L.append(f"- ⚠️ {c}")

    # 御膳图鉴：先看菜，再谈价。图片必须来自官方详情接口。
    if meal_details:
        adapted = [d if (isinstance(d, dict) and "image" in d and "default_combo" in d)
                   else adapt_mcd_meal_detail(d) for d in meal_details]
        merged = attach_photos(candidates, adapted)
        gallery = render_photo_gallery(merged)
        heading("御膳图鉴（官方餐品图）")
        L.extend(gallery)
        # 只有真的配上图了，才需要解释「为什么只有前几道有图」
        if any("![" in line for line in gallery):
            if merged.get("photos_note"):
                L.append(f"- {merged['photos_note']}")
            L.append("- ⚠️ 菜单列表接口 `query-meals` 不返回图片；"
                     "以上每一张图均由 `query-meal-detail` 逐道取得，"
                     "因此只呈前几道，不为全部候选反复调接口。")

    # 御膳
    heading("太医献方（候选御膳）")
    # 口径一致性：外送链路未打通时，不得把到店菜单当成外送菜单呈现
    if delivery is not None and delivery.get("status") != "ready":
        L.append("- ⚠️ 外送链路尚未打通，以下餐品取自**到店自取口径**"
                 "（beType=1），其价格、可售范围与配送费均可能与麦乐送不同，"
                 "臣未能核实外送菜单，不敢以此充当外送报价。")
    if not candidates.get("ok"):
        L.append(f"- ⚠️ {candidates.get('message')}")
    else:
        if not candidates["candidates"]:
            L.append("- 臣未能从官方数据中筛选出合适餐品。")
        for i, c in enumerate(candidates["candidates"], 1):
            price_txt = (f"{fmt_money(c['price'], UNIT_YUAN)} 元"
                     if c["price"] is not None else "官方未返回价格")
            L.append(f"- **{c['name']}**｜{price_txt}")
            for r in c["reasons"]:
                L.append(f"  - {r}")
        if candidates.get("budget_max") is not None:
            fe = "可满足" if candidates.get("budget_feasible") else "**无法完全满足**"
            L.append(f"- 预算 {candidates['budget_max']} 元：{fe}")
            if not candidates.get("budget_feasible") and candidates.get("cheapest"):
                L.append(f"  - 当前官方数据中最低价为 "
                         f"「{candidates['cheapest']['name']}」"
                         f"{fmt_money(candidates['cheapest']['price'], UNIT_YUAN)} 元，"
                         f"仍高于陛下所定预算。臣不敢伪造符合预算之品。")
        for w in candidates.get("warnings", []):
            L.append(f"- ⚠️ {w}")
        if candidates.get("note"):
            L.append(f"- {candidates['note']}")

    # 账目
    if price is not None:
        heading("核对御膳账目")
        if delivery is not None and delivery.get("status") != "ready":
            L.append("- ⚠️ 该核价基于到店自取口径，不代表麦乐送外送应付金额"
                     "（外送含配送费，臣未能核实）。")
        if not price.get("ok"):
            L.append(f"- ⚠️ {price.get('message')}")
        else:
            for r in price["rows"]:
                if r["total"] is None:
                    L.append(f"- {r['name']}：**未取得官方核价**，不作推荐依据")
                else:
                    L.append(f"- {r['name']}：**{r['total']:.2f} 元**"
                             f"（{r['price_source']}）")
                    # 外送费用明细：只呈现官方确实返回的项，缺失不补
                    raw = r.get("raw") or {}
                    fee_labels = (("delivery_fen", "配送费"),
                                  ("packing_fen", "打包费"),
                                  ("tableware_fen", "餐具费"),
                                  ("product_fen", "餐品小计"))
                    for key, label in fee_labels:
                        if raw.get(key) is not None:
                            L.append(f"  - {label}：{_yuan(raw[key])} 元"
                                     "（官方核价返回）")
                    if raw.get("delivery_fen") is None and r["total"] is not None:
                        L.append("  - 官方本次未返回配送费字段，臣不预估。")
            for w in price.get("warnings", []):
                L.append(f"- ⚠️ {w}")
            if price.get("summary"):
                L.append(f"- {price['summary']}")

    # 旧例
    if profile is not None:
        heading("陛下旧例")
        L.append(describe_preference(profile))

    # 代下单：第三档写操作，须三重复述全部点头
    order_plan = (extras or {}).get("order_plan")
    if order_plan is not None:
        heading("拟旨下单（三重复述）")
        L.extend(render_order_section(order_plan))

    heading("奏请定夺")
    if order_plan is not None and order_plan.get("status") == "ready":
        L.append("- 三重复述已毕，臣可创建**待支付订单**；"
                 "订单创建后臣回传支付链接，**支付仍须陛下自行完成**。")
    else:
        L.append("- 以上均为**已查询、已核价、已推荐**，**未下单、未付款**。")
        L.append("- 请陛下自行前往麦当劳官方点餐渠道完成购买。")
    # 结尾不给开放式填空——陛下的每一个选择都应由调用方呈成选项卡片，点了即生效
    L.append("- **臣已备下选项，陛下点选即可**（换个更省的／换成新品／调整预算／"
             "查看某道膳品详情／按旧例重拟），不必自己打字。")

    text = "\n".join(L)
    # 合规自检只针对「主张性内容」，免责声明本身包含"保健/治疗"等否定式表述，须排除
    scan_text = "\n".join(
        line for line in L
        if not line.startswith("- 以上「麦历」主题为")
        and not line.startswith("- 以上为麦当劳官方活动日历")
    )
    scan = compliance_scan(scan_text)
    if not scan["passed"]:
        text += ("\n\n> ⚠️ 合规自检未通过："
                 + "；".join(filter(None, [
                     f"涉及运势/吉凶词：{scan['fortune_words']}" if scan["fortune_words"] else "",
                     f"涉及夸大表述：{scan['exaggerated_claims']}" if scan["exaggerated_claims"] else "",
                 ])))
    return text


# ===========================================================================
# CLI
# ===========================================================================

def _read_json_arg(value):
    if value is None:
        return None
    return json.loads(value) if value.strip().startswith(("{", "[")) else _load_json(value)


def _read_raw_arg(value):
    """按纯文本读取（available-coupons 官方返回的是文本而非 JSON）。"""
    if value is None:
        return None
    if os.path.exists(value):
        with open(value, "r", encoding="utf-8") as fh:
            return fh.read()
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="金拱门御膳房 · 本地规则引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("date-context", help="日期/节气/节日识别")
    p.add_argument("--date", help="YYYY-MM-DD，默认今日")
    p.add_argument("--simulate", action="store_true", help="标记为指定日期模拟")

    p = sub.add_parser("theme", help="当日主题")
    p.add_argument("--date", help="YYYY-MM-DD，默认今日")
    p.add_argument("--simulate", action="store_true")

    p = sub.add_parser("match", help="菜单筛选")
    p.add_argument("--menu", required=True)
    p.add_argument("--request", default=None)
    p.add_argument("--date", default=None)

    p = sub.add_parser("coupons", help="优惠候选筛选")
    p.add_argument("--coupons", required=True)
    p.add_argument("--candidates", required=True)
    p.add_argument("--request", default=None)

    p = sub.add_parser("verify-price", help="官方核价核验")
    p.add_argument("--verified", required=True)

    p = sub.add_parser("render", help="渲染奏折")
    p.add_argument("--date", default=None)
    p.add_argument("--menu", default=None)
    p.add_argument("--coupons", default=None)
    p.add_argument("--verified", default=None)
    p.add_argument("--campaigns", default=None)
    p.add_argument("--request", default=None)
    p.add_argument("--delivery", default=None, help="外送链路 plan JSON")
    p.add_argument("--available-coupons", default=None, help="available-coupons 返回")
    p.add_argument("--profile", default=None, help="偏好 JSON；省略则读取存档")
    p.add_argument("--meal-details", default=None,
                   help="query-meal-detail 返回数组（JSON 文件或 JSON 串）")
    p.add_argument("--order-plan", default=None,
                   help="代下单 plan JSON（build_order_plan 输出），用于渲染三重复述")

    p = sub.add_parser("meal-detail", help="解析 query-meal-detail 返回（含图片）")
    p.add_argument("--raw", required=True)
    p.add_argument("--show-modification", action="store_true",
                   help="展开特调项（默认不主动展开，遵从官方展示规则）")

    p = sub.add_parser("gallery", help="渲染御膳图鉴")
    p.add_argument("--candidates", required=True, help="match 输出的候选 JSON")
    p.add_argument("--details", required=True,
                   help="query-meal-detail 返回数组（JSON 文件或 JSON 串）")
    p.add_argument("--limit", type=int, default=PHOTO_DEFAULT_LIMIT)

    p = sub.add_parser("preference", help="陛下旧例：查看/存档/清除偏好")
    p.add_argument("--show", action="store_true")
    p.add_argument("--set", default=None, help="要合并的偏好 JSON")
    p.add_argument("--clear", default=None, help="要清除的字段，逗号分隔")
    p.add_argument("--clear-all", action="store_true")
    p.add_argument("--path", default=None, help="存档路径（测试用）")
    p.add_argument("--no-save", action="store_true", help="只在本会话内使用，不落盘")

    p = sub.add_parser("coupons-available", help="解析 available-coupons 返回")
    p.add_argument("--raw", required=True)

    p = sub.add_parser("store-coupons", help="解析 query-store-coupons 返回（本单可用券）")
    p.add_argument("--raw", required=True)

    p = sub.add_parser("verify-coupon-price", help="券效核验：两次官方核价对比")
    p.add_argument("--with-coupon", required=True)
    p.add_argument("--without-coupon", default=None,
                   help="不带券的同组合核价返回；省略则只报官方 discount")

    p = sub.add_parser("claim-reconcile", help="领券对账：领了几张 vs 卡包实有几张")
    p.add_argument("--claimed", required=True, help="券名列表 JSON 数组")
    p.add_argument("--wallet", required=True, help="卡包券名列表 JSON 数组")

    p = sub.add_parser("coupons-claim", help="编排代领券令（第二档写操作，须确认）")
    p.add_argument("--available", required=True, help="available-coupons 返回")
    p.add_argument("--confirmed", action="store_true",
                   help="陛下已明示确认；不加此参数则只生成待确认文案，绝不执行")

    p = sub.add_parser("order-plan", help="编排代下单（第三档写操作，须三重复述）")
    p.add_argument("--store", required=True,
                   help="门店 JSON：store_code/name/be_code/be_type/order_type/scene_name")
    p.add_argument("--items", required=True,
                   help="商品数组 JSON：product_code/name/quantity/coupon_title/modification_note")
    p.add_argument("--price", default=None, help="calculate-price 的官方返回")
    p.add_argument("--delivery", default=None,
                   help="交付方式 JSON：mode/address/address_id/take_way/take_way_code")
    p.add_argument("--confirmed", default=None,
                   help="陛下已确认的复述步骤，逗号分隔：content,amount,delivery")
    p.add_argument("--item-details", default=None,
                   help="各商品 query-meal-detail 返回数组，用于核对选配与必选口味")

    p = sub.add_parser("opening",
                       help="陛下上朝：问候 + 三问一卡（何膳 / 用度人数 / 传膳与送处）")
    p.add_argument("--single", action="store_true",
                   help="退回旧版：只呈「今日想用何膳」一问"
                        "（宿主不支持多问卡片时才用；正常一律用默认的三问一卡）")

    p = sub.add_parser("picks", help="产出结构化选项，供调用方呈成选项卡片（陛下点选）")
    p.add_argument("--stage", required=True,
                   help="opening / scene / budget / after_memorial / order_confirm / "
                        "ice / coupon / address / store_area")
    p.add_argument("--context", default=None,
                   help="上下文 JSON：candidates / pending / values / count / addresses")

    p = sub.add_parser("store-query", help="到店取餐：编排门店查询（官方不定位，须问陛下）")
    p.add_argument("--city", default=None, help="城市名，如 杭州")
    p.add_argument("--keyword", default=None, help="地段/地标关键词，如 西湖文化广场")
    p.add_argument("--be-type", type=int, default=1, help="1=到店自取，5=得来速")
    p.add_argument("--addresses", default=None,
                   help="delivery-query-addresses 的返回 JSON，用于反推城市与地段")

    p = sub.add_parser("store-list",
                       help="把 query-nearby-stores 的返回呈成可点选的门店清单（含官方距离）")
    p.add_argument("--stores", required=True,
                   help="query-nearby-stores 的返回 JSON")
    p.add_argument("--limit", type=int, default=5, help="最多展示几家")

    p = sub.add_parser("memorial-scroll", help="整篇御膳奏折卡片（HTML，带排版）")
    p.add_argument("--date", default=None, help="YYYY-MM-DD，默认今日")
    p.add_argument("--date-context", default=None, help="date-context 输出 JSON")
    p.add_argument("--theme", default=None, help="theme 输出 JSON")
    p.add_argument("--candidates", default=None,
                   help="attach_photos 后的候选 JSON（含官方图片）")
    p.add_argument("--coupons", default=None, help="券令 JSON")
    p.add_argument("--price", default=None, help="calculate-price 官方返回")
    p.add_argument("--campaigns", default=None, help="官方活动日历返回")
    p.add_argument("--delivery", default=None, help="外送链路 plan JSON")
    p.add_argument("--store", default=None, help="门店 JSON：name")
    p.add_argument("--order-plan", default=None, help="order-plan 输出 JSON")
    p.add_argument("--out", default=None, help="写出 HTML 文件路径；省略则打印")

    p = sub.add_parser("order-scroll", help="拟旨下单奏折卡片（HTML，一次性交付物）")
    p.add_argument("--plan", required=True, help="order-plan 输出的 JSON")
    p.add_argument("--photos", default=None,
                   help="attach_photos 后的候选数组（含官方图片地址）")
    p.add_argument("--date", default=None, help="YYYY-MM-DD，默认今日（仅取抬头日期）")
    p.add_argument("--date-context", default=None, help="date-context 输出 JSON")
    p.add_argument("--theme", default=None, help="theme 输出 JSON")
    p.add_argument("--store", default=None, help="门店 JSON：name")
    p.add_argument("--out", default=None, help="写出 HTML 文件路径；省略则打印到标准输出")

    p = sub.add_parser("order-checklist", help="下单前待定清单：选配轮次与必选口味")
    p.add_argument("--details", required=True,
                   help="query-meal-detail 返回数组（JSON 文件或 JSON 串）")

    p = sub.add_parser("scene", help="识别用餐场景")
    p.add_argument("--text", default="")
    p.add_argument("--explicit", default=None,
                   choices=list(SCENE_PRESETS.keys()))

    p = sub.add_parser("delivery", help="编排麦乐送外送链路")
    p.add_argument("--addresses", default=None, help="delivery-query-addresses 返回")
    p.add_argument("--stores", default=None, help="delivery-query-stores 返回")
    p.add_argument("--address-id", default=None)

    p = sub.add_parser("compliance", help="合规自检")
    p.add_argument("--text", required=True)

    args = ap.parse_args(argv)

    def target_date():
        return (datetime.strptime(args.date, "%Y-%m-%d").date()
                if getattr(args, "date", None) else today_cst())

    def simulated():
        return bool(getattr(args, "simulate", False)) or bool(getattr(args, "date", None))

    if args.cmd == "date-context":
        print(json.dumps(build_date_context(target_date(), simulated()),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "theme":
        ctx = build_date_context(target_date(), simulated())
        print(json.dumps({"date_context": ctx, "theme": build_theme(ctx)},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "match":
        menu = _read_json_arg(args.menu)
        req = _read_json_arg(args.request) or {}
        ctx = build_date_context(target_date() if getattr(args, "date", None) else today_cst(),
                                 simulated())
        theme = build_theme(ctx)
        print(json.dumps(build_candidates(menu, req, theme), ensure_ascii=False, indent=2))
    elif args.cmd == "coupons":
        print(json.dumps(optimize_coupons(_read_json_arg(args.coupons),
                                          _read_json_arg(args.candidates),
                                          _read_json_arg(args.request) or {}),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "verify-price":
        print(json.dumps(verify_price(_read_json_arg(args.verified)),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "render":
        ctx = build_date_context(target_date(), simulated())
        theme = build_theme(ctx)
        cands = build_candidates(_read_json_arg(args.menu) or {},
                                 _read_json_arg(args.request) or {}, theme) if args.menu else {
            "ok": False, "reason": "no_menu", "message": "未提供官方菜单，不敢妄拟御膳。",
            "candidates": [], "warnings": []}
        coup = optimize_coupons(_read_json_arg(args.coupons) or {},
                                cands.get("candidates", []),
                                _read_json_arg(args.request) or {}) if args.coupons else None
        pr = verify_price(_read_json_arg(args.verified)) if args.verified else None
        camp = _read_json_arg(args.campaigns) if args.campaigns else None
        dlv = _read_json_arg(args.delivery) if args.delivery else None
        avail = (adapt_mcd_available_coupons(_read_raw_arg(args.available_coupons))
                 if args.available_coupons else None)
        prof = _read_json_arg(args.profile) if args.profile else load_persisted_preference()
        mds = None
        if args.meal_details:
            mds = _read_json_arg(args.meal_details)
            if isinstance(mds, dict):
                mds = mds.get("details") or [mds]
        extras = None
        if args.order_plan:
            extras = {"order_plan": _read_json_arg(args.order_plan)}
        print(render_memorial(ctx, theme, cands, coup, pr, prof, camp, dlv, avail, mds,
                              None, False, extras))
    elif args.cmd == "preference":
        prof = load_persisted_preference(args.path) or dict(DEFAULT_PROFILE)
        if args.set:
            prof = merge_preference(prof, _read_json_arg(args.set))
        if args.clear:
            prof = merge_preference(prof, {"clear": [c.strip()
                                                     for c in args.clear.split(",")]})
        if args.clear_all:
            prof = merge_preference(prof, {"clear_all": True})
            clear_persisted_preference(args.path)
        elif args.set and not args.no_save:
            prof = save_preference(prof, args.path)
        print(json.dumps({"profile": prof,
                          "storage_path": args.path or preference_path()},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "coupons-available":
        print(json.dumps(adapt_mcd_available_coupons(_read_raw_arg(args.raw)),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "store-coupons":
        print(json.dumps(adapt_mcd_store_coupons(_read_json_arg(args.raw)),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "verify-coupon-price":
        print(json.dumps(verify_coupon_price(
            _read_json_arg(args.with_coupon),
            _read_json_arg(args.without_coupon) if args.without_coupon else None),
            ensure_ascii=False, indent=2))
    elif args.cmd == "claim-reconcile":
        print(json.dumps(reconcile_claim_result(_read_json_arg(args.claimed),
                                                _read_json_arg(args.wallet)),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "coupons-claim":
        plan = build_coupon_claim_plan(
            adapt_mcd_available_coupons(_read_raw_arg(args.available)),
            confirmed=args.confirmed)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print()
        print("\n".join(render_coupon_claim_section(plan)))
    elif args.cmd == "order-plan":
        confirmed = [s.strip() for s in args.confirmed.split(",")] if args.confirmed else None
        dets = None
        if args.item_details:
            dets = _read_json_arg(args.item_details)
            if isinstance(dets, dict):
                dets = dets.get("details") or [dets]
        plan = build_order_plan(_read_json_arg(args.store),
                                _read_json_arg(args.items),
                                _read_json_arg(args.price) if args.price else None,
                                _read_json_arg(args.delivery) if args.delivery else None,
                                confirmed, dets)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print()
        print("\n".join(render_order_section(plan)))
    elif args.cmd == "opening":
        if args.single:
            op = render_opening()
            print(json.dumps(op, ensure_ascii=False, indent=2))
            print()
            print(PICK_RENDER_BANNER)
            print(f"- {op['greeting']}")
            for i, o in enumerate(op["options"], 1):
                mark = "（固定）" if o["label"] in OPENING_REQUIRED else ""
                print(f"  {i}. {o['label']}{mark}　{o['description']}")
            print(f"- {op['note']}")
        else:
            b = render_opening_bundle()
            print(json.dumps(b, ensure_ascii=False, indent=2))
            print()
            print(PICK_RENDER_BANNER)
            print(f"- {b['greeting']}")
            for n, q in enumerate(b["questions"], 1):
                print(f"  {n}. [{q['header']}] {q['question']}")
                for o in q["options"]:
                    mark = "（固定）" if o["label"] in OPENING_REQUIRED else ""
                    print(f"     - {o['label']}{mark}　{o['description']}")
            print(f"- {b['note']}")
    elif args.cmd == "picks":
        ctx = _read_json_arg(args.context) if args.context else {}
        if not isinstance(ctx, dict):
            ctx = {}
        picks = suggest_picks(args.stage, **ctx)
        print(json.dumps(picks, ensure_ascii=False, indent=2))
        print()
        print(PICK_RENDER_BANNER)
        print(f"- {picks['question']}（臣已备选项，陛下点选即可）")
        for o in picks["options"]:
            print(f"  - {o['label']}　{o['description']}")
    elif args.cmd == "store-query":
        addrs = _read_json_arg(args.addresses) if args.addresses else None
        req = build_store_request(args.city, args.keyword, args.be_type,
                                  addresses=addrs)
        print(json.dumps(req, ensure_ascii=False, indent=2))
        print()
        if req["status"] == "ready":
            print(f"- 臣可按此查询：{STORE_SEARCH_TOOL}"
                  f"（{req['be_type_name']}，按位置搜索）")
            print(f"- 参数：{json.dumps(req['params'], ensure_ascii=False)}")
        elif req["status"] == "need_confirm":
            lvl = {"street": "街道门牌", "landmark": "地标",
                   "district": "区县（偏粗）", "city": "城市（几乎无效）"}.get(
                       req.get("keyword_level"), "未知")
            print(f"- 关键词精度：{lvl}　city={req['city']}　keyword={req['keyword']}")
            print(f"- {req['message']}")
            print(f"- {req['ask']['question']}（{req['ask']['note']}）")
            for o in req["ask"]["picks"]["options"]:
                print(f"  - {o['label']}　{o['description']}")
        else:
            ask = req["ask"]
            print(f"- ⚠️ {req['message']}")
            print(f"- {ask['question']}（{ask['note']}）")
            for f in ask["fields"]:
                print(f"  - {f['label']}（{f['key']}）：如「{f['example']}」")
        print(f"- {req['caveat']}")
        print(f"- {req['ip_geo_note']}")
    elif args.cmd == "store-list":
        raw = _read_json_arg(args.stores)
        adapted = adapt_mcd_nearby_stores(raw)
        print(render_store_list(adapted, limit=args.limit))
        verdict = assess_nearby_result(adapted)
        print(f"- {verdict['advice']}")
    elif args.cmd == "memorial-scroll":
        if args.date_context:
            dctx = _read_json_arg(args.date_context)
        elif args.date:
            dctx = build_date_context(
                datetime.strptime(args.date, "%Y-%m-%d").date(),
                simulated=True)
        else:
            dctx = build_date_context(today_cst())
        theme = (_read_json_arg(args.theme) if args.theme
                 else build_theme(dctx))
        cands = _read_json_arg(args.candidates) if args.candidates else {}
        if isinstance(cands, list):
            cands = {"ok": True, "candidates": cands}
        html = render_memorial_scroll(
            dctx, theme, cands,
            _read_json_arg(args.coupons) if args.coupons else None,
            _read_json_arg(args.price) if args.price else None,
            _read_json_arg(args.campaigns) if args.campaigns else None,
            _read_json_arg(args.delivery) if args.delivery else None,
            _read_json_arg(args.store) if args.store else None,
            _read_json_arg(args.order_plan) if args.order_plan else None)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"御膳奏折已誊写：{args.out}")
        else:
            print(html)
    elif args.cmd == "order-scroll":
        plan = _read_json_arg(args.plan)
        photos = None
        if args.photos:
            ph = _read_json_arg(args.photos)
            if isinstance(ph, dict):
                ph = ph.get("candidates") or ph.get("details") or []
            photos = ph if isinstance(ph, list) else None
        if args.date_context:
            dctx = _read_json_arg(args.date_context)
        elif args.date:
            dctx = build_date_context(
                datetime.strptime(args.date, "%Y-%m-%d").date(),
                simulated=True)
        else:
            dctx = build_date_context(today_cst())
        theme = _read_json_arg(args.theme) if args.theme else None
        store = _read_json_arg(args.store) if args.store else None
        html = render_order_scroll(plan, theme, dctx, photos, store)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"奏折卡片已誊写：{args.out}")
        else:
            print(html)
    elif args.cmd == "order-checklist":
        dets = _read_json_arg(args.details)
        if isinstance(dets, dict):
            dets = dets.get("details") or [dets]
        cl = build_pending_checklist(dets)
        print(json.dumps(cl, ensure_ascii=False, indent=2))
        print()
        print("\n".join(render_pending_checklist(cl)))
    elif args.cmd == "scene":
        print(json.dumps(detect_scene(args.text, args.explicit),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "meal-detail":
        d = adapt_mcd_meal_detail(_read_json_arg(args.raw))
        print(json.dumps(d, ensure_ascii=False, indent=2))
        print()
        print("\n".join(render_meal_detail_card(d, args.show_modification)))
    elif args.cmd == "gallery":
        cands = _read_json_arg(args.candidates) or {}
        dets = _read_json_arg(args.details)
        if isinstance(dets, dict):
            dets = dets.get("details") or [dets]
        adapted = [d if (isinstance(d, dict) and "default_combo" in d)
                   else adapt_mcd_meal_detail(d) for d in dets or []]
        merged = attach_photos(cands, adapted)
        print("\n".join(render_photo_gallery(merged, args.limit)))
        if merged.get("photos_note"):
            print(f"- {merged['photos_note']}")
    elif args.cmd == "delivery":
        addr = adapt_mcd_addresses(_read_json_arg(args.addresses)) if args.addresses else None
        st = adapt_mcd_delivery_stores(_read_json_arg(args.stores)) if args.stores else None
        print(json.dumps(build_delivery_plan(addr, st, args.address_id),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "compliance":
        print(json.dumps(compliance_scan(args.text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
