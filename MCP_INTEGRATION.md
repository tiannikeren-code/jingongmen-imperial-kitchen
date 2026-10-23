# 麦当劳 MCP 集成说明

本文档记录「金拱门御膳房」实际使用的麦当劳官方 MCP 工具、调用顺序、真实调用结果与错误处理。

**所有工具名称与调用结果均来自当前开发环境真实可用的 `mcd-mcp`，未照搬他人作品的工具清单。**

---

## 一、MCP 服务

| 项 | 值 |
|---|---|
| 服务地址 | `https://mcp.mcd.cn` |
| 传输方式 | `streamablehttp` |
| 鉴权 | `Authorization: Bearer <Token>`（Token 由用户在控制台申请，本项目不含任何真实 Token） |
| 官方参考仓库 | https://github.com/M-China/mcd-mcp-server |
| 环境中可用工具总数 | 35 |

---

## 二、实际调用的工具

| 工具名称 | 用途 | 是否实际调用成功 | 验证依据 |
|---|---|:---:|---|
| `query-nearby-stores` | 查询到店自取可点餐门店，取 `storeCode` | ✅ 成功 | 返回杭州 5 家门店，`traceId: 11cbff6d8dea6a817d62636d94cd724f`，时间 2026-10-21 19:19:34；**2026-10-22 复核：返回自带 `distance`（米）且已由近及远排序**，`traceId: f4aa4001fda8516b815ba5171d10691b` / `83a57ea17490a5316507702829843d52` |
| `query-meals` | 查询门店真实菜单与官方标价 | ✅ 成功 | 返回 15 个分类、120+ 餐品，`traceId: 3bc4b2cbe9091b75879c5ac3d125b582`，时间 19:19:42 |
| `query-store-coupons` | 查询指定门店可用优惠券 | ✅ 成功（**返回空列表**） | `data: []`，`traceId: 923ee97cab1493f46c6b204ecb79c33e`，时间 19:20:27 |
| `query-my-coupons` | 查询用户卡包 | ✅ 成功（**返回空**） | 返回「暂无可用优惠券」 |
| `calculate-price` | 官方核价（只读，不产生订单） | ✅ 成功 | 巨无霸 2650 分 + 中薯条 1450 分 = 4100 分（41.00 元），`traceId: e0ab376a79435f6d84c9947c469a1569`，时间 19:20:35 |
| `campaign-calendar` | 查询官方营销活动日历 | ✅ 成功 | 返回 2026-10-21 当日多条真实活动（麦当劳 X PEACEMINUSONE、韩式蘸酱上新、G-DRAGON 联动等） |

### 写操作分级：永不执行 / 确认后执行 / 三重复述后执行

| 档位 | 工具 | 规则 |
|---|---|---|
| **NEVER 永不执行** | `draw-lottery` | 消耗账号资产且无撤销路径，任何情况下都不执行 |
| **CONFIRM 确认后执行** | `auto-bind-coupons` / `delivery-create-address` / `cancel-order` | 免费或可撤销。臣逐字复述 → 陛下明示 → 才由调用方执行 |
| **CONFIRM_STRICT 三重复述后执行** | `create-order` / `mall-create-order` / `party-order-create` | **订单内容 / 金额明细 / 交付方式**三项全部点头才出单；**只出待支付单，绝不付款** |

**下单为何能进 CONFIRM_STRICT 而不是 NEVER（已查证官方工具声明）**：

> `create-order` 官方声明的下一步是「引导用户：您可以通过支付链接扫码或者打开麦当劳 APP 完成支付」。

即 `create-order` 创建的是**待支付订单**，付款这一刀官方切给了用户。
**「创建订单」与「付款」是两件事**，不该同等对待；臣绝不代付这一条不变。

> **为什么不一律禁止**：领券免费且几乎无损失；下单花钱，但官方把付款留给了用户——
> 真正不可逆、不可撤销的只有抽奖一类。
> 把领券与下单混为一档，结果是陛下还得自己打开小程序领券、自己照抄菜单下单，推荐链路断在这里。
> 分级不等于放松——**不静默下单、不代付款**这两条底线没有动。

