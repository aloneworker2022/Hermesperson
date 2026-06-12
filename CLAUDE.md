# CLAUDE.md — 開發者 / AI 維護指南

> 這份檔案是寫給**未來要修改、擴充這個專案程式碼的 AI（或人）**看的。
> 想「玩」請看 `skills/companion-soul/README.md`；想知道「扮演角色的規則」請看
> `skills/companion-soul/SKILL.md`。本檔只談**架構、資料結構、慣例、怎麼安全地加功能**。

---

## 1. 這是什麼（30 秒心智模型）

`companion-soul` 是一個給 Hermes Agent 的 skill。它把一個 LLM 的 `SOUL.md`（人格設定檔）
換成「一個有名字、個性、外貌、生活、會養成的戀愛對象」。

核心是一個 **Python 狀態引擎**：

```
玩家下指令 → relationship.py 改 state.json → render_soul.py 把 state 算繪成 SOUL.md
                                            → LLM 讀 SOUL.md 後就「變成那個人」
```

**最重要的不變量**：`SOUL.md` 是 **state 的衍生產物（derived view）**。
- 永遠不要手改 `SOUL.md`；任何狀態改動後一定呼叫 `write_soul()` 重繪。
- 改了 `templates/soul.template.md` 或 `render_soul.py` 後，舊存檔用 `rerender` 就能套用。
- 真正的「真相來源（source of truth）」是 `state.json`。

成人向、純虛構。**本 repo 不含露骨文字**——露骨內容由使用者本地 LLM 依 `intimacy_mode`
即時生成；引擎只提供人格、關係狀態與「場景框架」。改任何親密相關功能時請維持這個分界。

---

## 2. 檔案佈局

```
skills/companion-soul/
├── README.md                 玩家向：安裝、玩法、指令、設定表
├── SKILL.md                  扮演 AI 向：指令入口、流程、口語→指令對照（Hermes 會載入）
├── install.sh                連結/複製到 ~/.hermes/skills/，註冊 bin 短指令與 Cron
├── bin/                      短指令 wrapper：companion / newOne / us / bye
├── scripts/
│   ├── relationship.py       ★ 主入口：狀態引擎、所有 CLI 指令、衰退/事件/升級邏輯
│   ├── persona_gen.py        人格生成：原型 + 隨機微調 + 外貌 + 特殊屬性抽卡
│   └── render_soul.py        把 state 算繪成 SOUL.md（含階段稱呼、心情、外貌、危機段）
├── templates/
│   └── soul.template.md      SOUL.md 骨架（render 用 {{佔位}} 填入）
└── references/               扮演 AI 的細節手冊（執行期 LLM 按需讀，引擎不讀）
    ├── personalities.md      各原型演出手冊
    ├── stages.md             關係階梯、門檻、稱呼
    ├── interaction-rules.md  好感/安全感/心情/親密規則
    └── events.md             情敵/出軌事件鏈、撞見現行、Cron 主動訊息
```

**「我要改的東西該動哪個檔？」對照：**

| 想改的東西 | 動這裡 | 別忘了同步 |
|---|---|---|
| 數值/門檻/機率/衰退/事件邏輯 | `scripts/relationship.py` | 若影響玩法 → README/SKILL |
| 人格原型、外貌、特殊屬性、名字池 | `scripts/persona_gen.py` | `references/personalities.md` |
| SOUL.md 的呈現/段落/稱呼/危機演出 | `scripts/render_soul.py` (+ `templates/`) | — |
| 玩家看到的玩法說明 | `README.md` | — |
| 扮演 AI 的行為規則/指令對照 | `SKILL.md` + `references/*.md` | — |

> 注意：`references/*.md` 與 `SKILL.md` 是**給執行期 LLM 讀的散文**，引擎程式碼不會解析它們。
> 所以「改數字」必須改 `scripts/`，光改 md 不會生效；反過來「改演出語氣」改 md 即可。

---

## 3. 執行期狀態（不在 repo 內）

引擎讀寫 `~/.hermes/`（可用環境變數覆寫，見下）。**這些是使用者資料，不進 git。**

```
~/.hermes/relationship/
├── state.json          ★ 真相來源（見 §4 schema）
├── config.json         偏好設定（見 DEFAULT_CONFIG）
├── soul.original.bak   第一次 newpersona 時備份的原始 SOUL.md（restore 用）
└── archive/            分手後封存的前任 state
~/.hermes/SOUL.md       算繪輸出（被 LLM 載入的人格檔）
~/.hermes/MEMORY.md     里程碑 append-only log
```

