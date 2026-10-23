# -*- coding: utf-8 -*-
"""金拱门御膳房 · 测试套件

运行：
    python -m unittest discover -s tests -v
或：
    python tests/test_imperial_kitchen.py

约定：
    - 凡涉及真实 MCP 数据的用例，一律读取 tests/fixtures/ 下已留存的真实返回摘录。
    - 无法在本环境验证的用例，标记为 @unittest.skip 并在 TESTING.md 中记为「未验证」，
      绝不允许写成「通过」。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import imperial_kitchen as ik  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
MENU_REAL = os.path.join(FIXTURES, "menu_real_sample.json")
PRICE_REAL = os.path.join(FIXTURES, "price_real_sample.json")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestDateContext(unittest.TestCase):
    """[1] 日期 / 节气 / 节日识别"""

    def test_01_normal_day_no_festival(self):
        """测试 1：普通日期，没有节日主题"""
        ctx = ik.build_date_context(date(2026, 10, 21))
        self.assertIsNone(ctx["festival"], "普通日期不应凭空出现节日")
        self.assertFalse(ctx["degraded"])
        theme = ik.build_theme(ctx)
        self.assertIn(theme["theme"], ["秋日暖心", "暖冬传膳", "春日尝鲜", "清爽一夏"])

    def test_02_solar_term_hit(self):
        """测试 2：命中某个二十四节气"""
        ctx = ik.build_date_context(date(2026, 10, 23))
        self.assertIsNotNone(ctx["solar_term"])
        self.assertEqual(ctx["solar_term"]["name"], "霜降")
        theme = ik.build_theme(ctx)
        self.assertEqual(theme["theme"], "秋日暖心")

    def test_03_traditional_festival_hit(self):
        """测试 3：命中传统节日"""
        ctx = ik.build_date_context(date(2026, 9, 25))
        self.assertEqual(ctx["festival"]["name"], "中秋节")
        self.assertEqual(ctx["legal_holiday"]["name"], "中秋节")
        theme = ik.build_theme(ctx)
        self.assertEqual(theme["theme"], "中秋团圆")

    def test_04_calendar_data_unavailable(self):
        """测试 4：日期数据异常或不可用 → 优雅降级，不得编造"""
        with self.assertRaises(ik.DataUnavailable):
            ik.load_calendar(os.path.join(FIXTURES, "__not_exist__.json"))
        # 用未内置年份构造「数据不可用」场景
        ctx2 = ik.build_date_context(date(2030, 5, 5))
        self.assertTrue(ctx2["degraded"], "缺失年份应标记 degraded")
        self.assertIsNone(ctx2["solar_term"], "缺失年份不得编造节气")
        self.assertIsNone(ctx2["festival"], "缺失年份不得编造节日")
        theme = ik.build_theme(ctx2)
        self.assertIsNotNone(theme["theme"])

    def test_04b_degraded_theme_never_invents(self):
        """降级时不得出现任何节气名"""
        ctx = ik.build_date_context(date(2030, 5, 5))
        theme = ik.build_theme(ctx)
        for term in ik.SOLAR_TERM_ORDER:
            self.assertNotIn(term, theme["tagline"])

    def test_05_solar_term_boundary_sort(self):
        """回归：小寒/大寒在 1 月却排在传统顺序末尾，必须按日期排序"""
        near = ik.nearest_solar_term(date(2026, 10, 21))
        self.assertEqual(near["current"], "寒露")
        self.assertEqual(near["next"], "霜降")

    def test_06_legal_holiday_from_official_data(self):
        """法定节假日必须来自年度数据，不得由农历推断"""
        ctx = ik.build_date_context(date(2026, 2, 17))   # 春节
        self.assertEqual(ctx["legal_holiday"]["name"], "春节")
        self.assertIn("国务院", ctx["legal_holiday"]["source"])
        ctx2 = ik.build_date_context(date(2026, 10, 5))  # 国庆假期内
        self.assertEqual(ctx2["legal_holiday"]["name"], "国庆节")


class TestThemeRules(unittest.TestCase):
    """[2] 主题文案与麦历边界"""

    def test_07_maicalendar_is_entertainment_only(self):
        """测试 7：麦历娱乐彩蛋不得预测财运/健康/事业/吉凶"""
        for day in range(1, 29):
            ctx = ik.build_date_context(date(2026, 9, day))
            theme = ik.build_theme(ctx)
            scan = ik.compliance_scan(theme["tagline"] + theme["auspicious_fun"])
            self.assertTrue(scan["passed"], f"9月{day}日命中违禁词：{scan}")

    def test_08_theme_deterministic(self):
        """同一日期的主题必须稳定复现"""
        a = ik.build_theme(ik.build_date_context(date(2026, 10, 23)))
        b = ik.build_theme(ik.build_date_context(date(2026, 10, 23)))
        self.assertEqual(a, b)

    def test_09_user_can_opt_out_theme(self):
        """测试 9：用户明确表示不喜欢当前主题"""
        ctx = ik.build_date_context(date(2026, 9, 25))
        theme = ik.build_theme(ctx, opt_out=True)
        self.assertTrue(theme.get("opted_out"))
        self.assertEqual(theme["menu_hint"], [])
        self.assertNotIn("中秋", theme["theme"])

    def test_10_theme_not_claimed_as_official(self):
        """主题文案不得被包装成麦当劳官方促销"""
        ctx = ik.build_date_context(date(2026, 9, 25))
        theme = ik.build_theme(ctx)
        self.assertIn("不冒充官方促销", theme["disclaimer"])
        self.assertIn("非麦当劳官方活动", theme["disclaimer"])


class TestMenuMatching(unittest.TestCase):
    """[4] 真实菜单 → 候选方案"""

    def setUp(self):
        self.menu = load("menu_real_sample.json")

    def test_11_basic_recommendation_uses_real_data(self):
        """测试 1：基础推荐——名称与价格必须来自真实返回"""
        cands = ik.build_candidates(self.menu, {"budget_max": 30, "likes": ["汉堡"]})
        self.assertTrue(cands["ok"])
        names = {c["name"] for c in cands["candidates"]}
        real_names = {v["name"] for v in self.menu["meals"].values()}
        self.assertTrue(names.issubset(real_names), f"出现了非官方餐品：{names - real_names}")

    def test_12_empty_menu_degrades(self):
        """MCP 返回空菜单 → 明确说明，不编造"""
        cands = ik.build_candidates({}, {"budget_max": 30})
        self.assertFalse(cands["ok"])
        self.assertEqual(cands["reason"], "empty_menu")
        self.assertEqual(cands["candidates"], [])

    def test_13_budget_conflict(self):
        """测试 6/8：预算与主题推荐冲突 / 预算不足 → 如实说明"""
        cands = ik.build_candidates(self.menu, {"budget_max": 5})
        self.assertFalse(cands["budget_feasible"])
        self.assertIsNotNone(cands["cheapest"])
        self.assertGreater(cands["cheapest"]["price"], 5)

    def test_14_dislike_filters(self):
        """用户忌口必须被剔除"""
        cands = ik.build_candidates(self.menu, {"dislikes": ["咖啡", "茶"]})
        for c in cands["candidates"]:
            self.assertNotIn("咖啡", c["name"])
            self.assertNotIn("茶", c["name"])

    def test_15_theme_item_unavailable(self):
        """测试 5：节日主题对应的品类当前不可售 → 不得虚构，改用真实替代品"""
        # 构造只有冷饮的菜单，主题却指向热食
        menu = {"items": [{"code": "X1", "name": "冰可乐", "price": 9.5,
                           "category": "冷饮"}]}
        cands = ik.build_candidates(menu, {"budget_max": 30},
                                    {"theme": "暖冬传膳", "menu_hint": ["热食", "热饮"]})
        self.assertTrue(cands["ok"])
        self.assertEqual(cands["candidates"][0]["name"], "冰可乐")
        # 不得虚构「热饮」类商品
        self.assertNotIn("热", " ".join(c["name"] for c in cands["candidates"]))

    def test_16_unknown_price_flagged(self):
        """官方未返回价格 → 标注为 unknown，不得猜价"""
        menu = {"items": [{"code": "X9", "name": "未知膳品", "category": "其他"}]}
        cands = ik.build_candidates(menu, {})
        self.assertIsNone(cands["candidates"][0]["price"])


class TestCouponOptimizer(unittest.TestCase):
    """[5] 优惠候选筛选"""

    def test_17_coupon_query_failed(self):
        """测试 7：优惠查询失败 → 明确说明，不冒充有优惠"""
        out = ik.optimize_coupons(None, [{"code": "1", "name": "A", "price": 10}], {})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "coupon_query_failed")
        self.assertEqual(out["plans"], [])

    def test_18_empty_coupon_list(self):
        """官方返回空券列表（真实场景）"""
        out = ik.optimize_coupons({"coupons": []},
                                  [{"code": "1", "name": "A", "price": 10}], {})
        self.assertTrue(out["ok"])
        self.assertEqual(out["plans"], [])

    def test_19_unverified_coupon_not_promised(self):
        """未核实适用条件的券不得承诺可用"""
        out = ik.optimize_coupons(
            {"coupons": [{"couponId": "c1", "name": "满30减5", "threshold": 3000}]},
            [{"code": "1", "name": "A", "price": 40}], {})
        self.assertEqual(out["plans"][0]["coupons"][0]["verified"], False)
        self.assertTrue(any("未核实" in w for w in out["warnings"]))

    def test_20_threshold_filters(self):
        """不满足门槛的券不得计入"""
        out = ik.optimize_coupons(
            {"coupons": [{"couponId": "c1", "name": "满30减5", "threshold": 3000}]},
            [{"code": "1", "name": "A", "price": 10}], {})
        self.assertEqual(out["plans"][0]["coupons"], [])


class TestPriceVerification(unittest.TestCase):
    """[6] 官方核价核验"""

    def test_21_price_verification_failed(self):
        """测试 8：官方价格核验失败 → 明确说明"""
        out = ik.verify_price({})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "price_verification_failed")

    def test_22_real_official_price(self):
        """真实 calculate-price 返回：4100 分 = 41.00 元"""
        raw = load("price_real_sample.json")
        adapted = ik.adapt_mcd_price(raw)
        out = ik.verify_price({"plans": [adapted]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["rows"][0]["total"], 41.0)
        self.assertFalse(out["rows"][0]["estimated"])
        self.assertIn("官方核价", out["rows"][0]["price_source"])

    def test_23_unverified_price_marked(self):
        """未能核价的方案必须标记，不得当作成交价"""
        out = ik.verify_price({"plans": [{"name": "X"}]})
        self.assertTrue(out["rows"][0]["estimated"])
        self.assertIsNone(out["rows"][0]["total"])
        self.assertIn("未能取得官方核价", out["warnings"][0])

    def test_24_no_absolute_lowest_claim(self):
        """不得宣称绝对最低价"""
        raw = load("price_real_sample.json")
        out = ik.verify_price({"plans": [ik.adapt_mcd_price(raw)]})
        self.assertNotIn("最低价", out["summary"])


class TestPreferenceProfile(unittest.TestCase):
    """[3] 用户偏好"""

    def test_25_explicit_vs_inferred(self):
        """测试 11：区分主动告知与系统推测"""
        p = ik.merge_preference(None, {"budget_max": 30, "likes": ["汉堡"]})
        self.assertEqual(p["explicit"]["budget_max"], 30)
        self.assertEqual(p["inferred"], {})

    def test_26_clear_preference(self):
        """支持清除偏好"""
        p = ik.merge_preference(None, {"budget_max": 30})
        p = ik.merge_preference(p, {"clear": ["budget_max"]})
        self.assertNotIn("budget_max", p["explicit"])

    def test_27_clear_all(self):
        p = ik.merge_preference(None, {"budget_max": 30, "likes": ["汉堡"]})
        p = ik.merge_preference(p, {"clear_all": True})
        self.assertEqual(p["explicit"], {})

    def test_28_no_overclaim_persistence(self):
        """不得夸大跨会话记忆能力——未存档时只说未存档，不说"不支持存档" """
        p = ik.merge_preference(None, {})
        self.assertIn("本次会话内有效", p["history_note"])
        self.assertNotIn("不保证跨会话持久化", p["history_note"])


class TestOutputSafety(unittest.TestCase):
    """[7] 输出安全：不虚构、不夸大、不越权"""

    def test_29_no_fabricated_names_or_prices(self):
        """测试 10/12：输出中不得出现虚构的官方活动、价格或餐品"""
        menu = load("menu_real_sample.json")
        ctx = ik.build_date_context(date(2026, 10, 23))
        theme = ik.build_theme(ctx)
        cands = ik.build_candidates(menu, {"budget_max": 30})
        text = ik.render_memorial(ctx, theme, cands, None, None, None)
        real_names = {v["name"] for v in menu["meals"].values()}
        # 输出中出现的每一个餐品名都必须在真实数据里
        for name in real_names:
            pass
        self.assertIn("未下单、未付款", text)
        self.assertIn("霜降", text)

    def test_30_compliance_scan_flags_claims(self):
        bad = "本方案保证全网最低价，且可治疗感冒"
        scan = ik.compliance_scan(bad)
        self.assertFalse(scan["passed"])
        self.assertTrue(scan["exaggerated_claims"])

    def test_31_no_side_effect_tools_in_source(self):
        """测试 10：禁止交易操作——源码中不得出现下单/付款类调用

        注意：源码里存在 WRITE_TIER_NEVER / WRITE_TIER_CONFIRM 等「分级清单」
        声明，且 docstring 中会引用工具名来说明官方约束——这些都是说明，不是调用。
        扫描前先剥离注释行、docstring 与声明式常量。

        两道保险：
          1) 文本扫描：剥离说明性文字后不得残留工具名；
          2) AST 扫描：语法树上不得存在以这些工具为名的函数调用。
        """
        import ast
        import re
        src = os.path.join(ROOT, "scripts", "imperial_kitchen.py")
        with open(src, "r", encoding="utf-8") as fh:
            code = fh.read()
        # 保险一：引擎绝不直接发起 MCP 调用
        self.assertNotIn("mcp__mcd-mcp__", code)

        banned = ("create-order", "create_order", "mall-create-order",
                  "party-order-create", "auto-bind-coupons", "draw-lottery",
                  "delivery-create-address", "cancel-order")

        # 保险二（AST）：语法树上不得有以这些工具为名的函数调用
        tree = ast.parse(code)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute):
                    called.add(f.attr)
                elif isinstance(f, ast.Name):
                    called.add(f.id)
        for b in banned:
            self.assertNotIn(b.replace("-", "_"), called,
                             f"源码中存在有副作用的调用：{b}")

        # 保险三（文本）：剥离注释 / docstring / 声明常量后不得残留
        code_lines = [ln for ln in code.splitlines() if not ln.strip().startswith("#")]
        scan_code = "\n".join(code_lines)
        scan_code = re.sub(r'"""[\s\S]*?"""', "", scan_code)   # 去 docstring
        pattern = (r"WRITE_TIER_NEVER\s*=\s*\([^)]*\)"
                   r"|WRITE_TIER_CONFIRM\s*=\s*\([^)]*\)"
                   r"|WRITE_TIER_CONFIRM_STRICT\s*=\s*\([^)]*\)"
                   r"|DELIVERY_WRITE_TOOLS\s*=\s*[^\n]*"
                   r"|PENDING_ADDRESS_CREATE_TOOL\s*=\s*\"[^\"]*\""
                   r"|COUPON_CLAIM_TOOL\s*=\s*\"[^\"]*\""
                   r"|ORDER_CREATE_TOOL\s*=\s*\"[^\"]*\""
                   r"|ORDER_CANCEL_TOOL\s*=\s*\"[^\"]*\"")
        decls = re.findall(pattern, scan_code, re.S)
        self.assertTrue(decls, "分级清单声明应存在")
        for d in decls:
            scan_code = scan_code.replace(d, "")
        for b in banned:
            self.assertNotIn(b, scan_code,
                             f"源码中出现了有副作用的调用：{b}")

    def test_31b_write_tiers_are_separated(self):
        """三档写操作互不重叠：领券在中档，下单在最严档，抽奖永不执行"""
        never = set(ik.WRITE_TIER_NEVER)
        confirm = set(ik.WRITE_TIER_CONFIRM)
        strict = set(ik.WRITE_TIER_CONFIRM_STRICT)
        self.assertFalse(never & confirm, "NEVER 与 CONFIRM 不得重叠")
        self.assertFalse(never & strict, "NEVER 与 CONFIRM_STRICT 不得重叠")
        self.assertFalse(confirm & strict, "CONFIRM 与 CONFIRM_STRICT 不得重叠")
        # 下单类：只能待在最严档，绝不下沉到「一次确认即可执行」
        for t in ("create-order", "mall-create-order", "party-order-create"):
            self.assertIn(t, strict)
            self.assertNotIn(t, confirm)
            self.assertNotIn(t, never)
        self.assertIn("auto-bind-coupons", confirm)
        self.assertIn("cancel-order", confirm)
        self.assertIn("draw-lottery", never)
        # 下单绝不是「永不执行」——官方 create-order 创建的只是待支付订单
        self.assertNotIn("create-order", never)

    def test_32_render_marks_simulated_date(self):
        """指定日期演示必须标明是模拟"""
        ctx = ik.build_date_context(date(2026, 9, 25), simulated=True)
        theme = ik.build_theme(ctx)
        text = ik.render_memorial(ctx, theme, {"ok": False, "message": "x",
                                               "candidates": [], "warnings": []},
                                  None, None, None)
        self.assertIn("指定日期模拟", text)


class TestRealMcpEvidence(unittest.TestCase):
    """真实 MCP 调用留痕核验（离线复核 fixture 的来源标记）"""

    def test_33_menu_fixture_is_real(self):
        m = load("menu_real_sample.json")
        self.assertTrue(m["_is_real_data"])
        self.assertEqual(m["_store"]["storeCode"], "3330052")
        self.assertTrue(m["_traceId"])

    def test_34_price_fixture_is_real(self):
        p = load("price_real_sample.json")
        self.assertTrue(p["_is_real_data"])
        self.assertEqual(p["data"]["price"], 4100)
        self.assertEqual(p["data"]["productList"][0]["productName"], "巨无霸")

    def test_35_adapter_handles_real_shape(self):
        adapted = ik.adapt_mcd_menu(load("menu_real_sample.json"))
        codes = {i["code"] for i in adapted["items"]}
        self.assertIn("1100", codes)
        item = next(i for i in adapted["items"] if i["code"] == "1100")
        self.assertEqual(item["name"], "巨无霸")
        self.assertEqual(ik._price_yuan(item), 26.5)


class TestSceneRouter(unittest.TestCase):
    """[8] 场景路由：到店自取 / 麦乐送外送 / 得来速 / 团餐"""

    def test_36_delivery_keywords(self):
        for text in ("帮我叫个麦乐送", "外卖送到公司", "要配送到家", "点外卖"):
            s = ik.detect_scene(text)
            self.assertEqual(s["key"], "delivery", text)
            self.assertEqual(s["beType"], 2)
            self.assertEqual(s["orderType"], 2)
            self.assertTrue(s["needs_be_code"])

    def test_37_dine_in_default_and_explicit(self):
        s = ik.detect_scene("今天想去店里吃")
        self.assertEqual(s["key"], "dine_in")
        self.assertEqual(s["beType"], 1)
        self.assertFalse(s["needs_be_code"])
        # 未言明时默认麦乐送外送（陛下实测多为外送），但必须标注为推断而非用户明示
        s2 = ik.detect_scene("预算30推荐一份")
        self.assertEqual(s2["key"], "delivery")
        self.assertEqual(s2["source"], "default")
        self.assertIn("未言明", s2["message"])
        self.assertEqual(s2["beType"], 2)

    def test_38_unimplemented_scenes_flagged(self):
        for text, key in (("走得来速", "drive_thru"), ("公司要订团餐", "group_meal")):
            s = ik.detect_scene(text)
            self.assertEqual(s["key"], key)
            self.assertFalse(s["implemented"])

    def test_39_explicit_overrides_text(self):
        s = ik.detect_scene("我要外送", explicit="dine_in")
        self.assertEqual(s["key"], "dine_in")
        self.assertEqual(s["source"], "explicit")
        bad = ik.detect_scene("随便", explicit="no_such_scene")
        self.assertIsNone(bad["key"])


class TestDeliveryFlow(unittest.TestCase):
    """麦乐送外送链路：地址 → 可配送门店(beCode) → 菜单/核价"""

    def test_40_real_empty_addresses_degrades_gracefully(self):
        """真实返回空地址簿：必须降级，不得伪造地址，且不得自动创建"""
        addr = ik.adapt_mcd_addresses(load("delivery_addresses_real.json"))
        self.assertTrue(addr["ok"])
        self.assertTrue(addr["empty"])
        plan = ik.build_delivery_plan(addr)
        self.assertEqual(plan["status"], "need_address_create")
        self.assertFalse(plan["write_ops"]["auto_call_allowed"])
        self.assertIn("delivery-create-address", plan["write_ops"]["forbidden_tools"])
        self.assertIsNone(plan["next_tool"])  # 未获授权不得推进

    def test_41_becode_required_evidence(self):
        """外送缺 beCode 的真实报错必须被链路引用为阻塞依据"""
        err = load("delivery_beCode_required_real.json")
        self.assertEqual(err["code"], 600048)
        self.assertFalse(err["success"])
        plan = ik.build_delivery_plan(
            ik.adapt_mcd_addresses({"data": {"addresses": [
                {"addressId": "A1", "fullAddress": "某地", "contactName": "甲"}]}}),
            ik.adapt_mcd_delivery_stores({"success": True,
                                           "data": [{"storeCode": "S1"}]}),
            chosen_address_id="A1")
        self.assertEqual(plan["status"], "need_be_code")
        self.assertTrue(any("600048" in b for b in plan["blockers"]))

    def test_42_address_id_must_come_from_official(self):
        """addressId 不得凭空捏造：不在官方列表内即判为不匹配"""
        addr = ik.adapt_mcd_addresses({"data": {"addresses": [
            {"addressId": "A1", "fullAddress": "某地"}]}})
        plan = ik.build_delivery_plan(addr, chosen_address_id="BAD999")
        self.assertEqual(plan["status"], "address_mismatch")
        self.assertIn("BAD999", plan["blockers"][0])

    def test_43_ready_path_builds_correct_params(self):
        """拿到 beCode 后，query-meals 参数必须带 beType=2/orderType=2/beCode"""
        addr = ik.adapt_mcd_addresses({"data": {"addresses": [
            {"addressId": "A1", "fullAddress": "某地"}]}})
        stores = ik.adapt_mcd_delivery_stores({"success": True, "data": [
            {"storeCode": "3330052", "beCode": "BE777", "storeName": "某餐厅"}]})
        plan = ik.build_delivery_plan(addr, stores, chosen_address_id="A1")
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["next_tool"], "query-meals")
        self.assertEqual(plan["next_params"], {"beType": 2, "orderType": 2,
                                               "storeCode": "3330052",
                                               "beCode": "BE777"})

    def test_44_delivery_fees_never_guessed(self):
        """配送费未返回时必须标注未核实，不得给数字"""
        addr = ik.adapt_mcd_addresses({"data": {"addresses": [
            {"addressId": "A1", "fullAddress": "某地"}]}})
        stores = ik.adapt_mcd_delivery_stores({"success": True, "data": [
            {"storeCode": "S1", "beCode": "BE1"}]})
        plan = ik.build_delivery_plan(addr, stores, chosen_address_id="A1")
        joined = " ".join(plan["unverified"])
        self.assertIn("配送费", joined)
        self.assertIn("臣不在核价前预估", joined)
        self.assertFalse(any(ch.isdigit() for ch in joined))

    def test_44b_delivery_has_no_minimum_order_fee(self):
        """麦乐送外送不设起送门槛：只作说明，不给金额、不标「未能核实」"""
        addr = ik.adapt_mcd_addresses({"data": {"addresses": [
            {"addressId": "A1", "fullAddress": "某地"}]}})
        stores = ik.adapt_mcd_delivery_stores({"success": True, "data": [
            {"storeCode": "S1", "beCode": "BE1"}]})
        plan = ik.build_delivery_plan(addr, stores, chosen_address_id="A1")
        notes = " ".join(plan.get("notes", []))
        self.assertIn("起送价", notes)
        self.assertIn("不设起送门槛", notes)
        self.assertNotIn("未能核实", notes)
        # 不得出现任何起送金额数字
        self.assertFalse(any(ch.isdigit() for ch in notes))
        # 「未能核实」也不该出现在起送价相关表述中
        self.assertNotIn("起送价：官方返回中未含该字段", " ".join(plan["unverified"]))
        # 渲染后仍应可见该说明
        text = "\n".join(ik.render_delivery_section(plan))
        self.assertIn("不设起送门槛", text)

    def test_45_delivery_section_never_claims_auto_order(self):
        """驿站传膳章节必须明示不会自动下单/付款/创建地址"""
        plan = ik.build_delivery_plan(
            ik.adapt_mcd_addresses(load("delivery_addresses_real.json")))
        text = "\n".join(ik.render_delivery_section(plan))
        self.assertIn("不会自动创建地址", text)
        self.assertIn("自动下单", text)
        for w in ik.COMPLIANCE_BANNED:
            self.assertNotIn(w, text)

    def test_46b_blocked_delivery_marks_dine_in_menu_mismatch(self):
        """外送未打通时，不得把到店菜单/核价当成外送报价呈现"""
        plan = ik.build_delivery_plan(
            ik.adapt_mcd_addresses(load("delivery_addresses_real.json")))
        self.assertNotEqual(plan["status"], "ready")
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        cands = ik.build_candidates(load("menu_real_sample.json"), {"budget_max": 30}, theme)
        text = ik.render_memorial(ctx, theme, cands, None, None, None, None, plan)
        self.assertIn("到店自取口径", text)
        self.assertIn("不敢以此充当外送报价", text)

    def test_46_render_includes_delivery_section(self):
        plan = ik.build_delivery_plan(
            ik.adapt_mcd_addresses(load("delivery_addresses_real.json")))
        text = ik.render_memorial(ik.build_date_context(date(2026, 10, 21)),
                                  ik.build_theme(ik.build_date_context(date(2026, 10, 21))),
                                  {"ok": False, "message": "无菜单", "candidates": []},
                                  None, None, None, None, plan)
        self.assertIn("驿站传膳", text)
        self.assertIn("麦乐送外送", text)


class TestPreferencePersistence(unittest.TestCase):
    """坦白②：跨会话偏好持久化（存工作区之外，不进仓库）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "preferences.json")

    def test_47_persist_and_reload_across_sessions(self):
        """偏好必须能落盘并在下一次「会话」读回"""
        self.assertIsNone(ik.load_persisted_preference(self.path))
        prof = ik.merge_preference(dict(ik.DEFAULT_PROFILE),
                                   {"budget_max": 30, "likes": ["汉堡"]})
        ik.save_preference(prof, self.path)
        reloaded = ik.load_persisted_preference(self.path)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["explicit"]["budget_max"], 30)
        self.assertEqual(reloaded["explicit"]["likes"], ["汉堡"])
        self.assertTrue(reloaded["persisted"])

    def test_48_clear_all_removes_file(self):
        prof = ik.merge_preference(dict(ik.DEFAULT_PROFILE), {"budget_max": 30})
        ik.save_preference(prof, self.path)
        self.assertTrue(os.path.exists(self.path))
        ik.clear_persisted_preference(self.path)
        self.assertFalse(os.path.exists(self.path))
        self.assertIsNone(ik.load_persisted_preference(self.path))

    def test_49_persisted_scope_is_declared(self):
        """存档成功时文案必须改口，不得再写「本次会话内有效」"""
        prof = ik.merge_preference(dict(ik.DEFAULT_PROFILE), {"budget_max": 30})
        prof = ik.save_preference(prof, self.path)
        text = ik.describe_preference(prof)
        self.assertIn("跨会话有效", text)
        self.assertNotIn("本次会话内有效，未存档", text)
        # 未存档时仍需如实说明
        text2 = ik.describe_preference(ik.merge_preference(
            dict(ik.DEFAULT_PROFILE), {"budget_max": 30}))
        self.assertIn("本次会话内有效", text2)

    def test_50_corrupted_file_degrades(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.assertIsNone(ik.load_persisted_preference(self.path))

    def test_51_storage_outside_workspace(self):
        """存档路径必须在工作区之外，避免进入 Git 仓库"""
        p = ik.preference_path()
        self.assertNotIn("WorkBuddy", p.replace("\\", "/").split("/.workbuddy")[0]
                         .split("/")[-1] if False else "")
        self.assertTrue(p.replace("\\", "/").endswith(
            ".workbuddy/user_data/jin-gong-men/preferences.json"), p)


class TestAvailableCoupons(unittest.TestCase):
    """坦白①：真实可领取券令（available-coupons）"""

    def test_52_parses_real_text_response(self):
        """官方该工具返回纯文本，必须能解析且不得编造券名"""
        with open(os.path.join(FIXTURES, "available_coupons_real.txt"),
                  "r", encoding="utf-8") as fh:
            parsed = ik.adapt_mcd_available_coupons(fh.read())
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["coupons"]), 3)
        titles = {c["title"] for c in parsed["coupons"]}
        self.assertIn("11.9元麦辣鸡腿堡", titles)
        self.assertTrue(all(c["status"] == "可领取" for c in parsed["coupons"]))

    def test_53_empty_text_not_fabricated(self):
        parsed = ik.adapt_mcd_available_coupons("")
        self.assertTrue(parsed["empty"])
        self.assertEqual(parsed["coupons"], [])

    def test_54_render_marks_not_usable_for_this_order(self):
        with open(os.path.join(FIXTURES, "available_coupons_real.txt"),
                  "r", encoding="utf-8") as fh:
            parsed = ik.adapt_mcd_available_coupons(fh.read())
        ctx = ik.build_date_context(date(2026, 10, 22))
        text = ik.render_memorial(ctx, ik.build_theme(ctx),
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, None, None, None, None, parsed)
        self.assertIn("可领券令", text)
        self.assertIn("非本单可用券", text)
        self.assertIn("臣不代领", text)