### 其余未调用的工具（及原因）

| 工具 | 未调用的原因 |
|---|---|
| `list-nutrition-foods` | 官方菜单未随餐品返回营养字段，本项目不推断营养信息，暂不使用 |

### 外送链路新增实跑验证（2026-10-22）

| 工具名称 | 用途 | 是否实际调用成功 | 验证依据 |
|---|---|:---:|---|
| `delivery-query-addresses` | 查询用户配送地址簿，取 `addressId` | ✅ 成功（**返回空列表**） | `data.addresses: []`，`traceId: d897f2c0b4076ea56cf53f0683cc7670`，时间 10:06:48 |
| `query-meals`（beType=2） | 验证外送菜单查询 | ❌ **被官方拒绝** | `code=600048`「外送场景下，beType=2/5/6时必传beCode」，`traceId: 244496c05d3473af51b72779e633fe46`，时间 10:07:28 |
| `delivery-query-stores` | 查询可配送门店与 `beCode` | ❌ **被官方拒绝** | `code=400`「addressId地址ID不能为空」，`traceId: 8b8a341d3b57722775eafcf9ab502699`，时间 10:08:15 |

上述两次失败是真实报错（`traceId` 已留痕），恰好反向证明了两条硬约束：① 外送必传 `beCode`；② `addressId` 必须来自官方地址簿。

### 外送链路二次实跑（2026-10-22，用户在账户中添加配送地址后）✅ 全通

| 工具名称 | 用途 | 是否实际调用成功 | 验证依据 |
|---|---|:---:|---|
| `delivery-query-addresses` | 取 `addressId` | ✅ 成功 | 返回 1 条地址，`traceId: 92864acc3909b19aab5eaf7a885eb855`，时间 10:54:27 |
| `delivery-query-stores`（beType=2） | 取 `storeCode` + **`beCode`** | ✅ 成功 | 3 家可配送门店，含 `beCode=333032902`，`traceId: 02c8a4614b5ec22bac84d5270b025d5f`，时间 10:54:36 |
| `query-meals`（beType=2 + beCode） | 外送菜单 | ✅ 成功 | 14 分类 / 100+ 餐品，`traceId: bece996d81819ee248bbc40719c5c1fe`，时间 10:54:47 |
| `calculate-price`（beType=2 + beCode） | 外送核价 | ✅ 成功 | 餐品 4400 + 配送费 600 + 打包费 190 = 5190 分，`traceId: 0f53f46475392aacb0ddbc4cb6edd3a4`，时间 10:55:20 |
| `available-coupons` | 可领取券列表 | ✅ 成功 | 3 张真实券，`traceId` 见 fixture |
| `query-store-coupons`（beType=2） | 外送门店券 | ✅ 成功（**返回空列表**） | `data: []`，`traceId: 34b72d034fbc61f56e8418d37fc60a10` |
| `query-meal-detail`（beType=2，单品 `901100`） | 取餐品图片 + 可特调 | ✅ 成功 | `data.image = https://menu-img.mcd.cn/.../MS_901100_600_1749174931903.png`，`supportModify=true`，`traceId: 4d8a566d577273d79db41ef56c72b923`，时间 11:17:24 |
| `query-meal-detail`（beType=2，套餐 `9900003001`） | 取套餐图片 + 选配轮次 | ✅ 成功 | `data.image = .../MS_9900003001_600.png`，3 轮选配（巨无霸 / 中薯条 / 可口可乐中杯 均为 `isDefault=1`），`traceId: e22ab473bf30f334b4fc7b516d45eb65`，时间 11:18:17 |

**关键实测结论一（图片）**：`query-meals` 菜单列表**不返回任何图片字段**（到店、外送均如此，fixture 中 0 处 `image`）。
餐品图片只能由 `query-meal-detail` 的 `data.image` 取得。这是「御膳图鉴」必须逐道调用详情接口的直接依据。

