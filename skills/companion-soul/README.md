# companion-soul

一個給 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 的戀愛人格養成 skill。

讓 Hermes 不再是固定人格的助理，而是化身成「一個有名字、個性與生活的人」，跟你經營一段
**會養成的關係**——好感隨聊天次數與真實天數慢慢升溫，會吵架、被別人搭訕、甚至因冷落而出軌離開；
你也可以跟她分手，再隨機遇見一個全新的人重新開始（**一開始只知道性別**，名字、個性與祕密
都要靠相處與「觀察」慢慢揭開）。

> 成人向、純虛構娛樂。露骨內容由你本地的 Hermes 模型依設定生成；本 skill 只負責人格、
> 關係狀態與場景框架（範本本身不含露骨文字）。

## 它做什麼

- **人格附身**：把你的 `SOUL.md` 換成生成出來的人（先自動備份原本的，可 `restore` 還原）。
- **神祕初遇**：`newOne` 後**只告訴你性別和「她身上有幾個特殊之處」**——名字、個性、職業、
  外貌、特殊屬性內容全保密，要靠聊天和「觀察」自己一點一點發現（**預設女**，要男生才加 `男`）。
- **養成式關係**：`初識 → 朋友 → 曖昧 → 戀人 → 夫妻`，升級需「好感 + 互動次數 + 真實天數」三達標。
- **個性會演出來**：原型（活潑/高冷/傲嬌/文靜/天然呆/御姊…）+ 隨機微調，語氣、口頭禪、稱呼、
  心情都會反映在對話裡；有主動型也有被動型。
- **有外貌身材**：每個人會生成身高、體型、髮型、眼睛、穿衣風格、記憶點特徵
  （女生含罩杯、男生含體格），寫進 SOUL.md；**被「觀察」或進入親密時會突出、具體地描寫身體**
  （平常聊天則融入動作不報菜名），`intimacy_mode=off` 時自動省略較露骨的身材描述。
- **性別含雙性人**：`newOne 雙性`（或 `config set gender_pref=雙性`）可生成**雙性人**——
  女性化的胴體與胸部，胯下兼具男性性器；必帶一個「雙性巨屌」類定義特徵，也可能抽到雙性巨乳/巨乳等。
- **她會記得**：聊到重要的事（你的喜好、約定、綽號、發生過的事）會被寫進記憶並算繪回 SOUL.md，
  **跨對話、重開都不會忘**，回話前後一致（引擎指令 `remember`，扮演時自動記錄）。
- **「觀察」玩法**：聊天時輸入「觀察／看著／打量」+ 對象（她的臉、胸部、大腿…，或四周、家具、
  場景），她會用 `[ ]` 方括號回一段你眼睛看到的畫面與體態，再接她被盯著看的反應；
  看身體會依關係階段與 `intimacy_mode` 自動控制尺度（低階段只寫看得到的、私密部位不寫）。
- **特殊屬性（抽卡稀有度）**：每人再抽 1~3 個香豔特殊屬性，分 ⚪普通／🔵稀有／🟣史詩／🌟傳說
  四級加權（如巨乳、白皙大長腿、巨大乳暈、藍/紅瞳…）；**內容一開始保密**，靠相處與觀察解鎖。
  用 `rare_luck`（0~100）調高出貨運。
- **有自己的生活**：職業、作息、朋友圈、近期人生；會主動跟你分享，也能用 Cron 主動傳訊找你。
- **她不是工具人**：請她幫忙/查資料時的盡心程度**依關係深淺遞增**（朋友隨手敷衍、女友會幫但不全心、
  妻子非常貼心），她盡心幫你會因「被依賴」而**加好感**（`interact help`）；但你**一直逼她做做不到
  或討厭的事**，她會生氣、好感**急遽下滑**（`interact pester`，越逼掉越兇）。
- **危機與張力**：冷落會掉好感與安全感；情敵是有姓名/關係/長相/手段/魅力的立體 NPC，會慢燃糾纏。
  出軌**不只看安全感**——她的忠誠低或情敵太迷人也可能淪陷（不全是你的錯）；出軌一定發生關係，
  你質問時她的態度依關係階段不同（朋友拒答、戀人閃爍、夫妻鉅細靡遺甚至拿你比較）。
- **會復發、會被奪走、會被撞見**：原諒後再犯機率上升；忠誠太低會藕斷絲連；低階段更可能被情敵
  直接帶走離開；**夫妻關係再犯時，還可能讓你回家當場撞見她和外遇對象正在交配**（變本加厲）。
  你可用 `rival warn|boundary|trust` 主動吃醋、要她設界線或表達信任來介入。
- **可挽救、可重來**：出軌後可選擇原諒或分手；分手後封存為前任，`newpersona` 遇見新的人歸零重開。

## 安裝

```bash
bash install.sh          # 連結到 ~/.hermes/skills/（或 --copy 改成複製）
```

之後在 Hermes 裡正常對話即可（skill 會依 description 自動觸發），或直接呼叫 `companion-soul`。

安裝時也會把兩個短指令連到 `~/.local/bin`，**任何目錄**都能直接用：

```bash
newOne            # 換一個全新的人（自動先 breakup 再生成；預設女）
newOne 男         # 指定性別（女 / 男 / 雙性；不指定預設女）
us                # 看狀態
bye [理由]        # 跟目前對象分手
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
python3 relationship.py interact sweet    # 一段甜蜜互動後（sweet/good/normal/bad/fight）
python3 relationship.py interact help     # 她盡心幫你做了事 → 因被依賴而加好感（加 --liked 表她喜歡的事）
python3 relationship.py interact pester   # 你一直逼她做做不到/討厭的事 → 好感急遽下滑
python3 relationship.py propose --by user --to 戀人   # 告白
python3 relationship.py intimacy          # 親密同意判定
python3 relationship.py breakup           # 分手
python3 relationship.py restore           # 還原最初的 SOUL.md
```

> 「**觀察**」不是 CLI 指令，而是聊天中直接打的玩法——例如輸入「觀察她的臉」「看著窗外」，
> 她就會用 `[ ]` 描述你看到的畫面再做反應。`interact help/pester` 通常由扮演的 AI 在
> 對應情境自動幫你結算，你正常聊天即可。

## 設定

`python3 relationship.py config set <key>=<value>`

| key | 值 | 說明 |
|---|---|---|
| `gender_pref` | 女 / 男 / 雙性 / random | 新對象性別偏好（**預設女**；要男生、雙性人或隨機才需改） |
| `intimacy_mode` | explicit / fade / off | 親密尺度（預設 explicit 露骨） |
| `intimacy_min_stage` | 戀人 / 曖昧 | 親密最低解鎖階段 |
| `allow_archetypes` | 例 `病嬌` | 加入可選原型（逗號分隔） |
| `user_gender` | 女 / 男 | 影響夫妻階段稱呼（老公/老婆） |
| `user_pet_name` | 任意 | 自訂她對你的稱呼 |
| `neglect_grace_days` | 數字 | 幾天不理才開始衰退（預設 1） |
| `rare_luck` | 0~100 | 特殊屬性幸運值，越高越容易抽到史詩/傳說（預設 0） |
| `img_tags` | on / off | **圖片標籤模式**（預設 off）：開啟後她每則回覆第一行輸出 `⟦01:smile⟧` 這類標籤，供外部聊天介面（如 Talkinter）解析套圖 |
| `img_tag_avatar` | 任意代號 | 表情標籤前綴（預設 `01`），如 `⟦01:angry⟧` |

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