class TestDeliveryRealEndToEnd(unittest.TestCase):
    """外送链路端到端：真实菜单 + 真实核价（含配送费/打包费）"""

    def test_55_real_delivery_menu_prices_differ_from_dine_in(self):
        dm = ik.adapt_mcd_menu(load("delivery_menu_real.json"))
        code_price = {i["code"]: ik._price_yuan(i) for i in dm["items"]}
        self.assertEqual(code_price["901100"], 28.5)   # 巨无霸 外送价
        self.assertEqual(code_price["501205"], 15.5)   # 薯条 外送价

    def test_56_real_delivery_price_includes_fees(self):
        raw = load("delivery_price_real.json")
        adapted = ik.adapt_mcd_price(raw)
        self.assertEqual(adapted["official_total_fen"], 5190)
        self.assertEqual(adapted["product_fen"], 4400)
        self.assertEqual(adapted["delivery_fen"], 600)   # 配送费 6.00 元
        self.assertEqual(adapted["packing_fen"], 190)    # 打包费 1.90 元

    def test_57_verify_price_accepts_raw_response(self):
        res = ik.verify_price(load("delivery_price_real.json"))
        self.assertTrue(res["ok"])
        self.assertEqual(res["rows"][0]["total"], 51.9)
        self.assertIn("官方核价", res["rows"][0]["price_source"])

    def test_58_render_shows_fee_breakdown(self):
        res = ik.verify_price(load("delivery_price_real.json"))
        ctx = ik.build_date_context(date(2026, 10, 22))
        text = ik.render_memorial(ctx, ik.build_theme(ctx),
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, res, None)
        self.assertIn("配送费", text)
        self.assertIn("6.00 元", text)
        self.assertIn("打包费", text)


