# 第三步 · 辨明用膳方式（到店自取 / 麦乐送外送）

> 本文件是 `SKILL.md` 的**按需子文件**。
> **何时读**：要定用膳方式、要查门店时才读
> 不要预先读取——读到才读。

---

### 第三步 · 辨明用膳方式（到店自取 / 麦乐送外送）
```
python scripts/imperial_kitchen.py scene --text "陛下原话"
```
引擎会识别场景并给出正确的 `beType` / `orderType`。
**陛下未言明时默认麦乐送外送（beType=2）**，但必须如实告知这是臣的推断，
并以选项卡片请陛下点选确认（可改到店自取）。

#### A. 麦乐送外送（beType=2，orderType=2）——**默认**，多两道前置
```
mcp__mcd-mcp__delivery-query-addresses          # 第 1 步：取 addressId
mcp__mcd-mcp__delivery-query-stores             # 第 2 步：beType=2 + addressId → storeCode + beCode
mcp__mcd-mcp__query-meals                       # 第 3 步：必传 beCode
python scripts/imperial_kitchen.py delivery --addresses <a.json> [--stores <s.json>] [--address-id <id>]
```
- 外送**必须传 beCode**，否则官方返回 `code=600048「外送场景下，beType=2/5/6时必传beCode」`（已实跑验证）。
- `addressId` 只能来自 `delivery-query-addresses` 的真实返回，**不得编造**（传空值会被官方拒绝：`code=400 addressId地址ID不能为空`）。
- 陛下名下暂无地址时，如实说明并请其提供字段（`city`/`contactName`/`gender`/`phone`/`address`/`addressDetail`），**确认后再创建**。
- **已端到端实跑验证**：外送核价会返回 `deliveryPrice`（配送费）与 `packingPrice`（打包费），
  照实展示在「核对御膳账目」明细里（实测配送费 6.00 元 / 打包费 1.90 元，因门店而异）。
- **起送价：麦乐送外送不设起送门槛**（陛下明示；官方 `calculate-price` 返回中亦无该字段）。
  奏折只作一句说明，**不给任何起送金额，也不标"未能核实"**——臣既未取得该字段，也不臆测数额。
- **外送价格高于到店**（实测同一组合 41.00 → 51.90 元），务必以核价结果为准，不可用店内存价推算。
- 门店券 `query-store-coupons` 在外送场景可能返回空，属真实结果，如实说明即可。
  （2026-10-22 代领券后该接口首次返回非空 2 张，已验证券效，详见 `MCP_INTEGRATION.md`。）
- 外送链路未打通时，若已查到到店菜单，奏折中必须标注「以下为到店自取口径，不代表外送报价」。

#### B. 到店自取（beType=1，orderType=1）——**先定地段，再查门店**

⚠️ **官方门店接口不定位。** 已核对 `query-nearby-stores` 的官方声明：
它只有 `beType` / `searchType` / `city` / `keyword` 四个入参，
**没有经纬度，也不读取陛下 IP**。而 `searchType` 默认值为 1，含义是
**查询收藏餐厅**——不按位置，所以返回的门店往往离陛下很远（陛下实测即如此）。

**关于"能不能按 IP 自动判断最近门店"：不必，也做不到——但问题本来就不在 IP。**

2026-10-23 实跑核实（`traceId 398b2615…` / `63c978eb…` / `02ec20d9…`）：
`query-nearby-stores` 的返回里**自带 `distance` 字段（单位：米）**，并且**已由近及远排好序**。
`distance` 是**服务端拿 `keyword` 做地理编码算出来的**——同一城市换关键词，排序立刻变：

| keyword | 最近门店 | 距离 |
|---|---|---|
| `西湖区` | 麦当劳杭州灵隐景区餐厅 | 2545 米 |
| `黄龙体育中心` | 麦当劳杭州西湖区玉古路餐厅 | **188 米** |
| `天目山路148号` | 麦当劳杭州黄龙世纪广场餐厅 | 410 米 |

所以臣真正要做的**不是找陛下在哪，而是把关键词说具体**：

| # | 结论 | 依据 |
|---|---|---|
| ① | 臣拿不到 IP，也不必拿 | 对话里没有 IP 字段；而距离由服务端按关键词算，不依赖陛下位置 |
| ② | 经纬度不可用 | 返回的 `longitude` / `latitude` **恒为 0.0**，本地算距无从谈起 |
| ③ | IP 定位本身不可靠 | 粒度只到城市；移动网络 / 宽带出口 / VPN 常定位到隔壁城市 |

