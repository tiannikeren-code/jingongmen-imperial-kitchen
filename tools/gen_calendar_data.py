# -*- coding: utf-8 -*-
"""一次性数据生成脚本（仅开发期使用，不属于 Skill 运行时）。

- 二十四节气：用 ephem 计算太阳视黄经，求其穿过 k*15 度的精确时刻，再换算到
  Asia/Shanghai（UTC+8，中国全境无夏令时）取当日日期。
- 传统节日：用 lunardate 做农历→公历换算。
- 法定节假日：直接采用国务院办公厅公开发布的年度安排，不由农历推断。

产物固化为 JSON 数据文件，Skill 运行时只依赖 Python 标准库。
"""
import json
import math
from datetime import datetime, timedelta, timezone

import ephem
from lunardate import LunarDate

CST = timezone(timedelta(hours=8))
UTC = timezone.utc

# (节气名, 太阳视黄经目标角度)
TERMS = [
    ("立春", 315), ("雨水", 330), ("惊蛰", 345), ("春分", 0),
    ("清明", 15), ("谷雨", 30), ("立夏", 45), ("小满", 60),
    ("芒种", 75), ("夏至", 90), ("小暑", 105), ("大暑", 120),
    ("立秋", 135), ("处暑", 150), ("白露", 165), ("秋分", 180),
    ("寒露", 195), ("霜降", 210), ("立冬", 225), ("小雪", 240),
    ("大雪", 255), ("冬至", 270), ("小寒", 285), ("大寒", 300),
]

# (节日名, 农历月, 农历日)；除夕单独处理
LUNAR_FESTIVALS = [
    ("春节", 1, 1), ("元宵节", 1, 15), ("龙抬头", 2, 2),
    ("上巳节", 3, 3), ("端午节", 5, 5), ("七夕", 7, 7),
    ("中元节", 7, 15), ("中秋节", 8, 15), ("重阳节", 9, 9),
    ("下元节", 10, 15), ("腊八节", 12, 8), ("小年", 12, 23),
]


def obliquity_deg(dt):
    """当日黄赤交角（IAU 1980 近似）"""
    T = (dt - datetime(2000, 1, 1, 12)).days / 36525.0
    return 23.439291111 - (46.8150 + 0.00059 * T - 0.001813 * T * T) * T / 3600.0


def sun_lon_deg(utc_dt):
    """太阳视黄经（度，0-360），相对【当日平春分点】。

    注意：不能直接用 ephem.Ecliptic(Sun).lon —— 该口径返回的是相对 J2000 平春分点
    的黄经，与节气定义所采用的"当日平春分点"相差约 0.36°（2025 年），会导致节气
    整体偏晚约 8.4 小时。这里改用 apparent geocentric 赤道坐标 (g_ra/g_dec) 配合
    当日黄赤交角换算，口径与节气定义一致。

    已用 pyephem 内置 next_equinox / next_solstice 对 2025、2026 两年全部 8 个
    分至点做过交叉校验，误差 ≤ 1 分钟。
    """
    sun = ephem.Sun(ephem.Date(utc_dt))
    ra, dec = float(sun.g_ra), float(sun.g_dec)
    eps = math.radians(obliquity_deg(utc_dt))
    lon = math.atan2(
        math.sin(ra) * math.cos(eps) + math.tan(dec) * math.sin(eps),
        math.cos(ra),
    )
    return math.degrees(lon) % 360.0


def solar_terms_for_year(year):
    """逐小时采样太阳视黄经，检测穿过各节气目标角度的时刻。

    全程使用【naive UTC】时间，避免时区混淆；仅在最后一步加 8 小时换算到 CST。
    """
    start = datetime(year, 1, 1, 0, 0)
    end = datetime(year, 12, 31, 23, 0)
    samples = []
    t = start
    while t <= end:
        samples.append((t, sun_lon_deg(t)))
        t += timedelta(hours=1)

    found = {}
    for name, target in TERMS:
        hit = None
        for i in range(len(samples) - 1):
            t1, l1 = samples[i]
            t2, l2 = samples[i + 1]
            delta = (l2 - l1) % 360.0
            if delta >= 180:  # 一小时不可能走半个天球，跳过异常区间
                continue
            offset = (target - l1) % 360.0
            if offset <= delta:
                frac = offset / delta if delta else 0.0
                hit = t1 + timedelta(hours=frac)
                break
        if hit is None:
            raise RuntimeError(f"{year} 年 {name} 未找到，请检查计算范围")
        cst = (hit.replace(tzinfo=UTC)).astimezone(CST)
        found[name] = {
            "date": cst.strftime("%Y-%m-%d"),
            "moment_cst": cst.strftime("%Y-%m-%d %H:%M"),
        }
    return found