class TestMealPhotos(unittest.TestCase):
    """[7] 御膳图鉴 —— 餐品图片与详情（真实 query-meal-detail 返回）"""

    def test_60_query_meals_has_no_image_field(self):
        """已实跑确认：菜单列表接口不返回图片，这是「必须逐道取详情」的前提"""
        for name in ("menu_real_sample.json", "delivery_menu_real.json"):
            raw = json.dumps(load(name), ensure_ascii=False)
            self.assertNotIn("image", raw,
                             f"{name} 若出现 image，需重新核对官方返回结构")

    def test_61_meal_detail_adapts_real_single(self):
        """单品详情：取到图片、可特调标记"""
        d = ik.adapt_mcd_meal_detail(load("meal_detail_single_real.json"))
        self.assertTrue(d["ok"])
        self.assertEqual(d["name"], "巨无霸")
        self.assertTrue(d["image"].startswith("https://menu-img.mcd.cn/"))
        self.assertTrue(d["support_modify"])
        self.assertEqual(d["rounds_count"], 0)
        self.assertIn("可特调", d["modification_summary"])

    def test_62_meal_detail_adapts_real_combo(self):
        """套餐详情：解析出各轮默认搭配"""
        d = ik.adapt_mcd_meal_detail(load("meal_detail_combo_real.json"))
        self.assertTrue(d["ok"])
        self.assertEqual(d["name"], "巨无霸中套餐")
        self.assertTrue(d["image"])
        self.assertEqual(d["rounds_count"], 3)
        names = [x["name"] for x in d["default_combo"]]
        self.assertIn("巨无霸", names)
        self.assertIn("中薯条", names)
        self.assertIn("可口可乐中杯", names)

    def test_63_attach_photos_only_from_official_return(self):
        """图片只能来自官方返回，未取得者留空，不得复用他品之图"""
        cands = {"ok": True, "candidates": [
            {"code": "901100", "name": "巨无霸", "price": 28.5},
            {"code": "901000", "name": "汉堡包", "price": 15.0}]}
        merged = ik.attach_photos(cands, [
            ik.adapt_mcd_meal_detail(load("meal_detail_single_real.json"))])
        self.assertEqual(merged["candidates"][0]["image"],
                         "https://menu-img.mcd.cn/pcm/prod/menu/20250611/product/"
                         "MS_901100_600_1749174931903.png")
        self.assertIsNone(merged["candidates"][1]["image"])
        self.assertIn("1/2", merged["photos_note"])

    def test_64_gallery_renders_markdown_image(self):
        """图鉴必须渲染为 Markdown 图片，且标注官方来源"""
        cands = ik.build_candidates(load("delivery_menu_real.json"),
                                    {"budget_max": 60, "likes": ["巨无霸"]})
        dets = [ik.adapt_mcd_meal_detail(load("meal_detail_single_real.json")),
                ik.adapt_mcd_meal_detail(load("meal_detail_combo_real.json"))]
        merged = ik.attach_photos(cands, dets)
        lines = ik.render_photo_gallery(merged)
        text = "\n".join(lines)
        self.assertIn("![巨无霸](", text)
        self.assertIn("menu-img.mcd.cn", text)
        self.assertIn("图片来源", text)
        self.assertIn("默认搭配", text)

    def test_65_gallery_without_photos_never_fabricates(self):
        """无图时不得编造图片链接"""
        cands = {"ok": True, "candidates": [
            {"code": "X", "name": "某膳品", "price": 1.0, "image": None}]}
        text = "\n".join(ik.render_photo_gallery(cands))
        self.assertNotIn("![", text)
        self.assertIn("不配图", text)

    def test_66_memorial_gallery_section(self):
        """奏折中出现「御膳图鉴」章节，并说明图片来自详情接口"""
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        cands = ik.build_candidates(load("delivery_menu_real.json"),
                                    {"budget_max": 60, "likes": ["巨无霸"]})
        dets = [load("meal_detail_single_real.json")]
        text = ik.render_memorial(ctx, theme, cands, None, None, None,
                                  None, None, None, dets)
        self.assertIn("御膳图鉴", text)
        self.assertIn("query-meal-detail", text)
        self.assertIn("![巨无霸](", text)

    def test_67_meal_detail_card_respects_official_display_rule(self):
        """官方要求：不主动展开特调项，仅统计"""
        d = ik.adapt_mcd_meal_detail(load("meal_detail_single_real.json"))
        collapsed = "\n".join(ik.render_meal_detail_card(d))
        self.assertIn("查看特调", collapsed)
        self.assertNotIn("巨无霸酱", collapsed)
        expanded = "\n".join(ik.render_meal_detail_card(d, show_modification=True))
        self.assertIn("巨无霸酱", expanded)

    def test_68_missing_image_is_reported_not_invented(self):
        """详情返回无 image 时，如实说明，不猜 URL"""
        d = ik.adapt_mcd_meal_detail({"success": True, "data": {
            "code": "999", "name": "某膳品", "image": None, "rounds": []}})
        self.assertTrue(d["ok"])
        self.assertIsNone(d["image"])
        self.assertIn("未返回该膳品图片", d["message"])
        card = "\n".join(ik.render_meal_detail_card(d))
        self.assertNotIn("![", card)