**关键实测结论三（饮品的必选口味）**（2026-10-22 实跑 `query-meal-detail`，可口可乐中杯 `903050`，`traceId: 7fdbf22a25ca86905aa957ee08894ba5`）：

```json
"modification": {"items": [{"maxValues": 1, "minValues": 1, "values": [
  {"name": "标准", "selectedQuantity": 1}, {"name": "去冰"}, {"name": "多冰"}, {"name": "少冰"}]}]}
```

- `minValues=1` 意味着**必须选一项**，官方默认「标准」。⇒ **下单前不问，陛下拿到的就是加冰的。**
- 官方展示规则要求"不要主动展开特调选项"——那是**浏览时**不刷屏；进入下单环节必须逐条问，
  否则默认值一落单就改不回来。本项目据此新增 `order-checklist`，把"该问什么"列成清单。

**关键实测结论四（"无糖"不是选项）**（同次实跑 + 菜单比对）：

- 这一杯可乐的官方数据里**没有无糖选项**——只有冰量四项。
- 「无糖可口可乐」是**另一个独立商品**：编码 `903071`，现价 11 元（2026-10-22 菜单实跑）。
- ⇒ 陛下若要无糖，是**换一道膳品**，不是改一个选项。臣必须说明这一点，不得假装能改选项。

**关键实测结论二（价格）**：外送价格**高于**到店自取。同一组合（巨无霸 + 中薯条）到店核价 **41.00 元**，外送核价 **51.90 元**（餐品贵 3.00 + 配送费 6.00 + 打包费 1.90）。这正是本项目坚持区分场景口径的原因。

> ⚠️ 隐私处理：真实返回含完整配送地址、联系人与 `addressId`。本项目**只保留脱敏后的 fixture**
> （地址保留至区、姓名打码、电话官方已脱敏、`addressId` 掩码），并有测试用例
> `test_59` 扫描全量 fixture，禁止完整手机号与完整 `addressId` 进入公开仓库。

### 代领券令（`auto-bind-coupons`）编排 —— CONFIRM 档

**已查证的官方工具声明原文**（非臣臆测）：

> 自动领取麦麦省所有当前可用的麦当劳优惠券。**无需指定具体的优惠券和 couponId**，
> 系统会自动领取用户可领的**所有**券。当用户说"帮我领券"、"自动领取优惠券"、
> "一键领券"时使用此工具。

由此得出三条硬事实：

1. **可以代领** —— 官方声明的触发场景就是「用户说帮我领券」，代领不违背官方意图。
2. **只能全领，不能挑** —— 无 `couponId` 入参。陛下若只想领一张，臣做不到，必须如实说明。
3. **参数为空** —— 无入参，意味着臣无法限定范围，"复述 + 确认"就成了唯一的护栏。

编排流程（臣的实现）：

```
available-coupons（列券）
   ↓ 臣逐张复述券名与状态
陛下明示「领」
   ↓
auto-bind-coupons           ← CONFIRM 档，仅在确认后由调用方执行
   ↓
query-my-coupons            ← 回查卡包，确认券真的入包（不凭"调用成功"就当领到）
   ↓
calculate-price             ← 验证本单能否使用、实际减免多少
```

⚠️ 臣**未核实**领券是否消耗领取资格或次数（官方声明中未提及），已在输出中如实标注。

### 代领券令实跑结果（2026-10-22，陛下明示后执行）✅