于是"就近"的正确打法是：**拿一个具体的路段/门牌/地标当 `keyword`**。
零打扰的默认来源是陛下已有的麦乐送地址，**但必须尽量切到街道门牌一级**——
**区县一级不能拿来当"就近"**：区中心离陛下可能几公里。实测同一查询点：

| `keyword` | 精度 | 最近门店距离 |
|---|---|---|
| `西湖区` | 区县 | 2545 米 |
| `黄龙体育中心` | 地标 | 188 米 |
| `天目山路148号` | **街道门牌** | 410 米 |

反推出 `city` + `keyword` 后请陛下**点一下确认**；陛下若说出更具体的地标则优先用陛下的：

```
# ① 有外送地址：反推城市与地段，返回 need_confirm + 点选项
python scripts/imperial_kitchen.py store-query \
    --addresses <delivery-query-addresses 的返回 JSON>

# ② 陛下已明说地段：直接 ready
python scripts/imperial_kitchen.py store-query --city 上海 --keyword 人民广场

python scripts/imperial_kitchen.py picks --stage store_area
```

`store-query` 的三种状态，臣须照此办事：

| status | 含义 | 臣该做什么 |
|---|---|---|
| `ready` | 城市与地段齐备 | 直接调 `query-nearby-stores`，`searchType=2` |
| `need_confirm` | 由外送地址反推 | **呈选项卡片请陛下点一下**（第一个选项即推荐值），不得先斩后奏 |
| `need_ask` | 账户下无地址 | 请陛下点选/补一句地段，这是唯一必须陛下开口的一项 |

`need_confirm` 时还要看 **`keyword_level`**（精度分级），措辞随之变：

| `keyword_level` | 例子 | `coarse_keyword` | 臣该怎么说 |
|---|---|---|---|
| `street` | `天目山路148号` | false | 「臣拟按陛下收货地此处就近寻店」→ 推荐项排第一 |
| `landmark` | `某某大厦` | false | 同上，注明切到地标一级 |
| `district` | `上城区` | **true** | **必须**说"区中心离陛下可能很远"，并把「给个更准的地标」排第一 |
| `city` | `杭州` | **true** | 明说"就近几乎无效"，务必请陛下给地标 |

- 反推结果必须标明是陛下**外送收货地**，**非实时定位**，也未必是陛下此刻所在；
  不得说成"臣检测到您在××附近"。
- 两项齐备后才调用：
  `mcp__mcd-mcp__query-nearby-stores` → `beType=1, searchType=2, city=?, keyword=?`
- 拿到返回后**必须完整展示 `storeCode`**（`beType=5` 时还要 `beCode`），并呈上官方距离：
  ```
  python scripts/imperial_kitchen.py store-list --stores <query-nearby-stores 返回 JSON>
  ```
  输出形如「**麦当劳杭州黄龙世纪广场餐厅**　410 米　营业 07:00-22:00 / 天目山路148号 / storeCode `3330253`」，
  再请陛下**点选**一家。
- 查回来之后用 `store-list` 呈上门店，它会自动给一句评语：
  **最近那家超过 1.5 公里**就明说"多半是关键词太粗，或陛下此刻不在收货地附近，给臣一个路名/门牌/地标，臣立刻重查"——
  臣不替陛下硬认这个距离。
- 陛下对"就近"不满意时，**先换更具体的 `keyword` 再查**（门牌 > 地标 > 商圈 > 区名 > 城市名），
  而不是去猜位置——这是本版实测出的唯一有效手段。
- 拿到 `storeCode` 后：`query-meals`（storeCode + orderType=1 + beType=1），
  陛下要看特调时再 `query-meal-detail`。
- **不得**用默认 `searchType=1` 的结果冒充"附近门店"——那是收藏夹，不是就近。
- `distance` 缺失或非法时显示"距离官方未返回"，**绝不自己估算一个距离**。

#### C. 得来速（beType=5）与企业团餐（beType=6）
本版**未实现**，遇此需求如实告知，建议陛下使用麦当劳官方渠道。

- 把 `query-meals` 的返回原样交给本地引擎筛选：
```
python scripts/imperial_kitchen.py match --menu <menu.json> --request <req.json>
```
- 引擎会自动适配真实返回结构（`categories` + `meals` 映射表），按预算/偏好/主题打分取前 6。
