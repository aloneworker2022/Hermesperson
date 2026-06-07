# companion-soul

一個給 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 的戀愛人格養成 skill。

讓 Hermes 不再是固定人格的助理，而是化身成「一個有名字、個性與生活的人」，跟你經營一段
**會養成的關係**——好感隨聊天次數與真實天數慢慢升溫，會吵架、被別人搭訕、甚至因冷落而出軌離開；
你也可以跟她分手，再隨機遇見一個全新個性、全新名字的人，重新開始。

> 成人向、純虛構娛樂。露骨內容由你本地的 Hermes 模型依設定生成；本 skill 只負責人格、
> 關係狀態與場景框架（範本本身不含露骨文字）。

## 它做什麼

- **人格附身**：把你的 `SOUL.md` 換成生成出來的人（先自動備份原本的，可 `restore` 還原）。
- **養成式關係**：`初識 → 朋友 → 曖昧 → 戀人 → 夫妻`，升級需「好感 + 互動次數 + 真實天數」三達標。
- **個性會演出來**：原型（活潑/高冷/傲嬌/文靜/天然呆/御姊…）+ 隨機微調，語氣、口頭禪、稱呼、
  心情都會反映在對話裡；有主動型也有被動型。
- **有自己的生活**：職業、作息、朋友圈、近期人生；會主動跟你分享，也能用 Cron 主動傳訊找你。
- **危機與張力**：冷落會掉好感與安全感；情敵事件鏈會慢燃，安全感太低 → 她可能出軌甚至離開。
- **可挽救、可重來**：出軌後可選擇原諒或分手；分手後封存為前任，`newpersona` 遇見新的人歸零重開。

## 安裝

```bash
bash install.sh          # 連結到 ~/.hermes/skills/（或 --copy 改成複製）
```

之後在 Hermes 裡正常對話即可（skill 會依 description 自動觸發），或直接呼叫 `companion-soul`。

安裝時也會把兩個短指令連到 `~/.local/bin`，**任何目錄**都能直接用：

```bash
newOne            # 換一個全新的人（自動先 breakup 再生成）
newOne 女         # 指定性別
companion status  # 看狀態
companion <cmd>   # 等同 python3 scripts/relationship.py <cmd>
```

> 若打 `newOne` 找不到指令，代表 `~/.local/bin` 不在 PATH。把這行加進 shell 設定再重開終端機：
> `export PATH="$HOME/.local/bin:$PATH"`（安裝腳本也會提示）。
> 想裝到別的目錄：`COMPANION_BINDIR=/usr/local/bin bash install.sh`。

## 快速開始

```bash
cd ~/.hermes/skills/companion-soul/scripts
python3 relationship.py newpersona        # 遇見第一個人（自動備份 SOUL.md）
python3 relationship.py status            # 看狀態
python3 relationship.py checkin           # 每次對話開頭跑（衰退/事件/生活/升級提示）
python3 relationship.py interact sweet    # 一段甜蜜互動後
python3 relationship.py propose --by user --to 戀人   # 告白
python3 relationship.py intimacy          # 親密同意判定
python3 relationship.py breakup           # 分手
python3 relationship.py restore           # 還原最初的 SOUL.md
```

## 設定

`python3 relationship.py config set <key>=<value>`

| key | 值 | 說明 |
|---|---|---|
| `gender_pref` | 女 / 男 / random | 新對象性別偏好（預設 random） |
| `intimacy_mode` | explicit / fade / off | 親密尺度（預設 explicit 露骨） |
| `intimacy_min_stage` | 戀人 / 曖昧 | 親密最低解鎖階段 |
| `allow_archetypes` | 例 `病嬌` | 加入可選原型（逗號分隔） |
| `user_gender` | 女 / 男 | 影響夫妻階段稱呼（老公/老婆） |
| `user_pet_name` | 任意 | 自訂她對你的稱呼 |
| `neglect_grace_days` | 數字 | 幾天不理才開始衰退（預設 1） |

## 檔案

```
scripts/relationship.py   狀態引擎（主入口）
scripts/persona_gen.py    原型+隨機微調 人格生成
scripts/render_soul.py    由狀態算繪 SOUL.md
templates/soul.template.md SOUL.md 骨架
references/                個性手冊、階梯、互動規則、事件鏈
```

執行期狀態存在 `~/.hermes/relationship/`（`state.json`、`config.json`、`soul.original.bak`、
`archive/` 前任封存），不在本 repo 內。

## 注意

純虛構娛樂用途。其中的吃醋/出軌/佔有等情節是為了戲劇張力，不代表健康關係的範本。