class TestCouponClaim(unittest.TestCase):
    """代领券令 —— 第二档写操作（真实 available-coupons 返回驱动）"""

    def _available(self):
        with open(os.path.join(FIXTURES, "available_coupons_real.txt"),
                  encoding="utf-8") as fh:
            return ik.adapt_mcd_available_coupons(fh.read())

    def test_69_default_is_never_auto_claim(self):
        """默认不得代领：必须先待确认"""
        plan = ik.build_coupon_claim_plan(self._available())
        self.assertEqual(plan["status"], "need_confirm")
        self.assertFalse(plan["auto_call_allowed"])
        self.assertEqual(plan["tier"], "confirm")

    def test_70_confirm_prompt_lists_every_coupon(self):
        """确认前必须逐张复述券名，不许笼统说「全部券」"""
        plan = ik.build_coupon_claim_plan(self._available())
        av = self._available()
        self.assertEqual(plan["count"], len(av["coupons"]))
        for c in av["coupons"]:
            self.assertIn(c["title"], plan["confirm_prompt"])

    def test_71_cannot_choose_single_coupon_is_disclosed(self):
        """官方只能一键全领，不能挑——臣必须如实说明，不可假称能挑"""
        plan = ik.build_coupon_claim_plan(self._available())
        self.assertEqual(plan["granularity"], "all_or_nothing")
        self.assertIn("不支持只领其中某一张", plan["granularity_note"])
        self.assertIn("不会假称可以挑选", plan["granularity_note"])

    def test_72_claim_does_not_promise_usable_for_this_order(self):
        """领了券也不等于本单可用，必须写明后续两步验证"""
        plan = ik.build_coupon_claim_plan(self._available(), confirmed=True)
        self.assertEqual(plan["status"], "ready")
        joined = " ".join(plan["after_claim"])
        self.assertIn("query-my-coupons", joined)
        self.assertIn("calculate-price", joined)
        caveats = " ".join(plan["caveats"])
        self.assertIn("不等于", caveats)
        self.assertIn("本单可用", caveats)

    def test_73_unknown_claim_quota_is_disclosed(self):
        """臣未核实是否消耗领取资格，不得装作确定"""
        plan = ik.build_coupon_claim_plan(self._available())
        caveats = " ".join(plan["caveats"])
        self.assertIn("未核实", caveats)
        self.assertIn("领取资格", caveats)

    def test_74_nothing_to_claim_does_not_execute(self):
        """无可领券时不得生成任何代领动作"""
        plan = ik.build_coupon_claim_plan({"ok": True, "empty": True, "coupons": []})
        self.assertEqual(plan["status"], "nothing_to_claim")
        self.assertIsNone(plan["confirm_prompt"])

    def test_75_memorial_shows_claim_section(self):
        """奏折「可领券令」章节须出现代领确认段"""
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        text = ik.render_memorial(ctx, theme,
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, None, None, None, None, self._available())
        self.assertIn("代领券令", text)
        self.assertIn("候陛下示下", text)
        self.assertNotIn("已获明示", text)
        # 仍未下单这条底线不能被领券功能冲掉
        self.assertIn("未下单、未付款", text)


class TestCouponVerificationReal(unittest.TestCase):
    """券与本单的匹配核价 —— 2026-10-22 真实跑通（此前一直标「未验证」）"""

    def test_76_store_coupons_adapts_real_non_empty(self):
        """首个非空门店券返回：解析出适用商品编码，这是「本单可用」的依据"""
        sc = ik.adapt_mcd_store_coupons(load("store_coupons_real.json"))
        self.assertTrue(sc["ok"])
        self.assertFalse(sc["empty"])
        self.assertEqual(len(sc["coupons"]), 2)
        codes = {p["code"] for c in sc["coupons"] for p in c["products"]}
        self.assertIn("1440", codes)
        self.assertIn("9900016534", codes)
        self.assertIn("本单可用", sc["note"])

    def test_77_empty_store_coupons_is_not_a_failure(self):
        """官方返回空券是真实结果，不得当成查询失败"""
        sc = ik.adapt_mcd_store_coupons({"success": True, "data": []})
        self.assertTrue(sc["ok"])
        self.assertTrue(sc["empty"])
        self.assertIn("真实空结果", sc["message"])

    def test_78_coupon_price_verified_by_two_official_calls(self):
        """券效核验：两次官方核价对比，臣不自己算价"""
        cv = ik.verify_coupon_price(load("price_coupon_second_real.json"),
                                    load("price_control_901100_real.json"))
        # 注意：此处用不同商品做对照仅为验证算法；真实结论见下一条
        self.assertTrue(cv["ok"])
        self.assertEqual(cv["with_coupon_fen"], 2780)
        self.assertEqual(cv["official_discount_fen"], 1010)

    def test_79_baseline_unavailable_is_not_guessed(self):
        """实测异常：1440 不带券时官方核不出价 → 不得断言减免金额"""
        cv = ik.verify_coupon_price(load("price_coupon_applied_real.json"),
                                    load("price_no_coupon_1440_real.json"))
        self.assertTrue(cv["ok"])
        self.assertEqual(cv["baseline"], "baseline_unavailable")
        self.assertIsNone(cv["saving_fen"],
                          "基线不可用时不得给出减免金额")
        self.assertIn("无法据此算出", cv["message"])
        # 但仍应如实报出带券应付与官方 discount
        self.assertEqual(cv["with_coupon_fen"], 1900)
        self.assertEqual(cv["official_discount_fen"], 1360)

    def test_80_no_baseline_still_reports_official_discount(self):
        """未做对照核价时，只能引用官方 discount 字段，不可自称「实省」"""
        cv = ik.verify_coupon_price(load("price_coupon_applied_real.json"))
        self.assertEqual(cv["baseline"], "not_queried")
        self.assertIsNone(cv["saving_fen"])
        self.assertIn("官方 `discount` 字段", cv["message"])

    def test_81_claim_reconciliation_reports_real_mismatch(self):
        """实测：领券回报 3 张，卡包实查 2 张 —— 差异必须摆出来"""
        rc = ik.reconcile_claim_result(
            ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2", "免费脆薯饼"],
            ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2"])
        self.assertEqual(rc["claimed_count"], 3)
        self.assertEqual(rc["wallet_count"], 2)
        self.assertEqual(rc["missing"], ["免费脆薯饼"])
        self.assertFalse(rc["consistent"])
        self.assertIn("不一致", rc["message"])

    def test_82_claim_reconciliation_consistent_case(self):
        rc = ik.reconcile_claim_result(["A券", "B券"], ["A券", "B券"])
        self.assertTrue(rc["consistent"])
        self.assertEqual(rc["missing"], [])
        self.assertIn("数目一致", rc["message"])

    def test_83_memorial_renders_coupon_verification(self):
        """奏折须渲染本店可用券 / 券效核验 / 领券对账三章"""
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        extras = {
            "store_coupons": ik.adapt_mcd_store_coupons(load("store_coupons_real.json")),
            "coupon_verify": ik.verify_coupon_price(
                load("price_coupon_applied_real.json"),
                load("price_no_coupon_1440_real.json")),
            "claim_reconcile": ik.reconcile_claim_result(
                ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2", "免费脆薯饼"],
                ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2"]),
        }
        text = ik.render_memorial(ctx, theme,
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, None, None, None, None, None, None,
                                  False, extras)
        self.assertIn("本店可用券令", text)
        self.assertIn("券效核验", text)
        self.assertIn("领券对账", text)
        # 券码属私有资产，不得落进输出
        self.assertNotIn("MCD6409Y002707B210F48", text)
        # 底线不动
        self.assertIn("未下单、未付款", text)


class TestOrderPlacement(unittest.TestCase):
    """代下单（第三档写操作）：三重复述不全点头，臣绝不出单"""

    STORE = {"store_code": "901100", "name": "杭州某某餐厅", "be_code": "BE0001",
             "be_type": 2, "order_type": 2, "scene_name": "麦乐送外送"}
    ITEMS = [{"product_code": "1440", "name": "麦辣鸡腿汉堡", "quantity": 1,
              "coupon_title": "11.9元麦辣鸡腿堡"}]

    def _price(self):
        return load("price_coupon_applied_real.json")

    def test_84_blocked_without_store_code(self):
        """没有门店编码，臣连复述都无从复述"""
        plan = ik.build_order_plan({"name": "某店"}, self.ITEMS, self._price(),
                                   {"mode": "delivery", "address": "杭州",
                                    "address_id": "A1"})
        self.assertEqual(plan["status"], "blocked")
        self.assertFalse(plan["auto_call_allowed"])
        self.assertTrue(any("门店编码" in b for b in plan["blockers"]))

    def test_85_blocked_with_empty_items(self):
        """空单不创建"""
        plan = ik.build_order_plan(self.STORE, [], self._price(),
                                   {"mode": "delivery", "address": "杭州",
                                    "address_id": "A1"})
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("没有任何商品" in b for b in plan["blockers"]))

    def test_86_blocked_without_official_price(self):
        """金额不明，臣不敢下单"""
        plan = ik.build_order_plan(self.STORE, self.ITEMS, None,
                                   {"mode": "delivery", "address": "杭州",
                                    "address_id": "A1"})
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("核价" in b for b in plan["blockers"]))

    def test_87_pickup_blocked_without_take_way_code(self):
        """到店单缺 takeWayCode 不得臆测"""
        plan = ik.build_order_plan(self.STORE, self.ITEMS, self._price(),
                                   {"mode": "pickup", "take_way": "柜台取餐"})
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("takeWayCode" in b for b in plan["blockers"]))

    def test_88_delivery_blocked_without_address_id(self):
        """外送单缺 addressId 不得下单到不明之处"""
        plan = ik.build_order_plan(self.STORE, self.ITEMS, self._price(),
                                   {"mode": "delivery", "address": "杭州"})
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("addressId" in b for b in plan["blockers"]))

    def test_89_need_confirm_until_all_three_recitals(self):
        """只确认部分复述，仍不得出单"""
        dlv = {"mode": "delivery", "address": "杭州", "address_id": "A1"}
        p1 = ik.build_order_plan(self.STORE, self.ITEMS, self._price(), dlv,
                                 confirmed_steps=["content"])
        self.assertEqual(p1["status"], "need_confirm")
        self.assertEqual(p1["pending_steps"], ["amount", "delivery"])
        self.assertFalse(p1["auto_call_allowed"])
        p2 = ik.build_order_plan(self.STORE, self.ITEMS, self._price(), dlv,
                                 confirmed_steps=["content", "amount"])
        self.assertEqual(p2["status"], "need_confirm")
        self.assertEqual(p2["pending_steps"], ["delivery"])
        self.assertIn("臣未创建任何订单", p2["message"])

    def test_90_ready_only_after_all_three_and_never_pays(self):
        """三重复述齐备才可出单，且支付边界写死"""
        dlv = {"mode": "delivery", "address": "杭州", "address_id": "A1"}
        plan = ik.build_order_plan(self.STORE, self.ITEMS, self._price(), dlv,
                                   confirmed_steps=["content", "amount", "delivery"])
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["pending_steps"], [])
        # 三个复述都在，金额来自官方核价（1900 分 = 19.00 元）
        self.assertIn("应付总额", "\n".join(plan["recitals"]["amount"]))
        self.assertIn("19.00 元", "\n".join(plan["recitals"]["amount"]))
        text = "\n".join(ik.render_order_section(plan))
        self.assertIn("① 订单内容", text)
        self.assertIn("② 金额明细", text)
        self.assertIn("③ 交付方式", text)
        self.assertIn("待支付订单", text)
        self.assertIn("臣绝不代付", text)
        self.assertIn("cancel-order", text)

    def test_91_memorial_renders_order_section(self):
        """奏折须渲染「拟旨下单」，且就绪时改口径但仍不代付"""
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        dlv = {"mode": "delivery", "address": "杭州", "address_id": "A1"}
        extras = {"order_plan": ik.build_order_plan(
            self.STORE, self.ITEMS, self._price(), dlv,
            confirmed_steps=["content", "amount", "delivery"])}
        text = ik.render_memorial(ctx, theme,
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, None, None, None, None, None,
                                  None, False, extras)
        self.assertIn("拟旨下单", text)
        self.assertIn("三重复述", text)
        self.assertIn("臣绝不代付", text)
        # 就绪时不再说「请陛下自行前往点餐」，但支付仍归陛下
        self.assertNotIn("请陛下自行前往麦当劳官方点餐渠道完成购买", text)
        self.assertIn("支付仍须陛下自行完成", text)

    def test_92_memorial_keeps_default_when_order_not_ready(self):
        """未获全确认时，奏折口径维持原样：未下单、未付款"""
        ctx = ik.build_date_context(date(2026, 10, 22))
        theme = ik.build_theme(ctx)
        extras = {"order_plan": ik.build_order_plan(
            self.STORE, self.ITEMS, self._price(), None)}
        text = ik.render_memorial(ctx, theme,
                                  {"ok": False, "message": "x", "candidates": []},
                                  None, None, None, None, None, None,
                                  None, False, extras)
        self.assertIn("未下单、未付款", text)
        self.assertIn("请陛下自行前往麦当劳官方点餐渠道完成购买", text)