| 工具 | 结果 | 依据 |
|---|---|---|
| `auto-bind-coupons` | ✅ 成功，回报**成功 3 张 / 失败 0 张** | 11.9元麦辣鸡腿堡、19.9元王牌炸鸡任选2、免费脆薯饼 |
| `query-my-coupons`（回查） | ⚠️ 卡包实查 **2 张** | 缺「免费脆薯饼」，与领券回报**不一致**，已如实对账 |
| `query-store-coupons`（beType=2） | ✅ **首次非空**，2 张 | `traceId: be45481dcf573b55055231e080be0106`，时间 11:50:06 |
| `calculate-price`（带券，1440） | ✅ 应付 **19.00 元** | 商品 25.50 → 11.90，`discount=1360`，`traceId: bcb7519b0270f98ddafe007b2501fef6` |
| `calculate-price`（**不带券**，1440） | ⚠️ 商品价 **0**、productList 空 | `traceId: 6abfddfd05a8df6dd3e39f06150077ec` |
| `calculate-price`（带券，9900016534） | ✅ 应付 **27.80 元** | 商品 30.00 → 19.90，`discount=1010`，`traceId: 9c1d616d9b7bbb3adc4c1c7c6b5e822d` |
| `calculate-price`（对照，901100 不带券） | ✅ 正常 **35.60 元** | 用于排除核价接口故障，`traceId: f79f5af166c5865373e6fbcf6c1f1fe6` |

**关键实测结论三（券效）**：两张券**均已验证生效**——麦辣鸡腿汉堡券 `discount` 13.60 元，
王牌炸鸡任选2 券 `discount` 10.10 元，均由官方 `calculate-price` 给出，臣未自行推算。
「券与本单的匹配核价」这条链路由此**从"未验证"转为"已验证"**。

**关键实测结论四（异常，未下断言）**：商品 `1440` 在**不带券**时官方核不出价
（`productPrice=0`、`productList` 为空，只剩配送费）。臣已用 `901100` 做对照实验，
确认核价接口本身正常，故这是**商品侧**现象；但官方未说明原因，臣**不作断言**，
只在输出中如实标注「无法据此算出省了多少」。

**关键实测结论五（领券对账）**：领券接口回报「成功 3 张」，卡包实查只有 2 张，
「免费脆薯饼」未见于卡包。臣**不假设领券接口一定对，也不假设卡包一定准**，
只把差异摆出来请陛下以官方 App 为准——这正是「领完必须回查」这一步的价值。

> ⚠️ 隐私处理：`couponId` / `couponCode` 是陛下真实券资产，泄露即可能被他人盗用。
> fixture 中**一律掩码**（保留结构、去掉真实券码），并新增 `test_59` 的券码扫描
> （正则 `MCD[A-Z0-9]{15,}`），禁止完整券码进入公开仓库。

---

## 三、调用顺序

```
用户提出需求
      │
      ├─► [本地] date-context / theme
      │      节气、节日、法定节假日（数据文件 + 天文算法）
      │
      ├─► [MCP] campaign-calendar        ← 可选，取官方真实活动
      │
      ├─► [本地] scene                   ← 识别到店自取 / 麦乐送外送
      │
      ├─► 分路：
      │    A. 到店自取（beType=1, orderType=1）
      │        [MCP] query-nearby-stores → storeCode（不传 beCode）
      │    B. 麦乐送外送（beType=2, orderType=2）
      │        [MCP] delivery-query-addresses → addressId
      │        [MCP] delivery-query-stores(beType=2) → storeCode + beCode
      │        ※ 缺 beCode 则官方拒答（600048），链路在此阻塞
      │
      ├─► [MCP] query-meals              → 真实菜单 + 官方标价
      │        到店：storeCode, orderType=1, beType=1
      │        外送：storeCode, orderType=2, beType=2, beCode（必传）
      │
      ├─► [本地] match                   ← 本地按预算/偏好/主题打分，取前 6
      │
      ├─► [MCP] query-store-coupons      → 本单可用券
      │
      ├─► [本地] coupons                 ← 本地粗筛优惠组合
      │
      ├─► [MCP] calculate-price          → 官方核价（只读）
      │
      ├─► [本地] verify-price + render   ← 核验标记 + 奏折渲染
      │
      └─► 输出：请用户自行前往官方渠道下单
              （到此为止，不再调用任何写操作）
```