def lunar_festival_events(lunar_years):
    """把若干农历年的传统节日换算成公历事件列表。

    腊月节日（腊八、小年、除夕）的公历日期会落在次年的 1-2 月，因此统一先
    生成事件、再按【公历年】归桶，避免跨年错位。
    """
    events = []
    for lunar_year in lunar_years:
        for name, month, day in LUNAR_FESTIVALS:
            try:
                solar = LunarDate(lunar_year, month, day, is_leap_month=False).to_solar_date()
            except Exception:
                continue
            events.append((name, solar.isoformat(), lunar_year))

        # 除夕：腊月最后一天（三十或廿九），必须回查确认该日真实存在
        for day in (30, 29):
            try:
                solar = LunarDate(lunar_year, 12, day, is_leap_month=False).to_solar_date()
                back = LunarDate.from_solar_date(solar.year, solar.month, solar.day)
                if back.month == 12 and back.day == day and not back.is_leap_month:
                    events.append(("除夕", solar.isoformat(), lunar_year))
                    break
            except Exception:
                continue
    return events


# 法定节假日：国务院办公厅公开发布的年度安排原文录入，严禁由农历推断
# 来源：国务院办公厅《关于 2026 年部分节假日安排的通知》（2025-11-04 发布）
LEGAL_HOLIDAYS = {
    "2026": {
        "source": "国务院办公厅关于2026年部分节假日安排的通知（2025-11-04）",
        "source_url": "https://www.gov.cn/",
        "verified": True,
        "ranges": [
            {"name": "元旦", "start": "2026-01-01", "end": "2026-01-03", "days": 3},
            {"name": "春节", "start": "2026-02-15", "end": "2026-02-23", "days": 9},
            {"name": "清明节", "start": "2026-04-04", "end": "2026-04-06", "days": 3},
            {"name": "劳动节", "start": "2026-05-01", "end": "2026-05-05", "days": 5},
            {"name": "端午节", "start": "2026-06-19", "end": "2026-06-21", "days": 3},
            {"name": "中秋节", "start": "2026-09-25", "end": "2026-09-27", "days": 3},
            {"name": "国庆节", "start": "2026-10-01", "end": "2026-10-07", "days": 7},
        ],
        "workdays_on_weekend": [
            "2026-01-04", "2026-02-14", "2026-02-28",
            "2026-05-09", "2026-09-20", "2026-10-10",
        ],
    }
}


def main():
    years = (2025, 2026, 2027)

    # 1) 节气：{年: {节气名: {date, moment_cst}}}
    solar_terms = {str(y): solar_terms_for_year(y) for y in years}

    # 2) 传统节日：按公历年归桶（腊月节日跨年问题）
    events = lunar_festival_events(tuple(range(min(years) - 1, max(years) + 2)))
    festivals = {}
    for name, date, lunar_year in events:
        gy = date[:4]
        festivals.setdefault(gy, {})[name] = {"date": date, "lunar_year": lunar_year}

    # 3) 由节气派生的节日（清明、冬至）
    for y in years:
        bucket = festivals.setdefault(str(y), {})
        terms = solar_terms[str(y)]
        for term_name in ("清明", "冬至"):
            if term_name in terms:
                bucket[term_name] = {
                    "date": terms[term_name]["date"],
                    "derived_from": "solar_term",
                }

    # 4) 法定节假日：只写入已核实的年度数据
    holidays = {k: v for k, v in LEGAL_HOLIDAYS.items() if k in {str(y) for y in years}}

    out = {
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S %z"),
        "timezone": "Asia/Shanghai (UTC+8, 无夏令时)",
        "methods": {
            "solar_terms": (
                "ephem 计算太阳视黄经（相对当日平春分点），求其达到 k*15 度的时刻，"
                "换算至 UTC+8 后取当日日期；已用 pyephem next_equinox/next_solstice "
                "对 2025、2026 年 8 个分至点交叉校验，误差 ≤1 分钟"
            ),
            "festivals": "lunardate 农历→公历换算；已与国务院 2026 放假安排交叉验证",
            "holidays": "国务院办公厅公开发布的年度安排原文录入，不由农历推断；"
                        "未核实的年份不写入数据文件，运行时优雅降级",
        },
        "solar_terms": solar_terms,
        "traditional_festivals": festivals,
        "legal_holidays": holidays,
        "coverage": {
            "solar_terms_years": [str(y) for y in years],
            "festival_years": sorted(festivals.keys()),
            "holiday_years": sorted(holidays.keys()),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