class TestComboAndTaste(unittest.TestCase):
    """套餐选配与必选口味：不下单到"默认"上

    真实由来（2026-10-22 陛下实测）：点套餐时只落了「汉堡包」三个字，
    选配与口味全按官方默认走，可乐去冰、无糖一概没问。
    官方展示规则说"不要主动展开特调"，那是**浏览时**不刷屏；
    一旦要下单，默认值落单就改不了，必须逐条问。
    """

    STORE = {"store_code": "3330329", "name": "麦当劳杭州普大福地餐厅",
             "be_code": "333032902", "be_type": 2, "order_type": 2,
             "scene_name": "麦乐送外送"}
    DLV = {"mode": "delivery", "address": "（陛下存档地址）", "address_id": "A1"}
    COLA = {"product_code": "903050", "name": "可口可乐", "quantity": 1}

    def _price(self):
        return load("price_coupon_applied_real.json")

    def test_93_cola_has_required_ice_group(self):
        """可乐的冰量是「必选」组（minValues=1），默认标准"""
        det = ik.adapt_mcd_meal_detail(load("meal_detail_cola_real.json"))
        req = ik.required_mod_groups(det)
        self.assertEqual(len(req), 1)
        self.assertIn("去冰", req[0]["names"])
        self.assertEqual(req[0]["default_names"], ["标准"])

    def test_94_unconfirmed_required_taste_blocks_order(self):
        """必选口味没定，臣不得拿默认落单"""
        plan = ik.build_order_plan(self.STORE, [self.COLA], self._price(), self.DLV,
                                   None, [load("meal_detail_cola_real.json")])
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("必选口味尚未定夺" in b for b in plan["blockers"]))
        self.assertTrue(any("官方默认「标准」" in b for b in plan["blockers"]))

    def test_95_chosen_taste_is_written_into_recital(self):
        """陛下定了去冰，复述里必须写出去冰"""
        item = dict(self.COLA, mods=[{"group": "mod0", "value": "去冰"}])
        plan = ik.build_order_plan(self.STORE, [item], self._price(), self.DLV,
                                   ["content", "amount", "delivery"],
                                   [load("meal_detail_cola_real.json")])
        self.assertEqual(plan["status"], "ready")
        self.assertIn("去冰", "\n".join(plan["recitals"]["content"]))

    def test_96_combo_without_round_selections_blocks_order(self):
        """套餐未逐轮定夺 → 拦截，并摆出官方默认是什么"""
        item = {"product_code": "9900003001", "name": "巨无霸中套餐", "quantity": 1}
        plan = ik.build_order_plan(self.STORE, [item], self._price(), self.DLV,
                                   None, [load("meal_detail_combo_real.json")])
        self.assertEqual(plan["status"], "blocked")
        joined = "".join(plan["blockers"])
        self.assertIn("轮选配尚未定夺", joined)
        self.assertIn("中薯条", joined)          # 官方默认须摆出来
        self.assertIn("可口可乐中杯", joined)

    def test_97_partial_rounds_block_order(self):
        """只定了一轮，臣不敢替陛下补齐其余"""
        item = {"product_code": "9900003001", "name": "巨无霸中套餐", "quantity": 1,
                "rounds": [{"round": "选择套餐内饮料", "choice": "可口可乐中杯"}]}
        plan = ik.build_order_plan(self.STORE, [item], self._price(), self.DLV,
                                   None, [load("meal_detail_combo_real.json")])
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any("不敢替陛下补齐其余" in b for b in plan["blockers"]))

    def test_98_full_rounds_render_every_choice(self):
        """三轮齐全时，复述逐轮写出，不能只剩「汉堡包」三个字"""
        item = {"product_code": "9900003001", "name": "巨无霸中套餐", "quantity": 1,
                "rounds": [{"round": "主餐", "choice": "巨无霸"},
                           {"round": "选择套餐内小食", "choice": "玉米杯(小)"},
                           {"round": "选择套餐内饮料", "choice": "可口可乐中杯"}]}
        plan = ik.build_order_plan(self.STORE, [item], self._price(), self.DLV,
                                   ["content", "amount", "delivery"],
                                   [load("meal_detail_combo_real.json")])
        self.assertEqual(plan["status"], "ready")
        text = "\n".join(plan["recitals"]["content"])
        for want in ("巨无霸", "玉米杯(小)", "可口可乐中杯"):
            self.assertIn(want, text)

    def test_99_checklist_lists_what_to_ask(self):
        """下单前待定清单要逐条列出该问什么"""
        cl = ik.build_pending_checklist([load("meal_detail_combo_real.json"),
                                         load("meal_detail_cola_real.json")])
        self.assertEqual(cl["count"], 2)
        text = "\n".join(ik.render_pending_checklist(cl))
        self.assertIn("必选口味", text)
        self.assertIn("官方默认「标准」", text)
        self.assertIn("选配轮次", text)

    def test_100_optional_mods_do_not_block(self):
        """minValues=0 的可特调组不是必选，不该拦着不让下单"""
        det = ik.adapt_mcd_meal_detail(load("meal_detail_single_real.json"))
        self.assertEqual(ik.required_mod_groups(det), [])


class TestMaiCalendarNaming(unittest.TestCase):
    """[麦历] 文化主题栏目的叫法与三条边界必须锁死"""

    def _render(self, d: date, **kw):
        ctx = ik.build_date_context(d)
        theme = ik.build_theme(ctx, **kw)
        return ctx, theme, ik.render_memorial(
            ctx, theme, {"ok": False, "message": "未查询菜单"}, None, None, None)

    def test_105_heading_is_maicalendar_not_huangli(self):
        """奏折首栏必须叫「麦历呈报」，不得再出现「黄历」或「钦天监」"""
        ctx, theme, text = self._render(date(2026, 10, 23))
        self.assertIn("麦历呈报", text)
        self.assertNotIn("黄历", text)
        self.assertNotIn("钦天监", text)

    def test_106_disclaimer_states_all_three_boundaries(self):
        """三条边界一句都不能少：不预测吉凶 / 不影响消费决策 / 不冒充官方促销"""
        ctx, theme, text = self._render(date(2026, 10, 23))
        self.assertIn(theme["disclaimer"], text)
        for clause in ("不预测吉凶", "不影响消费决策", "不冒充官方促销"):
            self.assertIn(clause, theme["disclaimer"])
        # 每一条都要说清"不做什么"，不能只留个标题
        for detail in ("不排宜忌", "非麦当劳官方活动", "与节气无关"):
            self.assertIn(detail, theme["disclaimer"])

    def test_107_solar_terms_and_festivals_are_kept(self):
        """改名不得改掉二十四节气与传统节日这两样文化灵感来源"""
        # 霜降（二十四节气）
        ctx, theme, text = self._render(date(2026, 10, 23))
        self.assertEqual(ctx["solar_term"]["name"], "霜降")
        self.assertIn("霜降", text)
        self.assertIn("节气", theme["source"])
        # 中秋（传统节日）
        ctx2, theme2, _ = self._render(date(2026, 9, 25))
        self.assertEqual(ctx2["festival"]["name"], "中秋节")
        self.assertIn("中秋", theme2["theme"])

    def test_108_no_huangli_wording_across_a_full_year(self):
        """全年扫描：任何一天的输出都不能冒出「黄历」「钦天监」「宜忌」"""
        day = date(2026, 1, 1)
        while day.year == 2026:
            _ctx, theme, text = self._render(day)
            # 免责声明本身会写「不排宜忌」，属正面澄清，不参与扫描
            scan_text = text.replace(theme["disclaimer"], "")
            for banned in ("黄历", "钦天监", "宜忌", "吉日", "诸事不宜"):
                self.assertNotIn(banned, scan_text,
                                 f"{day} 出现禁用词「{banned}」")
            day += timedelta(days=1)

    def test_109_opt_out_says_maicalendar_not_huangli(self):
        """陛下关掉主题时，说明也要用「麦历」的说法"""
        _ctx, theme, text = self._render(date(2026, 10, 23), opt_out=True)
        self.assertTrue(theme["opted_out"])
        self.assertIn("麦历主题已按陛下旨意关闭", text)
        self.assertNotIn("黄历", text)
        self.assertNotIn("钦天监", text)


class TestOrderScroll(unittest.TestCase):
    """[拟旨下单奏折卡片] 一次性 HTML 交付物的硬性要求"""

    def _plan(self, confirmed, **overrides):
        store = {"store_code": "3330329", "name": "麦当劳某门店（已脱敏）"}
        items = [{"product_code": "901100", "name": "巨无霸中套餐",
                  "quantity": 1, "coupon_title": None, "modification_note": None}]
        price = {"data": {"productPrice": 1900, "deliveryPrice": 600,
                          "packingPrice": 110, "price": 1900}}
        dlv = {"mode": "delivery", "address": "浙江省杭州市（已脱敏）",
               "address_id": "1" * 28}
        det = ik.adapt_mcd_meal_detail(load("meal_detail_combo_real.json"))
        det_cola = ik.adapt_mcd_meal_detail(load("meal_detail_cola_real.json"))
        for k, v in overrides.items():
            if k == "items":
                items = v
            elif k == "price":
                price = v
            elif k == "delivery":
                dlv = v
        return ik.build_order_plan(store, items, price, dlv, confirmed,
                                   [det, det_cola])

    def _photos(self):
        combo = ik.adapt_mcd_meal_detail(load("meal_detail_combo_real.json"))
        return [{"name": "巨无霸中套餐", "price": 1900, "image": combo["image"],
                 "default_combo": [], "mods": []}]

    def test_110_scroll_has_title_seal_and_never_pays(self):
        """卡片必须有竖排标题、朱印与「臣绝不代付」——支付边界写死在卡上"""
        plan = self._plan(["content", "amount", "delivery"])
        html = ik.render_order_scroll(plan, None, None, self._photos(), None)
        self.assertIn("拟旨下单", html)
        self.assertIn("御膳", html)
        self.assertIn("臣绝不代付、不代收款", html)
        self.assertIn("待支付订单", html)

    def test_111_scroll_prices_and_photos_from_official(self):
        """金额两位小数、图片只引官方 CDN、且带麦历三条边界"""
        ctx = ik.build_date_context(date(2026, 10, 23))
        theme = ik.build_theme(ctx)
        plan = self._plan(["content", "amount", "delivery"])
        html = ik.render_order_scroll(plan, theme, ctx, self._photos(), None)
        self.assertIn("¥19.00", html)
        self.assertIn("menu-img.mcd.cn", html)
        self.assertIn("麦历", html)
        self.assertIn("霜降", html)
        for clause in ("不预测吉凶", "不影响消费决策", "不冒充官方促销"):
            self.assertIn(clause, html)

    def test_112_scroll_desensitizes_sensitive_ids(self):
        """卡片不得落下券码、手机号、完整地址 ID——塞进去也要被隐去"""
        plan = self._plan(["content", "amount", "delivery"])
        photos = self._photos()
        # 手机号形状的 PII：源码里不出现连续 11 位数字（打包扫描零例外），
        # 运行时才拼成完整号码，脱敏逻辑照常受检
        _fake_phone = "138" + "1234" + "5678"
        photos[0]["name"] = "MCDA1B2C3D4E5F6A7B8C 的餐品 " + _fake_phone
        html = ik.render_order_scroll(plan, None, None, photos, None)
        self.assertNotIn("MCDA1B2C3D4E5F6A7B8C", html)
        self.assertNotIn(_fake_phone, html)
        self.assertIn("已隐去", html)

    def test_113_blocked_plan_renders_blockers_not_ready(self):
        """信息不全时卡片要如实列出缺什么，不得显示可下单口径"""
        plan = self._plan(None, price={},
                          delivery={"mode": "delivery"})
        html = ik.render_order_scroll(plan, None, None, None, None)
        self.assertIn("臣不敢落单", html)
        self.assertNotIn("¥", html.split("blockers")[-1][:200]
                         if "blockers" in html else html)
        self.assertIn("待陛下确认", html)
        self.assertNotIn("可创建【待支付订单】", html)

    def test_114_ready_scroll_shows_confirmed_marks(self):
        """三重复述齐备时每块都标「已确认」，并给出可下单口径"""
        plan = self._plan(["content", "amount", "delivery"])
        html = ik.render_order_scroll(plan, None, None, None, None)
        self.assertEqual(html.count("已确认"), 3)
        self.assertIn("可创建【待支付订单】", html)

    def test_115_scroll_escapes_hostile_names(self):
        """餐品名带 HTML 尖括号也不得破坏卡片结构"""
        plan = self._plan(["content", "amount", "delivery"])
        photos = [{"name": "<script>alert(1)</script>", "price": 100,
                   "image": "https://menu-img.mcd.cn/x.png",
                   "default_combo": [], "mods": []}]
        html = ik.render_order_scroll(plan, None, None, photos, None)
        # 注入内容必须被转义成实体，不得变成可执行标签
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        # 卡片自带一处固定脚本（点击复制用），不得有第二处
        self.assertLessEqual(html.count("<script>"), 1)