**关键设计：先本地筛选，再调用官方核价。** 不把全部组合丢给 MCP，减少无效调用。

---

## 四、关键输入与返回数据

### 1. `query-nearby-stores`
- **输入**：`beType=1`（到店自取）、`searchType=2`、`city="杭州"`、`keyword="西湖"`
- **关键返回**：`data[].storeCode`、`storeName`、`address`、`businessStatus`、`reservationTimeOptions`
- **本项目取用**：`storeCode`（后续所有门店级调用都依赖它）
- **实测样例**：`3330052` 麦当劳杭州西湖银泰餐厅（延安路98号，营业中 06:30–23:00，支持预约）

**2026-10-22 补充：`distance` 字段（就近排序的真相）**

返回里还有 `distance`（**单位：米**），且**已由近及远排好序**。关键在于它是
**服务端拿 `keyword` 做地理编码算的**，不是拿用户位置算的：

| `city` | `keyword` | 最近门店 | `distance` | traceId |
|---|---|---|---|---|
| 杭州 | `西湖区`（区县） | 麦当劳杭州灵隐景区餐厅 | 2545 | `398b2615307afcbe33b503fe4e9c873f` |
| 杭州 | `黄龙体育中心`（地标） | 麦当劳杭州西湖区玉古路餐厅 | 188 | `63c978eb31baaf47cb3b3bb993f7e40d` |
| 杭州 | `天目山路148号`（街道门牌） | 麦当劳杭州黄龙世纪广场餐厅 | 410 | `02ec20d9e18d77308a17a1af69590778` |

三行同为 2026-10-23 实跑，**同一个查询点**（`天目山路148号`，浙大玉泉校区正门，公开门牌，
不含任何真实用户地址，可原样复跑）。

**区县一级与"说具体"差 13.5 倍**（2545m vs 188m）——陛下就此指出"区中心可能离用户非常远"，
故引擎的 `parse_address_location()` 必须一路切到路名 + 门牌号，`keyword_level` 四级
（`street` / `landmark` / `district` / `city`），后两级标 `coarse_keyword=True` 并改口径。
注意地标（188m）与门牌（410m）无所谓谁更近——取决于门店实际开在哪；**陷阱只在区县一级**。

推论（写进 SKILL.md 铁律 8）：
- **不需要 IP 定位**，臣也拿不到 IP；`longitude` / `latitude` 恒为 `0.0`，本地算距无从谈起。
- 想让"就近"更准，唯一有效手段是**把 `keyword` 说具体**（门牌 > 地标 > 商圈 > 区名 > 城市名）。
- ⚠️ `delivery-query-stores`（外送可配送门店）**不返回 distance 也不返回 address**，
  只能证明"能送到陛下这个地址"，**不能用来判断哪家更近**。
- 官方展示要求：门店的 `storeCode` 必须完整展示（`beType=5` 时还要 `beCode`）。
- 引擎侧：`adapt_mcd_nearby_stores()` + `render_store_list()`，CLI `store-list`；
  距离缺失或非法时显示"距离官方未返回"，绝不估算。

### 2. `query-meals`
- **输入**：`storeCode="3330052"`、`orderType=1`、`beType=1`
- **返回结构（真实）**：
  - `data.categories[].name` —— 分类名
  - `data.categories[].meals[].code` / `.tags` —— 分类下餐品编码与标签
  - `data.meals.{code}` —— 餐品详情映射：`name` / `currentPrice` / `originalPrice` / `discountType` / `withOrder` / `image`
- **本项目取用**：`code`、`name`、`currentPrice`（**单位：元，字符串**）、`originalPrice`、`tags`、`category`
- **适配逻辑**：`adapt_mcd_menu()` 把 `categories` + `meals` 映射表拼成扁平 items 并去重（同一餐品会出现在多个分类）
- **实测样例**：
  - `1100` 巨无霸 `currentPrice="26.5"`
  - `4810` 薯条 `currentPrice="14.5"`
  - `507411` 麦咖啡™美式 `currentPrice="11.9"` `discountType="促销优惠"`

