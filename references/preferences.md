# 陛下旧例（偏好）

> 本文件是 `SKILL.md` 的**按需子文件**。
> **何时读**：要读或写陛下偏好时才读
> 不要预先读取——读到才读。

---

## 陛下旧例（偏好）

偏好**可跨会话存档**，存档在用户目录 `~/.workbuddy/user_data/jin-gong-men/preferences.json`，
**位于工作区之外，不会进入 Git 仓库、不随作品公开**。

- 用户**明确说出**的 → `explicit`（如"以后预算 30 以内"）
- 系统**推测**的 → `inferred`，必须标注"臣之推测，待陛下确认"
- 支持「忘掉我的预算偏好」「以后优先便宜的」「今天破例」
- 只记录与点餐有关的偏好，不收集任何敏感个人信息
- 存档失败时（如无写权限）如实降级为"本次会话内有效"，**不假装已存档**

```
python scripts/imperial_kitchen.py preference --set '{"budget_max":30,"likes":["汉堡"]}'
python scripts/imperial_kitchen.py preference --show
python scripts/imperial_kitchen.py preference --clear budget_max
python scripts/imperial_kitchen.py preference --clear-all     # 连存档文件一并删除
python scripts/imperial_kitchen.py preference --set '{...}' --no-save   # 只用一次，不落盘
```