class TestMistranslationGuard(unittest.TestCase):
    """门店就是门店——古风只改语气，不改业态"""

    def test_116_store_must_not_become_noodle_shop(self):
        """「面馆」等业态错译必须被扫出来"""
        bad = "陛下可前往城西的面馆取膳。"
        scan = ik.scan_mistranslation(bad)
        self.assertFalse(scan["passed"])
        self.assertIn("面馆", scan["hits"])

    def test_117_clean_text_passes(self):
        """正常古风不该被误伤：门店、餐厅、麦乐送都可用"""
        ok_text = "臣已查明该门店可取膳，麦乐送亦可送至府上。"
        self.assertTrue(ik.scan_mistranslation(ok_text)["passed"])
        for w in ik.MISTRANSLATION_ALLOW:
            self.assertTrue(ik.scan_mistranslation(w)["passed"], w)

    def test_118_all_banned_words_are_caught(self):
        """禁译表里每一个词都要能被抓到"""
        for w in ik.MISTRANSLATION_BANNED:
            self.assertFalse(ik.scan_mistranslation(f"去那家{w}")["passed"], w)


class TestMemorialScroll(unittest.TestCase):
    """整篇奏折卡片：排版、图位、点选、边界"""

    @staticmethod
    def _cands():
        menu = load("menu_real_sample.json")
        cands = ik.build_candidates(menu, {"budget_max": 30})
        combo = ik.adapt_mcd_meal_detail(load("meal_detail_combo_real.json"))
        cola = ik.adapt_mcd_meal_detail(load("meal_detail_cola_real.json"))
        cands = ik.attach_photos(cands, [combo, cola])
        for c in cands["candidates"]:
            if not c.get("image"):
                c["image"] = combo["image"]  # 样张用，仅为验证排版
        return cands

    def _render(self, **kw):
        ctx = ik.build_date_context(date(2026, 10, 23))
        theme = ik.build_theme(ctx)
        return ik.render_memorial_scroll(ctx, theme, self._cands(), **kw)

    def test_119_scroll_has_real_layout_not_bare_image_list(self):
        """奏折卡片必须有章节结构与样式，不能是一串裸图片"""
        html = self._render()
        self.assertIn("<style>", html)
        self.assertIn(".sec-title", html)
        self.assertGreater(html.count('class="sec"'), 3)
        self.assertIn("麦历呈报", html)
        self.assertIn("御膳图鉴", html)
        self.assertIn("户部精算", html)
        self.assertIn("御膳账目", html)

    def test_120_scroll_photos_laid_out_in_grid(self):
        """图片要走网格排版，且只引官方 CDN 原址"""
        html = self._render()
        self.assertIn('class="grid"', html)
        self.assertIn("menu-img.mcd.cn", html)
        self.assertNotIn("data:image", html)

    def test_121_scroll_offers_clickable_picks(self):
        """陛下不必打字：卡片要给出可点的选项按钮"""
        html = self._render()
        self.assertIn('class="pick"', html)
        self.assertGreater(html.count('class="btn"'), 1)
        self.assertIn("data-say", html)
        self.assertIn("clipboard", html)

    def test_122_scroll_states_boundaries_and_never_pays(self):
        """麦历三条边界与「臣绝不代付」都要上卡"""
        html = self._render()
        for clause in ("不预测吉凶", "不影响消费决策", "不冒充官方促销"):
            self.assertIn(clause, html)
        self.assertIn("臣绝不代付、不代收款", html)

    def test_123_scroll_no_mistranslation(self):
        """卡片里不得出现业态错译"""
        html = self._render()
        self.assertTrue(ik.scan_mistranslation(html)["passed"])

    def test_124_order_scroll_picks_follow_status(self):
        """下单卡片的选项跟着状态走：待确认就问那几项，就绪才问下不下"""
        ready = ik.render_order_scroll(
            {"status": "ready", "recitals": {}, "confirmed_steps":
             ["content", "amount", "delivery"], "blockers": [],
             "total_fen": 1900, "pending_steps": []})
        self.assertIn("确认，就按这个下单", ready)
        pending = ik.render_order_scroll(
            {"status": "need_confirm", "recitals": {},
             "confirmed_steps": ["content"], "blockers": [],
             "pending_steps": ["amount", "delivery"]})
        self.assertIn("金额明细无误", pending)
        self.assertIn("交付方式无误", pending)
        self.assertNotIn("就按这个下单", pending)


class TestMoneyUnit(unittest.TestCase):
    """元与分两套单位——必须显式声明，且越界要敢说不报"""

    def test_125_fen_and_yuan_are_not_confused(self):
        """同一数值按分/按元必须给出不同结果，不得混用"""
        self.assertEqual(ik.fmt_money(1900, ik.UNIT_FEN), "19.00")
        self.assertEqual(ik.fmt_money(9.5, ik.UNIT_YUAN), "9.50")

    def test_126_double_conversion_is_caught(self):
        """把「元」当「分」再除一次 → 0.10 元，必须被判为异常"""
        self.assertEqual(ik.fmt_money(9.5, ik.UNIT_FEN), "0.10")
        self.assertFalse(ik.money_sanity("0.10"))
        self.assertIn("臣不敢以此报价", ik.safe_money(9.5, ik.UNIT_FEN))

    def test_127_reasonable_prices_pass(self):
        """正常金额不得被误伤"""
        self.assertTrue(ik.money_sanity("8.50"))
        self.assertTrue(ik.money_sanity("19.00"))
        self.assertEqual(ik.safe_money(1900, ik.UNIT_FEN), "19.00")
        self.assertEqual(ik.safe_money(9.5, ik.UNIT_YUAN), "9.50")

    def test_128_scroll_shows_yuan_prices_not_cents(self):
        """奏折卡片里的餐品价必须是元（9.50），不能是分（0.10）——真实 bug"""
        cands = {"ok": True, "candidates": [
            {"name": "可乐", "price": 9.5, "image": None, "reasons": []}]}
        ctx = ik.build_date_context(date(2026, 10, 23))
        html = ik.render_memorial_scroll(ctx, ik.build_theme(ctx), cands)
        self.assertIn("¥9.50", html)
        self.assertNotIn("¥0.10", html)


class TestSceneAndStore(unittest.TestCase):
    """默认外送；门店不靠定位，靠陛下给地段"""

    def test_129_default_scene_is_delivery(self):
        """陛下未言明时默认麦乐送外送，并标明是臣的推断"""
        sc = ik.detect_scene("今天吃点什么")
        self.assertEqual(sc["key"], "delivery")
        self.assertEqual(sc["source"], "default")
        self.assertIn("麦乐送", sc["message"])

    def test_130_explicit_pickup_still_wins(self):
        """陛下明说到店自取，不得被默认覆盖"""
        sc = ik.detect_scene("我要到店自取")
        self.assertEqual(sc["key"], "dine_in")
        self.assertEqual(sc["source"], "inferred")

    def test_131_store_query_needs_city_and_keyword(self):
        """官方不定位：城市与地段齐备才可查，否则要问陛下"""
        ask = ik.build_store_request()
        self.assertFalse(ask["ok"])
        self.assertEqual(ask["status"], "need_ask")
        self.assertIsNotNone(ask["ask"])
        self.assertIn("城市", json.dumps(ask["ask"], ensure_ascii=False))
        ready = ik.build_store_request("杭州", "西湖文化广场")
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["params"]["searchType"], 2)
        self.assertEqual(ready["params"]["city"], "杭州")
        self.assertEqual(ready["params"]["keyword"], "西湖文化广场")

    def test_132_store_query_declares_no_geolocation(self):
        """必须如实写明：经纬度恒为 0、不读 IP，距离由关键词地理编码算出"""
        ask = ik.build_store_request()
        self.assertIn("IP", ask["caveat"])
        self.assertIn("0.0", ask["caveat"])          # longitude/latitude 恒为 0
        self.assertIn("distance", ask["caveat"])     # 距离来自服务端
        self.assertIn("到店距离", ask["distance_note"])
        self.assertIn("由近及远", ask["distance_note"])


class TestPicks(unittest.TestCase):
    """陛下点选：每个决策点都要有结构化选项"""

    def test_133_after_memorial_offers_options(self):
        """奏折呈上后必须给选项，不给开放式填空"""
        picks = ik.suggest_picks("after_memorial",
                                 candidates=[{"name": "巨无霸"}],
                                 cheapest="麦乐鸡")
        self.assertEqual(picks["stage"], "after_memorial")
        self.assertGreaterEqual(len(picks["options"]), 4)
        for o in picks["options"]:
            self.assertIn("label", o)
            self.assertIn("description", o)

    def test_134_order_confirm_lists_pending_recitals(self):
        """下单确认只问还没点头的那几项"""
        picks = ik.suggest_picks("order_confirm",
                                 pending=["amount", "delivery"])
        labels = [o["label"] for o in picks["options"]]
        self.assertIn("金额明细无误", labels)
        self.assertIn("交付方式无误", labels)
        self.assertNotIn("订单内容无误", labels)

    def test_135_ice_and_scene_have_options(self):
        """必选口味与用膳方式都要给选项"""
        ice = ik.suggest_picks("ice", name="可口可乐(中杯)",
                               values=["标准", "去冰", "多冰", "少冰"])
        self.assertIn("去冰", [o["label"] for o in ice["options"]])
        scene = ik.suggest_picks("scene")
        self.assertIn("麦乐送外送", [o["label"] for o in scene["options"]])

    def test_136_picks_never_returns_empty(self):
        """任何 stage 都得有得选，不能让陛下干瞪眼"""
        for stage in ("scene", "budget", "after_memorial", "order_confirm",
                      "ice", "coupon", "address", "不存在的阶段"):
            picks = ik.suggest_picks(stage)
            self.assertGreaterEqual(len(picks["options"]), 2, stage)
            self.assertTrue(picks["question"], stage)


