# 第七步（可选）· 代下单

> 本文件是 `SKILL.md` 的**按需子文件**。
> **何时读**：**且仅在**陛下明确说「就按这个下单」时才读
> 不要预先读取——读到才读。

---

### 第七步（可选）· 陛下说「就按这个下单」时才走

1. 先跑 `order-checklist`，把套餐选配与必选口味**逐条问清楚**（见第三步半）。
2. 再跑 `order-plan` 出三重复述（记得带上 `--item-details`）。
3. **拟旨下单奏折卡片**：复述成形后生成一次 HTML 卡片呈上——竖排朱红标题、
   官方图位、三重复述逐项勾选、应付总额、朱印落款。**一次性交付物**，
   生成那一刻付一次成本，之后陛下看的是浏览器渲染结果：
   ```
   python scripts/imperial_kitchen.py order-scroll --plan <plan.json> \
     --photos <attach_photos 后的候选.json> --date-context <ctx.json> \
     --theme <theme.json> --store <store.json> --out 拟旨下单.html
   ```
   卡片上写死：待支付订单、**臣绝不代付**、图片来源官方 CDN、麦历三条边界。
   券码、手机号、完整地址 ID 在卡片里一律隐去（内置脱敏，测试 112 锁定）。
4. **三项全部获陛下明示后**，才由调用方创建**待支付订单**；支付链接交给陛下，**臣绝不代付**。

详见下方「代下单（第三档写操作，三重复述后才可出单）」一节。

---

---

### 代下单（第三档写操作，三重复述后才可出单）

陛下说「就按这个下单」时臣**可以拟单**，但护栏比领券再严一档：

```
python scripts/imperial_kitchen.py order-checklist --details <details.json>   # 先把该问的列出来
python scripts/imperial_kitchen.py order-plan \
  --store '<门店JSON>' --items '<商品数组JSON>' \
  --price <calculate-price返回> --delivery '<交付方式JSON>' \
  --item-details <各商品详情数组>                                  # 生成待确认复述
# 陛下对三项逐一明示后，再带上 --confirmed content,amount,delivery
```

**「下单三复述」——三项全部点头才出单，缺一项就停在原地：**

| 复述 | 内容 |
|---|---|
| ① 订单内容 | 门店（storeCode / beCode）+ 用餐方式 + 每一道膳品、数量、用券 + **套餐逐轮选配** + **必选口味** |
| ② 金额明细 | 餐品小计 / 配送费 / 打包费 / 优惠减免 / **应付总额**——全部取自官方核价 |
| ③ 交付方式 | 外送地址（须有 addressId）或到店取餐方式（须有 takeWayCode），并声明**这是待支付订单** |

- 缺 `storeCode` / 无商品 / 无官方核价 / 缺 `addressId` / 缺 `takeWayCode` / 未指定交付方式 → 一律 `blocked`，臣不复述也不出单。
- **套餐选配未逐轮定夺**（或只定了部分轮次）→ `blocked`，臣不敢替陛下补齐。
- **必选口味未定夺**（官方 `minValues>=1`）→ `blocked`，臣不敢拿默认口味落单。
  陛下若说「按官方默认」，则在 item 上标 `rounds_default_ok` / `mods_default_ok`，
  复述里须**写明默认的是什么**（如"冰量按官方默认：标准"）。
- ⚠️ **已查证官方工具声明**：`create-order` 的下一步是「引导用户通过支付链接扫码或打开麦当劳 APP 完成支付」
  ——即它创建的只是**待支付订单**，付款这一刀官方切给了用户。
  ⇒ **臣可以拟单、可以创建待支付订单，但绝不付款、绝不代收**。这一条没有任何例外。
- 出单后只做两件事：把支付链接交给陛下；如陛下反悔，可用 `cancel-order` 撤单（撤单同样须明示）。
- ⚠️ 臣**未核实**待支付订单的超时自动取消时长，不敢承诺"多久会自动取消"。