### 3. `query-store-coupons`
- **输入**：`storeCode="3330052"`、`orderType=1`、`beType=1`
- **返回结构**：`data[].title` / `couponId` / `couponCode` / `tradeDateTime` / `products[].productName|productCode`
- **实测结果**：`data: []`（本门店当前无可展示券）
- **本项目处理**：空列表 ≠ 查询失败。引擎区分两种状态——`coupons=None` 判为查询失败，`coupons=[]` 判为"官方确认无券"，文案不同。

### 4. `calculate-price`
- **输入**：`storeCode`、`orderType=1`、`beType=1`、`items=[{productCode:"1100",quantity:1},{productCode:"4810",quantity:1}]`
- **返回结构（真实，单位：分）**：
  - `data.price` 现价、`data.originalPrice` 原价、`data.discount` 优惠金额
  - `data.productList[].productCode|productName|quantity|subtotal`
  - `data.takeWayList[].code|title`（如 `eat-in` 堂食、`take-in-store` 外带）
- **实测结果**：
  ```json
  {"price":4100,"originalPrice":4100,"discount":0,
   "productList":[
     {"productCode":"1100","productName":"巨无霸","quantity":1,"subtotal":2650},
     {"productCode":"4810","productName":"中薯条","quantity":1,"subtotal":1450}],
   "takeWayList":[{"code":"eat-in","title":"堂食"},{"code":"take-in-store","title":"外带"}]}
  ```
- **注意**：`calculate-price` 返回的 `productName` 是「中薯条」，而 `query-meals` 返回「薯条」——**以核价接口返回为准**，本项目不做名称对齐猜测。

### 5. `campaign-calendar`
- **输入**：无必填（`specifiedDate` 可选）
- **返回**：按日期分组的官方活动（标题、内容、图片）
- **本项目处理**：放入「礼部呈报」栏目，**与麦历（节气/节日）主题分栏**，明确标注来自官方活动日历，不混为一谈。麦历是文化灵感，官方活动是真的活动，两者互不冒充。

---

## 五、价格核验逻辑

1. **标价 ≠ 成交价。** `query-meals` 的 `currentPrice` 只是官方标价，本项目在输出中明确标注"价格为官方标价，非最终成交价"。
2. **最终以 `calculate-price` 为准。** 只有该接口返回的价格才标记为"官方核价"。
3. **单位换算。** 官方返回金额单位为**分**，展示时除以 100 转元（引擎在 `verify_price()` 中统一处理）。
4. **未核验即标注。** 任何未取得 `calculate-price` 结果的方案，标记 `estimated=True`、价格为 `None`，并在奏折中写「未取得官方核价，不作推荐依据」。
5. **券条件未核实不承诺。** 券的适用条件来自官方返回；返回中未确认的，标记"条件未核实，以官方核价为准"。
6. **不叠加假设。** 除非官方明确返回可叠加，否则按互斥处理。
7. **不宣称最低价。** 固定表述为「在本次查询到的官方餐品、优惠与可核验方案范围内，臣已为陛下比较当前可确认的价格」。

---

## 六、错误处理方式

| 错误场景 | 引擎返回 | 用户可见文案 | 下一步建议 |
|---|---|---|---|
| MCP 连接失败 / 工具不存在 | `ok=False` | 「臣未能从官方数据中查得可售餐品，不敢妄拟御膳。」 | 检查 MCP 连接后重试 |
| 菜单返回为空 | `reason="empty_menu"` | 同上 | 换门店或稍后重试 |
| 优惠查询失败（`coupons=None`） | `reason="coupon_query_failed"` | 「户部券令查询未返回结果，臣不敢妄称有优惠。」 | 略过优惠，按标价推荐 |
| 优惠返回空列表（`coupons=[]`） | `ok=True, plans=[]` | 「户部查得：当前无可用券令。」 | 无需处理 |
| 核价失败 | `reason="price_verification_failed"` | 「御膳账目未能核验，臣不敢报出实价。」 | 展示标价并注明未核验 |
| 官方未返回某餐品价格 | 价格为 `None` | 「官方未返回价格」 | 该餐品不参与排序 |
| 参数不符（如到店场景误传 beCode） | MCP 报错 | 照实转述 MCP 的错误信息 | 到店自取不传 beCode |
| 预算低于所有餐品 | `budget_feasible=False` | 说明超出多少 + 给出官方最低价选项 | 调整预算或换品类 |
| 节气/节日数据缺失 | `degraded=True` | 「数据未内置，已跳过节气主题」 | 降级为普通主题 |