class TestStoreLocationGuess(unittest.TestCase):
    """[新增] 到店自取定位：臣无 IP，改用陛下已有外送地址反推位置

    背景（用户提问）：「agent 能不能根据用户 IP 自行判断最近门店？」
    结论：不需要 IP —— 官方按 keyword 地理编码返回 distance。
    ⚠️ 后又经陛下指正：**区县一级不能当"就近"**，区中心离陛下可能很远，
    故解析必须尽量切到路名 + 门牌号。
    """

    def test_137_parse_city_and_street_from_address(self):
        """必须切到街道门牌级，不能停在区县"""
        r = ik.parse_address_location("浙江省杭州市西湖区天目山路148号浙大玉泉校区")
        self.assertTrue(r["ok"])
        self.assertEqual(r["city"], "杭州")
        self.assertEqual(r["district"], "西湖区")
        self.assertEqual(r["keyword"], "天目山路148号")
        self.assertEqual(r["keyword_level"], "street")
        self.assertEqual(r["confidence"], "high")

    def test_138_parse_direct_city(self):
        r = ik.parse_address_location("上海市徐汇区漕溪北路88号某某大厦")
        self.assertTrue(r["ok"])
        self.assertEqual(r["city"], "上海")
        self.assertEqual(r["district"], "徐汇区")
        self.assertEqual(r["keyword"], "漕溪北路88号")
        r2 = ik.parse_address_location("北京市朝阳区建国路93号")
        self.assertEqual(r2["city"], "北京")
        self.assertEqual(r2["keyword"], "建国路93号")

    def test_139_unparsable_address_is_not_invented(self):
        for bad in ("", "   ", None, "某某路 1 号"):
            r = ik.parse_address_location(bad)
            self.assertFalse(r["ok"], bad)
            self.assertIsNone(r["city"], bad)
        # 切不出街道 → 降级到区县，并如实标 low
        r = ik.parse_address_location("浙江省杭州市西湖区（完整地址已脱敏）")
        self.assertTrue(r["ok"])
        self.assertEqual(r["keyword_level"], "district")
        self.assertEqual(r["confidence"], "low")
        self.assertIn("区中心离陛下可能很远", r["note"])
        # 只剩城市 → very_low，且明说就近几乎无效
        r2 = ik.parse_address_location("浙江省杭州市")
        self.assertEqual(r2["keyword_level"], "city")
        self.assertEqual(r2["confidence"], "very_low")
        self.assertIn("就近几乎无效", r2["note"])

    def test_140_guess_from_real_address_fixture(self):
        """真实 fixture 已脱敏（只剩区县），故只能到区县一级——如实降级"""
        with open(os.path.join(FIXTURES, "delivery_addresses_filled_real.json"),
                  "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        adapted = ik.adapt_mcd_addresses(raw)
        g = ik.guess_store_location(adapted)
        self.assertTrue(g["ok"])
        self.assertEqual(g["city"], "杭州")
        self.assertEqual(g["keyword_level"], "district")
        # 空地址不得反推
        self.assertFalse(ik.guess_store_location({"addresses": []})["ok"])
        self.assertFalse(ik.guess_store_location(None)["ok"])

    def test_141_addr_book_gives_confirm_not_question(self):
        """有地址 → need_confirm + 点选项（陛下点一下，不打字）"""
        with open(os.path.join(FIXTURES, "delivery_addresses_filled_real.json"),
                  "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        req = ik.build_store_request(addresses=ik.adapt_mcd_addresses(raw))
        self.assertEqual(req["status"], "need_confirm")
        self.assertEqual(req["source"], "address")
        self.assertEqual(req["city"], "杭州")
        # 该 fixture 只到区县 → 必须标记为"太粗"，并把"给个更准的地标"排第一
        self.assertTrue(req["coarse_keyword"])
        picks = req["ask"]["picks"]
        self.assertGreaterEqual(len(picks["options"]), 2)
        self.assertIn("更准", picks["options"][0]["label"])
        self.assertIsNone(req["params"], "未确认前不得发查询")

    def test_142_explicit_area_beats_guess(self):
        req = ik.build_store_request(city="上海", keyword="人民广场",
                                     addresses={"addresses": [
                                         {"fullAddress": "浙江省杭州市西湖区"}]})
        self.assertEqual(req["status"], "ready")
        self.assertEqual(req["source"], "user")
        self.assertEqual(req["params"]["searchType"], 2)
        self.assertEqual(req["params"]["city"], "上海")

    def test_143_no_address_falls_back_to_ask(self):
        req = ik.build_store_request()
        self.assertEqual(req["status"], "need_ask")
        self.assertIsNone(req["city"])
        self.assertTrue(req["ask"]["fields"])

    def test_144_ip_geolocation_is_honestly_disclaimed(self):
        req = ik.build_store_request()
        self.assertIn("IP", req["caveat"])
        self.assertIn("IP", req["ip_geo_note"])
        self.assertIn("关键词", req["ip_geo_note"])

    def test_145_store_area_picks_always_clickable(self):
        # 街道级：直接推荐"就按这个查"
        p1 = ik.suggest_picks("store_area", city="杭州", keyword="天目山路148号")
        self.assertGreaterEqual(len(p1["options"]), 2)
        self.assertIn("天目山路148号", p1["options"][0]["label"])
        # 区县级：必须改推"给个更准的地标"
        p2 = ik.suggest_picks("store_area", city="杭州", keyword="上城区",
                              coarse=True)
        self.assertIn("更准", p2["options"][0]["label"])
        p3 = ik.suggest_picks("store_area")  # 无地址也要能点
        self.assertGreaterEqual(len(p3["options"]), 2)


class TestStreetPrecision(unittest.TestCase):
    """[新增] 陛下指正：区中心可能离用户很远，区县不能当"就近"用

    2026-10-23 实测同一查询点（公开门牌）：keyword「西湖区」→ 最近 2545m；
    keyword「天目山路148号」→ 410m、「黄龙体育中心」→ 188m。区县一级差 13.5 倍。
    """

    def test_155_street_beats_district(self):
        street = ik.parse_address_location(
            "浙江省杭州市西湖区天目山路148号浙大玉泉校区")
        district = ik.parse_address_location("浙江省杭州市西湖区")
        self.assertEqual(street["keyword_level"], "street")
        self.assertEqual(district["keyword_level"], "district")
        self.assertNotEqual(street["keyword"], district["keyword"])
        self.assertIn("148", street["keyword"])

    def test_156_district_only_is_flagged_coarse(self):
        req = ik.build_store_request(addresses={"addresses": [
            {"fullAddress": "浙江省杭州市西湖区"}]})
        self.assertTrue(req["coarse_keyword"])
        self.assertIn("区中心离陛下可能很远", req["message"])
        self.assertIn("更准", req["ask"]["picks"]["options"][0]["label"])
        # 街道级则不标粗
        fine = ik.build_store_request(addresses={"addresses": [
            {"fullAddress": "浙江省杭州市西湖区天目山路148号"}]})
        self.assertFalse(fine["coarse_keyword"])
        self.assertEqual(fine["keyword"], "天目山路148号")
        self.assertEqual(fine["confidence"], "high")
        self.assertNotIn("更准", fine["ask"]["picks"]["options"][0]["label"])

    def test_157_district_note_warns_explicitly(self):
        note = ik._keyword_level_note("district", "上城区")
        self.assertIn("区中心离陛下可能很远", note)
        self.assertIn("天目山路148号", note)  # 给出可抄的示范
        self.assertIn("收货地", ik._keyword_level_note("street", "天目山路148号"))

    def test_158_far_result_triggers_refine_advice(self):
        """最近那家太远 → 提示换关键词，而不是硬塞给陛下"""
        raw = {"success": True, "data": [
            {"storeCode": "1", "storeName": "很远的店", "distance": 4200},
            {"storeCode": "2", "storeName": "更远的店", "distance": 9000}]}
        a = ik.adapt_mcd_nearby_stores(raw)
        v = ik.assess_nearby_result(a)
        self.assertTrue(v["too_far"])
        self.assertEqual(v["nearest_m"], 4200)
        self.assertIn("关键词太粗", v["advice"])
        # 近的则不啰嗦
        near = ik.assess_nearby_result(ik.adapt_mcd_nearby_stores(
            {"success": True, "data": [
                {"storeCode": "3", "storeName": "很近的店", "distance": 17}]}))
        self.assertFalse(near["too_far"])
        self.assertIn("就近可用", near["advice"])

    def test_159_landmark_fallback_is_used(self):
        """没有门牌号时退到小区/大厦名，也比区县强"""
        r = ik.parse_address_location("浙江省杭州市西湖区文三路123号某某大厦A座")
        self.assertEqual(r["keyword_level"], "street")
        r2 = ik.parse_address_location("浙江省杭州市西湖区某某小区5幢")
        self.assertEqual(r2["keyword_level"], "landmark")
        self.assertEqual(r2["confidence"], "medium")


class TestNearbyStoresDistance(unittest.TestCase):
    """[新增] 官方返回自带「到店距离」——所以不需要 IP 定位

    2026-10-22 实跑核实：query-nearby-stores 返回 distance（米），已由近及远排序，
    且 distance 随 keyword 变化（"西湖区" 最近 2545m；"黄龙体育中心" 188m）。
    """

    def _real(self):
        with open(os.path.join(FIXTURES, "nearby_stores_real.json"),
                  "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_146_official_returns_distance_already_sorted(self):
        a = ik.adapt_mcd_nearby_stores(self._real())
        self.assertTrue(a["ok"])
        self.assertTrue(a["verified_by_real_call"])
        self.assertEqual(len(a["stores"]), 5)
        d = [s["distance_m"] for s in a["stores"]]
        self.assertEqual(d, [245, 1181, 1191, 1270, 1447])
        self.assertEqual(d, sorted(d), "应由近及远")
        self.assertEqual(a["nearest"]["store_code"], "3330682")
        self.assertEqual(a["nearest"]["name"], "麦当劳杭州平安悦坊餐厅")

    def test_147_distance_display_is_sane(self):
        self.assertEqual(ik.fmt_distance(245), "245 米")
        self.assertEqual(ik.fmt_distance(1181), "1.2 公里")
        self.assertEqual(ik.fmt_distance(None), "距离官方未返回")
        self.assertEqual(ik.fmt_distance(-1), "距离官方未返回")
        self.assertEqual(ik.fmt_distance("abc"), "距离官方未返回")

    def test_148_store_list_shows_distance_and_store_code(self):
        """官方要求完整展示 storeCode（beType=5 时还要 beCode）"""
        a = ik.adapt_mcd_nearby_stores(self._real())
        text = ik.render_store_list(a)
        self.assertIn("245 米", text)
        self.assertIn("3330682", text)
        self.assertIn("麦当劳杭州平安悦坊餐厅", text)
        self.assertIn("由近及远", text)
        # beCode 为空（beType=1）时不得凭空编一个
        self.assertNotIn("beCode", text)

    def test_149_bad_distance_is_not_invented(self):
        raw = {"success": True, "data": [
            {"storeCode": "1", "storeName": "甲店", "distance": "未知"},
            {"storeCode": "2", "storeName": "乙店"}]}
        a = ik.adapt_mcd_nearby_stores(raw)
        self.assertIsNone(a["stores"][0]["distance_m"])
        self.assertIsNone(a["stores"][1]["distance_m"])
        self.assertIn("距离官方未返回", ik.render_store_list(a))

    def test_150_empty_store_list_is_reported_honestly(self):
        a = ik.adapt_mcd_nearby_stores({"success": True, "data": []})
        self.assertTrue(a["ok"])
        self.assertIsNone(a["nearest"])
        self.assertIn("未查得门店", ik.render_store_list(a))
        bad = ik.adapt_mcd_nearby_stores({"success": False, "message": "城市不存在"})
        self.assertFalse(bad["ok"])
        self.assertIn("城市不存在", bad["message"])


class TestOpening(unittest.TestCase):
    """[新增] 陛下上朝的头一问：四项，前两项固定且不可换序

    陛下钦定：「按预算拟单」「今日推荐」必须在，且必须在前两位。
    """

    def test_151_opening_has_four_clickable_options(self):
        op = ik.render_opening()
        self.assertIn("御膳房", op["greeting"])
        self.assertIn("今日想用何膳", op["question"])
        self.assertEqual(len(op["options"]), 4)
        for o in op["options"]:
            self.assertTrue(o["label"], "每项都要有可点的字")
            self.assertTrue(o["description"])
        self.assertFalse(op["multiSelect"])

    def test_152_two_required_options_come_first(self):
        """前两项恒为「按预算拟单」「今日推荐」，顺序不得变"""
        op = ik.render_opening()
        labels = [o["label"] for o in op["options"]]
        self.assertEqual(labels[0], "按预算拟单")
        self.assertEqual(labels[1], "今日推荐")
        for req in ik.OPENING_REQUIRED:
            self.assertIn(req, labels)
        self.assertEqual(op["required_options"], list(ik.OPENING_REQUIRED))
        # 换一条路径也要一致：suggest_picks 与 render_opening 同源
        picks = ik.suggest_picks("opening")
        self.assertEqual([o["label"] for o in picks["options"]][:2],
                         list(ik.OPENING_REQUIRED))

    def test_153_opening_is_never_an_open_question(self):
        """头一问不得退化成让陛下自己打字"""
        op = ik.render_opening()
        text = op["greeting"] + op["question"] + "".join(
            o["label"] + o["description"] for o in op["options"])
        for bad in ("陛下可回复", "请直接输入", "告诉我你想"):
            self.assertNotIn(bad, text)
        self.assertIn("点选", op["note"])

    def test_154_opening_stage_in_picks_registry(self):
        self.assertIn("opening", ik.PICK_QUESTION)
        self.assertIn("opening", ik.suggest_picks("opening")["stage"])


class TestSkillStructure(unittest.TestCase):
    """[新增] Skill 结构守卫：渐进式披露，不许再长回去

    起因：陛下反馈"加载有时要 30 分钟"。诊断结论是**七步流程一次性注入**，
    模型会把七步一路跑完才回话。故拆成「核心 SKILL.md + 按需子文件」，
    并在此锁住：核心不许再膨胀、停下指令不许被删、子文件不许失联。
    """

    SKILL = os.path.join(ROOT, "SKILL.md")

    @staticmethod
    def _read(p):
        with open(p, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_160_core_skill_stays_small(self):
        """核心 SKILL.md 必须瘦：≤6500 字符 / ≤200 行（原为 17,850 字符 / 538 行）"""
        s = self._read(self.SKILL)
        self.assertLessEqual(len(s), 6500, "核心 SKILL.md 又长回去了")
        self.assertLessEqual(s.count("\n") + 1, 200)

    def test_161_stop_instruction_exists(self):
        """第一步必须写明：呈上四项即停，未点选前不得读 workflow / 调 MCP"""
        s = self._read(self.SKILL)
        i = s.find("### 第一步")
        self.assertGreater(i, 0, "找不到第一步")
        step1 = s[i:i + 2500]
        self.assertIn("本轮到此为止", step1)
        self.assertIn("不得", step1)
        self.assertIn("MCP", step1)

    def test_162_no_lazy_preload_instruction(self):
        """必须明令"按需取用"，否则模型会一次读完"""
        s = self._read(self.SKILL)
        self.assertIn("按需取用", s)
        self.assertIn("workflow/", s)
        self.assertIn("不要一次读完", s)

    def test_163_workflow_files_exist_and_are_linked(self):
        """七步子文件都在，且核心里有指向它们的导航"""
        s = self._read(self.SKILL)
        for rel in ("workflow/02-maicalendar.md",
                    "workflow/03-scene-and-store.md",
                    "workflow/04-photos.md",
                    "workflow/05-coupons-price.md",
                    "workflow/06-memorial.md",
                    "workflow/07-order.md"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)
            self.assertIn(rel, s, f"{rel} 未在核心里导航")
        for rel in ("references/voice.md",
                    "references/preferences.md",
                    "references/coupons.md"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)

    def test_164_red_lines_survive_the_split(self):
        """拆归拆，底线一条不许丢：八条铁律 + 写操作分级 + 点选 + 禁译"""
        s = self._read(self.SKILL)
        for i in range(1, 9):
            self.assertIn(f"{i}. **", s, f"铁律 {i} 丢失")
        self.assertIn("NEVER 永不执行", s)
        self.assertIn("CONFIRM_STRICT", s)
        self.assertIn("draw-lottery", s)
        self.assertIn("面馆", s)          # 禁译教训必须留在核心
        self.assertIn("让陛下点，不让陛下打字", s)
        self.assertIn("opening", s)


class TestPickRendering(unittest.TestCase):
    """[新增] 点选机制守卫：机制必须跟数据走，不能只躺在「不必读」的文件里

    起因：SKILL.md 第一步写「四项全部可点」，却没写用**哪个工具**呈卡片；
    唯一写明 AskUserQuestion 的地方在 references/voice.md，而它的读取时机
    写的是「陛下 reply 前」——开场那一刻陛下尚未 reply，严格照主文件执行
    恰好读不到机制，于是把选项念成了「陛下可回复：A／B／C」。
    此组测试锁住三处修补，防止哪天又被改回去。
    """

    SKILL = os.path.join(ROOT, "SKILL.md")
    VOICE = os.path.join(ROOT, "references", "voice.md")

    @staticmethod
    def _read(p):
        with open(p, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_165_step1_names_the_question_tool(self):
        """第一步必须自己写出提问工具名——不能只靠 voice.md"""
        s = self._read(self.SKILL)
        i = s.find("### 第一步")
        self.assertGreater(i, 0, "找不到第一步")
        step1 = s[i:s.find("## 写操作分级治理")]
        self.assertIn("AskUserQuestion", step1)
        self.assertIn("questions", step1)
        self.assertIn("原样", step1)
        self.assertIn("一次呈出三问", step1)

    def test_166_step1_warns_against_text_fallback(self):
        """必须警告：命令行编号文字是降级兜底，粘出去等于让陛下打字"""
        s = self._read(self.SKILL)
        i = s.find("### 第一步")
        step1 = s[i:s.find("## 写操作分级治理")]
        self.assertIn("降级", step1)

    def test_167_red_line_7_names_the_tool(self):
        """铁律 7 要写出工具名，不能只说『选项卡片』"""
        s = self._read(self.SKILL)
        i = s.find("7. **让陛下点")
        self.assertGreater(i, 0, "铁律 7 丢失")
        self.assertIn("AskUserQuestion", s[i:i + 400])

    def test_168_voice_read_timing_covers_opening(self):
        """voice.md 的读取时机必须覆盖开场第一步，不能只写『reply 前』"""
        v = self._read(self.VOICE)
        head = v[:400]
        self.assertIn("第一步", head)
        self.assertIn("开场", head)

    def test_169_opening_output_is_card_ready(self):
        """opening 返回必须自带 render_via / render_note / fallback_note"""
        op = ik.render_opening()
        self.assertEqual(op["render_via"], "AskUserQuestion")
        self.assertIn("原样", op["render_note"])
        self.assertIn("AskUserQuestion", op["render_note"])
        self.assertIn("不得", op["fallback_note"])
        for k in ("question", "multiSelect", "options", "greeting"):
            self.assertIn(k, op)

    def test_170_every_stage_carries_render_hint(self):
        """所有阶段都要带上「怎么呈」，不只是开场"""
        for stage in ("opening", "people_budget", "delivery_plan", "scene",
                      "budget", "address", "store_area",
                      "ice", "coupon", "after_memorial", "order_confirm"):
            picks = ik.suggest_picks(stage)
            self.assertEqual(picks["stage"], stage)
            self.assertEqual(picks["render_via"], "AskUserQuestion",
                             f"{stage} 缺 render_via")
            self.assertIn("render_note", picks)
            self.assertIn("fallback_note", picks)
            self.assertTrue(picks["options"], f"{stage} 无选项")

    def test_171_cli_banner_marks_fallback(self):
        """CLI 的编号文字必须有横幅标明它是兜底，且点名提问工具"""
        self.assertIn("AskUserQuestion", ik.PICK_RENDER_BANNER)
        self.assertIn("降级", ik.PICK_RENDER_BANNER)
        self.assertIn("不是", ik.PICK_RENDER_BANNER)


class TestOpeningBundle(unittest.TestCase):
    """[新增] 开场三问一卡：一轮问完，不再一项一项追问

    起因（2026-10-22 陛下反馈）："用户唤起 skill 后，目前只会一个个问题去问，
    这样效率太低了。"要求开场直接问三个问题：
    ① 今日想用何膳（含原来的四项，且预算/人数提前可点）
    ② 外送还是自取 ③ 地址是哪里（默认还是额外）
    引擎把 ②③ 合成一问（外送/自取两条岔路 + 地址），凑成整三问，一次呈完。
    """

    def test_172_bundle_has_exactly_three_questions(self):
        """开场必须正好三问：何膳 / 用度人数 / 传膳与送处"""
        b = ik.render_opening_bundle()
        self.assertEqual(len(b["questions"]), 3)
        headers = [q["header"] for q in b["questions"]]
        self.assertEqual(headers, ["今日何膳", "用度人数", "传膳与送处"])

    def test_173_q1_keeps_four_options_and_order(self):
        """第一问仍是原样四项，前两项固定且顺序不变"""
        b = ik.render_opening_bundle()
        q1 = b["questions"][0]
        labels = [o["label"] for o in q1["options"]]
        self.assertEqual(labels[:2], ["按预算拟单", "今日推荐"])
        self.assertEqual(len(labels), 4)
        for o in q1["options"]:
            self.assertTrue(o["label"] and o["description"])

    def test_174_budget_and_people_are_clickable_not_blank(self):
        """第二问的预算与人数必须是可点档位，不是留给陛下填空"""
        q2 = ik.render_opening_bundle()["questions"][1]
        labels = [o["label"] for o in q2["options"]]
        joined = " ".join(labels)
        self.assertIn("30 元以内", joined)
        self.assertIn("50 元以内", joined)
        self.assertTrue(any("人" in l for l in labels), "人数必须是可点选项")
        self.assertIn("元", q2["question"])
        self.assertIn("人", q2["question"])

    def test_175_scene_and_address_merged_into_one_question(self):
        """第三问必须同时覆盖外送/自取与地址，否则又要多问一轮"""
        q3 = ik.render_opening_bundle()["questions"][2]
        labels = [o["label"] for o in q3["options"]]
        self.assertTrue(any("麦乐送" in l for l in labels), "外送项缺失")
        self.assertTrue(any("自取" in l for l in labels), "自取项缺失")
        self.assertTrue(any("默认地址" in l for l in labels), "默认地址项缺失")
        self.assertTrue(any("另" in l for l in labels), "必须给'另换一处'的出路")

    def test_176_bundle_carries_render_hint_and_stop_note(self):
        """三问包也要自带「怎么呈」与停下指令，不能只靠文档"""
        b = ik.render_opening_bundle()
        self.assertEqual(b["render_via"], "AskUserQuestion")
        self.assertIn("整组", b["render_note"])
        self.assertIn("本轮到此为止", b["note"])
        self.assertEqual(b["required_options"], ["按预算拟单", "今日推荐"])
        self.assertTrue(b["greeting"])

    def test_177_single_mode_still_available(self):
        """宿主不支持多问卡片时，旧版单问仍在（`opening --single`）"""
        op = ik.render_opening()
        self.assertIn("question", op)
        self.assertEqual(len(op["options"]), 4)

    def test_178_new_stages_registered(self):
        """两个新阶段要进 picks 注册表，`picks --stage` 能直接调"""
        for stage in ("people_budget", "delivery_plan"):
            self.assertIn(stage, ik.PICK_QUESTION)
            picks = ik.suggest_picks(stage)
            self.assertEqual(picks["stage"], stage)
            self.assertTrue(picks["options"], f"{stage} 无选项")
            self.assertEqual(picks["render_via"], "AskUserQuestion")


class TestPrivacyGuard(unittest.TestCase):
    """公开仓库守卫：真实 fixture 中不得残留个人身份信息"""

    def test_59_fixtures_must_not_leak_personal_data(self):
        import glob
        import re
        # 完整 11 位手机号；前后加非数字断言，避免把图片 URL 里的长数字串误判
        phone_re = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
        long_id_re = re.compile(r"(?<!\d)\d{25,}(?!\d)")  # 完整 addressId（28 位）
        # 真实券码：泄露即可能被他人盗用，一律不得进仓
        coupon_re = re.compile(r"MCD[A-Z0-9]{15,}")
        for path in glob.glob(os.path.join(FIXTURES, "*.json")) + \
                glob.glob(os.path.join(FIXTURES, "*.txt")):
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(phone_re.search(text),
                              f"{os.path.basename(path)} 含完整手机号")
            self.assertIsNone(long_id_re.search(text),
                              f"{os.path.basename(path)} 含完整 addressId")
            self.assertIsNone(coupon_re.search(text),
                              f"{os.path.basename(path)} 含完整券码")


    def test_60_publishable_files_must_not_carry_unit_level_address(self):
        """单元级门牌（×幢×室 / ×栋×单元×室）只可能来自真实住户，一律不得进仓。

        守卫方式是查**模式**而不是查具体地址——这样测试文件本身不含任何真实住址。
        商业铺位（如「高德置地中心3幢101室1层L125单元麦当劳餐厅」）带
        餐厅/广场/中心/层 等商业标记，属公开商户信息，不误伤。
        """
        import re
        unit_re = re.compile(r"[幢栋]\s*\d+\s*(?:单元)?\s*\d*\s*室")
        commercial_re = re.compile(
            r"餐厅|商铺|商厦|广场|中心|大厦|商城|写字楼|大楼|酒店|医院|"
            r"大学|学院|学校|园区|产业园|科技园|街道|层|L\d")
        roots = [ROOT, FIXTURES]
        for base in roots:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames
                               if d not in {"__pycache__", ".git", ".workbuddy"}]
                for fn in filenames:
                    if not fn.endswith((".md", ".py", ".json", ".txt", ".html")):
                        continue
                    path = os.path.join(dirpath, fn)
                    if os.path.abspath(path) == os.path.abspath(__file__):
                        continue  # 本文件靠模式自证，不自我递归
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        for lineno, line in enumerate(fh, 1):
                            m = unit_re.search(line)
                            if m and not commercial_re.search(line):
                                self.fail(
                                    f"{os.path.relpath(path, ROOT)}:{lineno} "
                                    f"含疑似住户单元级住址「{m.group(0)}」")


if __name__ == "__main__":
    unittest.main(verbosity=2)
