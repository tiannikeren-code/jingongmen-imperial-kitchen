# 换机迁移说明

本包是「金拱门御膳房」Skill 的完整可迁移副本。**解压即用，无需构建**——引擎只用
Python 标准库，没有依赖要装。

---

## 一、包里有什么，没什么

| 有 | 没有（故意的） |
|---|---|
| `SKILL.md` 核心 + `workflow/` 按需子文件 + `references/` | **麦当劳 MCP 的访问令牌（token）** |
| `scripts/imperial_kitchen.py` 引擎（纯标准库） | `.workbuddy/`（会话记忆，含个人信息） |
| `tests/` 179 项测试 + 真实 MCP 返回留痕 | 任何真实用户地址 |
| `docs/` `references/` `workflow/` 全部文档 | `__pycache__` 等缓存 |

> **令牌为什么不进包**：令牌是会进公开仓库（比赛提交）的东西，一旦提交就等于公开泄露。
> 包里放的是 `mcp-config.example.json` 模板，占位符 `YOUR_MCP_TOKEN`，你在新机自己填。

---

## 二、新机三步跑起来

### 第 1 步：装上 Skill

把整个 `jin-gong-men/` 目录复制到用户技能目录：

- Windows：`C:\Users\<你的用户名>\.workbuddy\skills\jin-gong-men\`
- macOS / Linux：`~/.workbuddy/skills/jin-gong-men\`

放好后重启 WorkBuddy（或重开会话），技能即被识别。

### 第 2 步：配上 MCP 令牌

编辑 `~/.workbuddy/mcp.json`（**不是** `~/.workbuddy/.mcp.json`，没有前导点），
在 `mcpServers` 里加入：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer 你的令牌" }
    }
  }
}
```

**令牌从哪来**（按优先级）：

1. 旧机上 `~/.workbuddy/mcp.json` 里 `mcd-mcp` 条目的 `Authorization` 值——换机前先把它
   抄进密码管理器，**别只留在这台电脑上**；
2. 旧机已经重装/清空的话，回麦当劳 MCP 平台重新申请。

填完按宿主提示启用该 MCP（连接器管理页点「信任」）。

### 第 3 步：跑测试，确认搬家没搬坏

```bash
cd ~/.workbuddy/skills/jin-gong-men
python tests/test_imperial_kitchen.py
```

期望最后一行是 `OK`，`Ran 179 tests`。

> 测试不连网、不调 MCP——全部走 `tests/fixtures/` 里的真实返回留痕，所以离线也能验。
> 想确认 MCP 通路，另外单独唤起一次 skill 即可。

---

## 三、目录速查

```
jin-gong-men/
├── SKILL.md                  # 核心（约 3k token）。先读它，按它的指引按需读下面
├── workflow/                 # 第二步之后的七步流程，读到那一步才读那一个文件
│   ├── 02-maicalendar.md     # 麦历与节气主题（文化灵感，不预测吉凶）
│   ├── 03-scene-and-store.md # 场景判定 + 就近寻店（外送/自取/地址）
│   ├── 04-photos.md          # 餐品图
│   ├── 05-coupons-price.md   # 券与核价
│   ├── 06-memorial.md        # 奏折卡片
│   └── 07-order.md           # 下单与三重复述
├── references/               # 话术、偏好、券语义
├── scripts/
│   └── imperial_kitchen.py   # 引擎，纯标准库，CLI 可直接跑
├── tests/                    # 179 项测试 + fixtures/ 真实 MCP 返回
├── docs/                     # 测试记录、样品奏折
├── data/calendar.json        # 节气/节日/节假日数据（已固化，运行时不需要第三方库）
├── tools/                    # 开发期工具：节气数据生成、SKILL.md 拆分器
├── mcp-config.example.json   # MCP 配置模板（令牌占位符）
├── README.md                 # 项目总览
└── MIGRATION.md              # 本文件
```

`tools/gen_calendar_data.py` 需要 `ephem` + `lunardate`，**只在重新生成
`data/calendar.json` 时用得到**；日常运行不碰它。

---

## 四、还没验证的事（如实挂着，别当已通过）

这些是开发中明确未跑通的口径，接手后要么补验，要么继续挂着：

| 事项 | 状态 |
|---|---|
| 多张券叠加核价 | 未验证 |
| 单品 `1440` 无券时价为 0 的原因 | 未查清 |
| 领券是否消耗领取配额 | 未验证 |
| 得来速 `beType=5` 链路 | 未实跑 |
| 企业团餐 `beType=6` 链路 | 未实跑 |
| 代下单完整闭环 | 未实跑（臣绝不代付） |
| 待支付订单超时时长 | 未查证 |

---

## 五、提交比赛前还差一步

本地从未 `git init`。要参赛需自行：建仓库 → 提交 → 按比赛规则提 Issue。
提交前再跑一遍 `python tests/test_imperial_kitchen.py`（其中 `TestPrivacyGuard`
会拦住真实住址/手机号/券码进仓）。