**任何错误场景下都不使用模拟数据冒充真实调用结果。**

---

## 七、哪些功能依赖 MCP，哪些由本地实现

| 功能 | 实现方式 |
|---|---|
| 门店查询 | **依赖 MCP**：`query-nearby-stores` |
| 菜单与官方标价 | **依赖 MCP**：`query-meals` |
| 餐品详情/特调 | **依赖 MCP**：`query-meal-detail`（按需） |
| 优惠券 | **依赖 MCP**：`query-store-coupons` / `query-my-coupons` |
| 官方活动 | **依赖 MCP**：`campaign-calendar` |
| 价格核验 | **依赖 MCP**：`calculate-price` |
| 日期 / 节气 | **本地**：天文算法 + 数据文件 |
| 传统节日 | **本地**：农历换算数据 |
| 法定节假日 | **本地**：国务院公开年度安排（2026 已核实） |
| 主题文案 / 今日宜 | **本地**：规则表 |
| 偏好管理 | **本地**：会话内 |
| 候选筛选与打分 | **本地** |
| 优惠粗筛 | **本地** |
| 奏折渲染与合规自检 | **本地** |

---

## 八、如何确认真实 MCP 调用成功

1. **返回体带真实时间戳与 traceId。** 例如 `query-meals` 返回 `"datetime":"2026-10-21 19:19:42"`、`"traceId":"3bc4b2cbe9091b75879c5ac3d125b582"`。
2. **数据与官方渠道一致。** 如 `calculate-price` 返回的 4100 分 = 41.00 元，与菜单标价 26.5 + 14.5 吻合。
3. **留痕可复现。** 真实返回摘录保存在 `tests/fixtures/`（含 `_is_real_data: true`、`_traceId`、`_captured_at`），测试中有专门用例校验这些标记。
4. **测试可离线复跑。** `python tests/test_imperial_kitchen.py` 中 `TestRealMcpEvidence` 会校验 fixture 的来源标记与关键数值。

---

## 九、本项目不自动下单、绝不付款

- **绝不自动**调用任何写操作——`create-order`、`mall-create-order`、`party-order-create`、
  `auto-bind-coupons`、`cancel-order`、`delivery-create-address` 一律须先复述、后经陛下明示。
- **永不调用** `draw-lottery`（消耗账号资源且无撤销路径）。
- **绝不付款**。`create-order` 只创建**待支付订单**，支付链接交给陛下自行扫码或用官方 APP 完成；臣不代付、不代收款。
- **不自动**提交订单备注、不生成取餐柜二维码。
- **引擎本身不发起任何 MCP 调用**：`scripts/imperial_kitchen.py` 只做解析与编排，真实调用由调用方（宿主 Skill）发起。
  源码中的工具名仅存在于「分级清单」常量与说明性文案中；测试 `test_31_no_side_effect_tools_in_source`
  会以 AST + 文本双道扫描，断言源码里**不存在这些工具的函数调用**，防止后续改动误引入。
- 未进入下单流程时，奏折结尾固定声明：「以上均为已查询、已核价、已推荐，**未下单、未付款**。」
  进入下单流程且三重复述已毕后，口径改为「臣可创建**待支付订单**，**支付仍须陛下自行完成**」。