路徑由 `relationship.py` 頂部的環境變數決定，**測試時務必覆寫到 /tmp**：
`HERMES_REL_DIR`、`HERMES_SOUL_PATH`、`HERMES_MEMORY_PATH`。

---

## 4. state.json 結構（`new_state()` 為準）

```jsonc
{
  "active": true,
  "persona": { /* persona_gen.generate_persona() 的整包輸出 */
    "name": "...", "gender": "女|男|雙性", "age": 24, "archetype": "傲嬌",
    "libido": {name:"性冷感|好色|雙性好色", grade:"N|S|SSR", desc},  // 性慾傾向（影響 shyness 與親密演出）
    "proactivity": "主動|被動", "shyness": 0-100, "jealousy": 0-100,
    "loyalty": 0-100,                    // ★ 出軌判定的關鍵之一（低=易淪陷）
    "tone": "...", "catchphrases": [...], "reactions": {...},
    "likes": [...], "dislikes": [...], "quirk": "...",
    "appearance": { /* 身高/體型/髮/眼/風格/特徵；女含 bust、男含 physique */ },
    "special_traits": [ {name, rarity, mark, desc}, ... ],  // 抽卡屬性
    "grades": { libido, occupation, build, bust, eyes, special },  // 各類別評級
    "overall": { "grade": "N|R|S|SR|SSR", "score": 1.2 },  // 人物總評（compute_overall）→ 決定脾氣門檻
    "life": { occupation, schedule, social_circle, hobbies, current_arc }
  },
  "relationship": {
    "stage": "初識",            // STAGES 之一
    "affinity": 10,             // 好感 0-100
    "trust_security": 50,       // 安全感 0-100（低=易動搖/出軌/被奪走）
    "mood": "普通",             // MOODS 之一
    "intimacy_level": 0,
    "affair_count": 0,          // 出軌累計，越高再犯/被奪走機率越高
    "anger": 0                  // 怒氣 0-100：惹怒互動累積、sweet/good 消、checkin 10% 自然清空
  },
  "counters": {
    "interaction_count": 0, "days_since_stage": 0,
    "last_interaction_at": iso, "started_at": iso, "stage_entered_at": iso,
    "anger_strikes": 0          // 惹怒紀錄：達 ANGER_THRESHOLD[總評] 引爆 _anger_blowup
  },
  "milestones": [ {type, note, at}, ... ],
  "memories": [ {note, at}, ... ],   // remember 指令累積，render 取最近 14 則進 SOUL（跨對話記憶）
  "pending_events": [ /* 進行中的事件，情敵鏈是 {"chain":"rival", phase, origin, stage, ...} */ ],
                                   // phase: 露臉→接近→追求（鋪墊期；追求才進 stage 0–3 與出軌判定。舊存檔無 phase→當追求）
                                   // origin: circle 生活圈／outing 興趣·放假新認識（決定 relation 取向）
                                   // heat: 追求期每次 checkin +1（火力：T 加壓、allure 進化、猛攻擋化解，舊存檔無→0）
                                   // date_spot/date_fresh: 旁觀者場景的地點與「本回合才剛撞見」標記
  "inbox": [ {text, at, seq, tone, theme}, ... ],  // 她趁你不在傳來、凍結待讀的主動訊息（非同步、不推播）
                                   // tone: fresh|worried|annoyed（鬧脾氣升級鏈，依稀有度）；theme: daily|outing_innocent|outing_rival
                                   // cron-msg 決定要不要發/第幾則/主題 → inbox add 凍結 → checkin 打開遞送並清空（=已讀=回覆）
  "flags": {
    "affair": false,        // 出軌旗標亮起（待原諒或分手）
    "engaged": false, "married": false,
    "leaving": false,       // 她決定為情敵離開你（需安全感≥75 才挽回）
    "caught_in_act": false, // 夫妻+再犯時當場撞見正在交配（變本加厲）
    "date_spotted": false   // 你撞見她正和追求者在外面（旁觀者場景）→ date watch/interrupt 處理，不出手下次 checkin 散場
  }
}
```

**向後相容是硬性要求**：玩家存檔會比新版程式碼舊。讀 state 時一律用
`dict.get(key, 預設)`、`flags.get("新旗標")`，**絕不可假設新欄位存在**。
（範例：`caught_in_act` 在舊存檔不存在，`flags.get("caught_in_act")` 回 `None`/falsy 即正確降級。）

