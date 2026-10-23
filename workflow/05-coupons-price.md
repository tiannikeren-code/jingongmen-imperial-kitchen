# 第四步 · 户部核算 ／ 第五步 · 核对御膳账目

> 本文件是 `SKILL.md` 的**按需子文件**。
> **何时读**：要查券、要核价时才读
> 不要预先读取——读到才读。

---

### 第四步 · 户部核算
```
mcp__mcd-mcp__query-store-coupons        # 指定门店可用券
mcp__mcd-mcp__query-my-coupons           # 陛下卡包（注意：不保证本单可用）
python scripts/imperial_kitchen.py coupons --coupons <c.json> --candidates <cands.json> --request <req.json>
```
**先本地粗筛，再交给官方核价**——不要把全部组合丢给 MCP。

### 第五步 · 核对御膳账目
```
mcp__mcd-mcp__calculate-price            # 只读核价，不产生订单
python scripts/imperial_kitchen.py verify-price --verified <v.json>
```
- ⚠️ **两套单位，务必分清**（2026-10-23 实测翻车：餐品被显示成 0.10 元）：
  | 来源 | 字段 | 单位 | 例 |
  |---|---|---|---|
  | `calculate-price` | `productPrice`/`price`/`deliveryPrice` | **分** | `1900` = 19.00 元 |
  | `query-meals` | `currentPrice`/`price` | **元**（常为字符串） | `'28.5'` = 28.5 元 |
  引擎以 `fmt_money(value, unit)` 显式声明单位，**禁止凭变量名猜**。
- 显示前必过合理性校验（0.5–2000 元）；越界即判为换算错误，输出
  "金额异常，疑为单位换算有误，臣不敢以此报价"，**绝不把 0.19 元端上去**。
- 未取得官方核价的方案，标注"未核验"，不作推荐依据。