---

## 5. 兩條主要資料流

### A) `checkin`（每次對話開頭跑）— `cmd_checkin()`
```
_apply_decay()        冷落衰退：依距上次互動天數扣好感/安全感（neglect_grace_days 寬限）
  → _advance_rival()  情敵鏈推進：露臉→接近→追求(鋪墊期)→搭訕→動搖→出軌；追求期才含 _temptation()/_trigger_affair()
  → _life_log()       生成「她今天的生活」旁白
  → _check_upgrade_hint()  夠門檻就提示可升級
  → write_soul()      重繪 SOUL.md
回傳：一段給 LLM 自然融入對話的 briefing 文字
```

### B) 算繪 — `render_soul.render(state, config)`
讀 template，依 state 填入各段：身分/個性/外貌(`_appearance_section`)/階段稱呼(`_address`)/
心情/親密(`_intimacy_section`)/**危機段(`_crisis_section`)**。
所有「尺度敏感」內容都在這裡依 `config["intimacy_mode"]` 分 explicit/fade/off 三路輸出。

---

## 6. 關鍵常數（改平衡性看這裡）

`relationship.py`：
- `STAGE_THRESHOLDS = {階段: (好感, 安全感, 天數)}` — 升級三達標門檻
- `INTERACT_DELTA = {品質: (好感Δ, 安全感Δ, mood)}` — sweet/good/normal/bad/fight
- `_temptation()` / `_trigger_affair()` 內的係數 — 出軌與被奪走機率公式（**只在 phase=追求 時生效**）
- `RIVAL_PHASES = ["露臉","接近","追求"]` / `RIVAL_PHASE_DESC` — 情敵鋪墊期（追求才進 stage 0–3）；
  `_advance_rival()` 鋪墊段的淡出率(安全感≥65)、推進率(冷落/低忠誠加速)、`_maybe_seed_outing_rival()`(0.25)
- `INBOX_PATIENCE = {grade: (留言上限, 等待時數)}` / `INBOX_ANGER = {grade: 怒氣量}` — 主動訊息信箱的
  鬧脾氣升級鏈耐性（越稀有越沒耐性）；`_inbox_tone()` 依序位算 fresh/worried/annoyed
- `OUTING_INNOCENT` / `OUTING_RIVAL` / `OUTING_AFFAIR` — 行程告知內容池（興趣報備 vs 跟情敵出去的 NTR 告知）；
  `_choose_theme()` 決定 cron-msg 主題、`_theme_lines()` 產生指引、`_leisure_now()` 算下班/放假在做什麼
- 追求期火力（heat）— `_advance_rival()` 追求段：`T += 3×(heat−1)`、heat≥3 每回合 allure+2(≤92)、
  猛攻擋化解 `min(0.55, 0.15×(heat−1))`、冷落空檔 `T+12`——後期陪伴不再保證化解
- `DATE_SPOTS` / `_spot_date()` / `cmd_date()` — 旁觀者場景（你撞見她和追求者在外面）：
  checkin 觸發 0.22(stage≥2)、信箱 outing_rival 已讀不回觸發 0.5；watch 投入率 0.40+0.10×(stage−2)、
  interrupt 成功率 0.45±(安全感/好感係數)−0.12(stage3)、鬧僵到頂 0.30 被當場帶走；
  `LIFE_LOG_RIVAL`（鋪墊期情敵混入生活旁白，0.4）

`render_soul.py`：`STAGES`（階段順序，index 即等級）、`MOOD_BEHAVIOR`、`ADDRESS_BY_STAGE`、
`ANGER_THRESHOLD`（稀有度→惹怒門檻；relationship.py 由此匯入，單一來源）
`persona_gen.py`：`ARCHETYPES`、`RARITY_WEIGHT`、`SPECIAL_TRAITS`、`GRADE_WEIGHT`/`_roll_graded`
（職業/體型/罩杯/眼睛的 N/R/S/SR/SSR 評級抽，吃 luck）、`LIBIDO`（性慾維度）、
`HOBBY_POOL`（興趣依氣質分桶）/`ARCHETYPE_HOBBY_VIBE`（原型→偏好氣質）/`_pick_hobbies()`（加權抽，貼個性）、
`RIVAL_RELATION`/`RIVAL_RELATION_OUTING`（情敵身分池，依 origin 取向）、`generate_rival(persona, origin)`、
`OCC_ROUTINE`（職業→工作時段/描述）、`CHRONOTYPES`（睡眠型）、各種名字/外貌池

時間：`now_dt()` 依 `config.timezone`（預設 Asia/Taipei，可用 `HERMES_TZ` 覆寫）回傳 naive
datetime；測試用 `--now`（注意要放在子指令**前**：`relationship.py --now ... checkin`）。
作息推斷在 `_routine_now()`（睡覺>工作>休息，支援跨夜時段與週末休）。

---

## 7. 「我要加 X」食譜

**加一個 config 設定**：在 `DEFAULT_CONFIG` 加 key+預設 → 在用到的地方 `cfg.get(key)`
→ 更新 `cmd_config` 允許清單（它檢查 `k in DEFAULT_CONFIG`）→ 同步 README/SKILL 設定表。

**加一種互動品質**：在 `INTERACT_DELTA` 加一筆 → `cmd_interact` 的 choices/parser 加上。

**加一個關係階段**：改 `render_soul.STAGES` 順序 + `STAGE_THRESHOLDS` + `ADDRESS_BY_STAGE`
（稱呼）；注意所有 `stage_index()` 比較與 `idx >= N` 的硬編界線（如夫妻=5）。

**加一個人格原型**：在 `persona_gen.ARCHETYPES` 加一筆（tone/catchphrases/reactions/
shyness/jealousy…），需要的話加進 `ARCHETYPE_LOYALTY` 與 `ARCHETYPE_HOBBY_VIBE`（偏好氣質桶，
缺則退回全桶等權）；演出手冊補 `references/personalities.md`。

**加一個特殊屬性（抽卡）**：在 `SPECIAL_TRAITS` 對應稀有度池加項目；稀有度權重在 `RARITY_WEIGHT`。

**加一個事件/危機（如撞見現行的作法）**：
1. 在 `flags` 加旗標（記得 `new_state` 也加，預設 false）。
2. 在觸發處（多半是 `_trigger_affair`/`_advance_rival`）設旗標 + `add_milestone` + 加 briefing。
3. 在 `_crisis_section` 依旗標渲染對應段落，**三種 intimacy_mode 都要分別處理**。
4. 在 `cmd_status` 加狀態提示；在解除處（如原諒）清旗標。
5. 在 `references/events.md` 補文件，並用 §8 的方式測。

---

## 8. 慣例與測試

- **語言**：使用者可見字串、文件、commit 用**繁體中文**；程式識別字用英文。
- **隨機性可重現**：吃 `random` 的指令支援 `--seed N`（測試靠它命中特定分支）。
  時間可用 `--now` 注入（`_NOW`）。
- **親密尺度分界**：任何會描寫身體/性的輸出，都必須讀 `config["intimacy_mode"]`
  並提供 explicit / fade / off 三種寫法；off 只陳述事實、不描寫。露骨文字交給本地 LLM。
- **沙箱測試**（不污染使用者 `~/.hermes`）：
  ```bash
  cd skills/companion-soul/scripts
  D=/tmp/t; rm -rf $D; mkdir -p $D/rel
  export HERMES_REL_DIR=$D/rel HERMES_SOUL_PATH=$D/SOUL.md HERMES_MEMORY_PATH=$D/MEM.md
  python3 relationship.py newpersona --gender 女
  python3 relationship.py checkin --seed 1
  ```
  要測特定情境（如夫妻出軌），用一小段 Python 直接組 state 後 `R.save_state()`，
  再跑指令並 `grep` SOUL.md / 輸出驗證（見 git log 中的測試範例）。
- **語法檢查**：`python3 -c "import ast; ast.parse(open('relationship.py').read())"`。
- 無第三方相依，純標準庫 Python 3。

---

## 9. 容易踩的雷

- 改了 `render_soul`/template 卻忘了它只在指令觸發時重繪 → 跑 `rerender` 套用到現有存檔。
- 新增 flag 沒在 `new_state` 設預設、或讀取時沒用 `.get()` → 舊存檔會 KeyError。
- 在 `_crisis_section` 加露骨內容卻沒做 off/fade 分支 → 破壞尺度分界。
- 把數值寫進 `references/*.md` 以為會生效 → 那些只是給 LLM 讀的散文，引擎不解析。
- 直接編輯 `~/.hermes/SOUL.md` → 下次任何指令 `write_soul()` 會覆蓋掉。
