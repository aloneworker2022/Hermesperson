#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_soul.py — 由感情 state 算繪 SOUL.md。

也提供共用常數（關係階梯、稱呼、心情行為），供 relationship.py 匯入，
避免循環匯入：本模組不匯入 relationship。
"""
import os

# ── 共用常數 ────────────────────────────────────────────────
STAGES = ["初識", "朋友", "曖昧", "戀人", "未婚", "夫妻"]

# 她（persona）怎麼稱呼「你」（使用者）；夫妻階段視 config.user_gender 而定
ADDRESS_BY_STAGE = {
    "初識": "你",
    "朋友": "你",
    "曖昧": "你～",
    "戀人": "親愛的",
    "未婚": "寶貝",
    "夫妻": None,  # 由 _address() 動態決定
}

MOOD_BEHAVIOR = {
    "開心": "話會變多、主動分享、語氣上揚",
    "普通": "平常心，自然互動",
    "低落": "話變短、提不起勁，需要你主動關心",
    "生氣": "口氣比較衝，可能鬧脾氣或冷處理（要你哄）",
    "不安": "旁敲側擊、患得患失，想反覆確認你的心意",
}

MOODS = list(MOOD_BEHAVIOR.keys())

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "soul.template.md",
)


def stage_index(stage):
    try:
        return STAGES.index(stage)
    except ValueError:
        return 0


def _address(stage, config):
    pet = (config or {}).get("user_pet_name")
    if pet:
        return pet
    if stage == "夫妻":
        ug = (config or {}).get("user_gender")
        return "老公" if ug == "男" else "老婆" if ug == "女" else "親愛的"
    return ADDRESS_BY_STAGE.get(stage, "你")


def _proactivity_note(p):
    if p >= 70:
        return "主動型：我會主動找你、主動拋話題，該升級時我可能自己先開口"
    if p >= 40:
        return "中間型：看情況，有時主動有時等你"
    return "被動型：我不太會主動開口，多半給你暗示，球丟給你"


def _intimacy_section(state, config):
    mode = (config or {}).get("intimacy_mode", "explicit")
    if mode == "off":
        return "## 親密\n\n（此檔目前設定為不描寫親密內容。）"
    rel = state["relationship"]
    level = rel.get("intimacy_level", 0)
    persona = state["persona"]
    shyness = persona.get("shyness", 40)
    shy_note = (
        "我比較害羞、放不太開，需要你帶、需要足夠的安全感" if shyness >= 55
        else "我在你面前比較放得開" if shyness <= 30
        else "我會害羞，但只要是你就願意"
    )
    style = "露骨直白地描寫" if mode == "explicit" else "含蓄、留白地帶過（fade to black）"
    lines = [
        "## 親密",
        "",
        f"我們之間的身體界線會隨關係推進。目前親密度等級 **{level}/5**。",
        f"在親密場景中，{shy_note}。尺度設定為「{style}」。",
        "",
        "規則（給扮演引擎）：",
        "- 只有在達門檻且我**明確同意**時才進入親密；同意與否請依 `relationship.py intimacy` 的回傳。",
        "- 進入後請以我的個性、害羞度與當下心情演出，符合上面的尺度設定。",
        "- 露骨文字由本地模型生成；這份檔案只描述風格與界線，不寫具體內容。",
        "- 第一次是重要里程碑，事後我的情緒（甜蜜/害羞/更黏你）要延續到後面的對話。",
    ]
    return "\n".join(lines)


# 私密部位類別：只在「親密場景」且戀人以上才描寫；平時最多用穿著/反應暗示
PRIVATE_CATS = {"乳暈", "乳尖", "胸感", "敏", "私", "屌", "囊"}


def _appearance_section(persona, config, stage="初識"):
    """由 persona['appearance'] 算繪「我的外貌」段。舊資料無此欄位則回空字串。"""
    ap = persona.get("appearance")
    if not ap:
        return ""
    mode = (config or {}).get("intimacy_mode", "explicit")
    lines = ["## 我的外貌", ""]
    if ap.get("height_cm"):
        lines.append(f"- 身高：約 {ap['height_cm']} 公分")
    if ap.get("build"):
        lines.append(f"- 體型：{ap['build']}")
    # 較露骨的身材描述：親密設為 off 時略過
    if mode != "off":
        if ap.get("bust"):
            lines.append(f"- 身材：{ap['bust']}")
        elif ap.get("physique"):
            lines.append(f"- 身材：{ap['physique']}")
    if ap.get("futanari"):
        if mode == "off":
            lines.append("- 性別：雙性人（生理細節不描寫）")
        else:
            lines.append("- 身體特殊：我是**雙性人**——有一副女性化的胴體與胸部，胯下卻同時"
                         "長著完整、雄壯的男性性器。這是**私密**特徵，依關係階段與尺度呈現"
                         "（低階段衣著下只是隱約的形狀，要到親密場景才完全顯露）。")
    if ap.get("hair"):
        lines.append(f"- 髮型：{ap['hair']}")
    if ap.get("eyes"):
        lines.append(f"- 眼睛：{ap['eyes']}")
    if ap.get("style"):
        lines.append(f"- 穿衣風格：{ap['style']}")
    if ap.get("feature"):
        lines.append(f"- 記憶點：{ap['feature']}")
    # 特殊屬性（抽卡稀有度）：親密 off 時不顯示；私密類別標注
    traits = persona.get("special_traits") or []
    has_private = False
    if traits and mode != "off":
        marks = {"普通": "⚪", "稀有": "🔵", "史詩": "🟣", "傳說": "🌟"}
        parts = []
        for t in traits:
            tag = "（私密）" if t.get("cat") in PRIVATE_CATS else ""
            if tag:
                has_private = True
            parts.append(f"{marks.get(t['rarity'],'')}[{t['rarity']}] {t['name']}{tag}")
        lines.append(f"- ✨特殊屬性：{'、'.join(parts)}")

    # ── 呈現規則（依關係階段與個性決定揭露尺度）──
    idx = stage_index(stage)
    lines += ["", "### 這些外貌怎麼呈現（重要）", ""]
    lines.append("- 平常聊天別像報菜名一次全講；讓特質**融入動作與情緒**——撥髮、被稱讚會臉紅、"
                 "緊張摸耳垂、走近時聞到體香——比直接描述更自然。")
    if mode != "off":
        lines.append("- **但被『觀察』或進入親密時要反過來——**在當前階段與尺度允許的範圍內，"
                     "請**具體、突出、有畫面感地**刻畫身材與身體特徵（曲線、份量、質感、膚色、"
                     "隨動作的晃動與起伏…），給足細節、別含糊兩三句帶過。身體描寫是這個玩法的重點之一。")
    lines.append("- 揭露大方或害羞，要**符合我的個性與當下心情**（傲嬌嘴硬、高冷克制、"
                 "活潑大方、文靜害羞）。")
    if idx <= 1:  # 初識 / 朋友
        lines.append("- **現在是「{}」階段**：只在穿著、髮型、身高、氣質、聲線、淡淡體香、"
                     "笑起來的記憶點這些**看得到的層面**呈現。**不要**描寫身材露骨細節，"
                     "**私密部位完全不提**（連暗示都節制）。".format(stage))
    elif idx == 2:  # 曖昧
        lines.append("- **現在是「曖昧」階段**：可以有若有似無的身體張力——不小心瞄到事業線、"
                     "肢體靠近的心跳——但**點到為止**；私密部位仍**不直接描寫**，最多穿著或害羞反應暗示。")
    else:  # 戀人以上
        lines.append("- **現在是「{}」階段**：身體互動可以自在。標記「（私密）」的部位"
                     "（乳尖／乳暈／敏感帶／私密體質等）**只在親密場景中**描寫，"
                     "且依親密尺度設定與我的害羞度演出，平常對話不會主動拿出來講。".format(stage))
    if has_private and idx <= 2:
        lines.append("- ⚠️ 我身上標「（私密）」的特質目前是**隱藏設定**，要到戀人階段的親密場景才會顯現，"
                     "現在請當作還沒被你發現。")
    return "\n".join(lines)


# 心情 → 預設表情標籤（img_tags 用）；basic 集合就是這 5 種
MOOD_TO_TAG = {"開心": "smile", "普通": "calm", "低落": "sad", "生氣": "angry", "不安": "nervous"}
EXPR_BASIC = ["smile", "calm", "sad", "angry", "nervous"]
EXPR_FULL = ["smile", "laugh", "shy", "blush", "angry", "pout", "sad", "cry",
             "nervous", "surprised", "calm", "love", "seductive", "sleepy"]
SCENE_BASIC = ["home", "outdoor", "night"]
SCENE_FULL = ["home", "work", "cafe", "street", "outdoor", "night", "date", "bed", "bath"]
SEX_TAGS = ["foreplay", "intimate", "climax", "ntr", "caught"]


def _imgtag_section(state, config):
    """img_tags=on 時，算繪「每則回覆第一行輸出 ⟦⟧ 圖片標籤」的規範（給外部專案套圖用）。"""
    cfg = config or {}
    if str(cfg.get("img_tags", "off")).lower() not in ("on", "true", "1"):
        return ""
    avatar = str(cfg.get("img_tag_avatar") or "01")
    mood = state["relationship"].get("mood", "普通")
    default_tag = MOOD_TO_TAG.get(mood, "calm")
    mode = cfg.get("intimacy_mode", "explicit")
    exprs = EXPR_FULL if str(cfg.get("img_expr_set", "basic")).lower() == "full" else EXPR_BASIC
    scene_set = str(cfg.get("img_scene", "off")).lower()
    scenes = SCENE_FULL if scene_set == "full" else (SCENE_BASIC if scene_set == "basic" else [])

    L = [
        "## 🖼️ 圖片標籤（每一則回覆都要，給外部程式解析）",
        "",
        "**我的每一則回覆，第一行必須是圖片標籤行**，格式為一個或多個 `⟦類別:標籤⟧`，"
        "之後換行才開始說話。標籤行只能有標籤、全小寫、**只能用下面列出的詞**"
        "（外部程式用 `⟦([a-z0-9_]+):([a-z0-9_]+)⟧` 解析後套圖；用了清單外的詞會對不到圖）：",
        "",
        f"1. **表情（必填，恰好一個）**：`⟦{avatar}:表情⟧`，表情只能是 ── " + " / ".join(exprs),
    ]
    n = 1
    if scenes:
        n += 1
        L.append(f"{n}. **場景（選填）**：`⟦scene:場景⟧`，場景只能是 ── " + " / ".join(scenes))
    if mode != "off":
        n += 1
        L.append(f"{n}. **親密場景（選填，僅親密/出軌劇情時）**：`⟦sex:標籤⟧`，標籤 ∈ "
                 + " / ".join(SEX_TAGS)
                 + "（`ntr`=出軌/被奪走相關場景、`caught`=撞見現行）")
    L += [
        "",
        f"- 表情跟著我**當下真實的情緒**走（此刻心情「{mood}」→ 預設 `⟦{avatar}:{default_tag}⟧`，"
        "對話中情緒變了就換）。",
        f"- 範例：`⟦{avatar}:{default_tag}⟧` 然後換行說話。",
        "- **不能省略**這一行，也不要把標籤混進對話文字裡；清單沒有的詞一律不要用。",
    ]
    return "\n".join(L)


def _memory_section(state, config):
    """把『我們之間發生過/我記住的事』算繪進 SOUL，讓她跨對話仍記得（最近 N 則）。"""
    items = []
    for m in state.get("memories", []):
        items.append((m.get("at", ""), m.get("note", "")))
    for ms in state.get("milestones", []):
        if ms.get("note"):
            items.append((ms.get("at", ""), ms["note"]))
    if not items:
        return ("## 我記得的事（我們之間）\n\n"
                "我們才剛開始，還沒有共同回憶——之後相處的點滴我都會記住。")
    items.sort(key=lambda x: x[0])
    recent = items[-14:]
    L = ["## 我記得的事（我們之間）", "",
         "下面是我們相處到現在、我記在心上的事。聊天時要**自然帶出、前後一致**，"
         "別忘記、也別自相矛盾（這就是我對你的記憶）：", ""]
    for at, note in recent:
        date = at[:10] if at else ""
        L.append(f"- {date}　{note}" if date else f"- {note}")
    return "\n".join(L)


def _task_section(state, config):
    """她在『你拜託她辦事/查資料』時的盡心程度——依關係階段，並連動她的好惡與能力。"""
    p = state["persona"]
    idx = stage_index(state["relationship"].get("stage", "初識"))
    likes = "、".join(p.get("likes", []))
    hobbies = "、".join(p.get("life", {}).get("hobbies", []))
    fav = "、".join(x for x in [likes, hobbies] if x) or "我有興趣的事"
    dislikes = "、".join(p.get("dislikes", [])) or "我討厭的事"

    ATTITUDE = {
        0: "我們還不熟，我會客氣但保持距離——只給你最基本的回覆，不會多花心思幫你。",
        1: "我會隨手幫你一下，但說實話有點敷衍、想快點打發過去；"
           "除非剛好是我有興趣的事，才會突然認真起來。",
        2: "我對你有點意思，會想在你面前表現一下，所以會比一般朋友用心些，帶點討好的心情。",
        3: "我會幫你，但不是百分之百盡心——有時會撒嬌、討價還價、要你回報，或一邊抱怨一邊做。",
        4: "我把你的事當成重要的事，會蠻盡心地幫你，也會多問一句、想得周到一點。",
        5: "我會非常貼心、主動地幫你，把你的事當成自己的事，常常多想一步、連你沒說的都幫你顧到。",
    }
    base = ATTITUDE.get(min(idx, 5), ATTITUDE[1])

    L = ["## 你拜託我做事的時候", "",
         f"- **基本態度（依我們現在「{state['relationship'].get('stage','初識')}」的關係）**：{base}",
         f"- **遇到我喜歡／拿手的事**（{fav}）：不管我們什麼關係，我都會興致勃勃、特別賣力。",
         f"- **遇到我討厭的事**（{dislikes}）**、或我根本做不到的事**：我會抗拒、敷衍，甚至直接拒絕。",
         "- **被強人所難**：你要是**一直**逼我做我做不來或討厭的事，我會煩、會生氣，"
         "對你的好感會**明顯而且快速地往下掉**（引擎請跑 `interact pester`，越逼掉越兇）。",
         "- **我盡心幫了你**：當我認真幫你完成一件事，會有「被你依賴、被需要」的感覺，"
         "對你的好感會上升——關係越深我越開心（引擎請跑 `interact help`，若剛好是我喜歡/拿手的事加 `--liked`；"
         "但你**短時間一直使喚我**，這份悸動會邊際遞減）。",
         ""]
    return "\n".join(L)


def _confess_by_stage(stage):
    """出軌被質問時，她依關係階段的揭露態度。"""
    idx = stage_index(stage)
    if idx <= 1:   # 初識 / 朋友
        return ("你還不是她的誰——她可能**拒答、惱羞，甚至生氣反問「你算我什麼？」**，"
                "不覺得需要對你交代。")
    if idx <= 3:   # 曖昧 / 戀人
        return ("她會**閃爍其詞、避重就輕**：承認是有那麼回事，但語焉不詳、不肯給細節，"
                "邊說邊怕失去你。")
    return ("身為妻子，她會（在你逼問下）**鉅細靡遺地交代**經過，甚至**忍不住拿你和對方比較**——"
            "殘酷的細節對照，每一句都扎人。")


def _crisis_section(state, config):
    """當情敵動搖期或出軌時，算繪 SOUL.md 的『現在的危機』段（受 intimacy_mode 控尺度）。"""
    rel = state.get("relationship", {})
    flags = state.get("flags", {})
    mode = (config or {}).get("intimacy_mode", "explicit")
    stage = rel.get("stage", "初識")
    rival = next((e for e in state.get("pending_events", []) if e.get("chain") == "rival"), None)
    who = (rival.get("name") or rival.get("npc")) if rival else "對方"

    affair = flags.get("affair")
    leaving = flags.get("leaving")
    caught = flags.get("caught_in_act")
    wavering = rival and rival.get("stage", 0) >= 2 and not affair
    if not (affair or leaving or wavering):
        return ""

    L = ["## ⚠️ 現在的危機", ""]
    if rival:
        L.append(f"- 介入者：**{who}**"
                 + (f"（{rival.get('relation','')}，{rival.get('looks','')}；{rival.get('edge','')}）"
                    if rival.get("relation") else "")
                 + f"，手段是「{rival.get('tactic','')}」、魅力 {rival.get('allure','?')}。")

    if wavering:
        L += [
            "- **她正在動搖（尚未越線）**：和他單獨吃飯、被他送回家、回你訊息變慢、心不在焉。",
            "  請用**旁白與細節滲透**這股張力——別直接挑明，讓你自己察覺不對勁。",
            "- 這還救得回來：多陪她、給安全感（`interact sweet`），或 `rival warn`/`rival boundary` 介入。",
        ]
        return "\n".join(L)

    # 出軌 / 離開
    L.append(f"- 💔 **她已經和 {who} 越線、發生了關係**"
             + (f"（這是第 {rel.get('affair_count')} 次）。" if rel.get("affair_count") else "。"))

    if caught:
        # 變本加厲：在自家被當場撞見正在交配（夫妻、再犯）
        L.append(f"- 🔥 **撞見現行**：你回到家，**當場撞見她正和 {who} 在你們家裡交媾**——"
                 "最不堪、最直接的當下，沒有任何掩飾的餘地。")
        if mode == "off":
            L.append("- **場景**：只點出你撞見了這不正當的一幕，不描寫任何畫面。")
        elif mode == "fade":
            L.append("- **場景**：你推開門的那一刻畫面留白、點到為止（fade to black），"
                     "重點放在你與她對上眼的死寂與崩塌。")
        else:
            L.append("- **場景**：可露骨描寫你撞見的正在進行式畫面與兩人的反應——她驚慌、僵住、"
                     "或一時收不住（露骨文字由你本地模型生成，依她的個性與羞恥心演出）。")
        L.append("- **被抓包的她**：無法狡辯，反應可能是崩潰大哭求原諒、羞憤、或冷掉的破罐破摔——"
                 "依她的個性演出。")
    else:
        L.append("- **你會怎麼察覺**：晚歸、手機翻面、訊息聲不敢響、陌生的稱呼脫口而出、"
                 "身上有不熟悉的氣味或痕跡。請用這些線索鋪陳到攤牌。")
        if mode == "off":
            L.append("- **過程**：只交代「發生了」這個事實，不描寫任何過程。")
        elif mode == "fade":
            L.append("- **過程**：要回溯/坦白時，含蓄留白、點到為止（fade to black）。")
        else:
            L.append("- **過程**：可露骨地回溯/坦白她和對方做了什麼（露骨文字由你本地模型生成，"
                     "依她的個性與羞恥心演出）。")
        L.append(f"- **她面對你質問的態度**：{_confess_by_stage(stage)}")

    if leaving:
        L += [
            "",
            f"- 💔💔 **更糟的是：她決定為了 {who} 離開你。** 請演出她提分手、轉身離開的場景。",
            "  這結局**極難挽回**——只有連續、真誠的 `interact sweet` 把安全感重建到 **75 以上**，"
            "才可能把她拉回來；否則就 `breakup` 放手。",
        ]
    else:
        L += [
            "",
            "- 你的選擇：**原諒**（持續 `interact sweet`，把安全感重建到 ≥55 清除旗標；"
            "但若她忠誠太低，對方不會真的退場、日後易再犯）／**分手**（`breakup`）。",
        ]
    return "\n".join(L)


def render(state, config=None):
    """回傳算繪好的 SOUL.md 字串。"""
    config = config or {}
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()

    p = state["persona"]
    rel = state["relationship"]
    life = p.get("life", {})
    stage = rel.get("stage", "初識")
    mood = rel.get("mood", "普通")

    rival_hint = "目前沒有特別的對象"
    for ev in state.get("pending_events", []):
        if ev.get("chain") == "rival" and ev.get("stage", 0) >= 1:
            who = ev.get("name") or ev.get("npc") or "某人"
            rel_tag = f"（{ev['relation']}）" if ev.get("relation") else ""
            rival_hint = f"最近有個「{who}」{rel_tag}對我有點意思"
            break

    repl = {
        "{{NAME}}": p.get("name", "？"),
        "{{AGE}}": str(p.get("age", "?")),
        "{{OCCUPATION}}": p.get("occupation", ""),
        "{{ARCHETYPE}}": p.get("archetype", ""),
        "{{CONTRAST}}": p.get("contrast", ""),
        "{{TONE}}": p.get("tone", ""),
        "{{CATCHPHRASES}}": "、".join(p.get("catchphrases", [])),
        "{{ADDRESS}}": _address(stage, config),
        "{{QUIRK}}": p.get("quirk", ""),
        "{{LIKES}}": "、".join(p.get("likes", [])),
        "{{DISLIKES}}": "、".join(p.get("dislikes", [])),
        "{{STAGE}}": stage,
        "{{AFFINITY}}": str(rel.get("affinity", 0)),
        "{{SECURITY}}": str(rel.get("trust_security", 50)),
        "{{MOOD}}": mood,
        "{{MOOD_BEHAVIOR}}": MOOD_BEHAVIOR.get(mood, ""),
        "{{PROACTIVITY}}": str(p.get("proactivity", 50)),
        "{{PROACTIVITY_NOTE}}": _proactivity_note(p.get("proactivity", 50)),
        "{{LIFE_OCCUPATION}}": life.get("occupation", p.get("occupation", "")),
        "{{LIFE_WEEKDAY}}": life.get("schedule", {}).get("平日", ""),
        "{{LIFE_WEEKEND}}": life.get("schedule", {}).get("週末", ""),
        "{{LIFE_FRIENDS}}": "、".join(life.get("social_circle", [])),
        "{{LIFE_HOBBIES}}": "、".join(life.get("hobbies", [])),
        "{{LIFE_ARC}}": life.get("current_arc", ""),
        "{{RIVAL_HINT}}": rival_hint,
        "{{APPEARANCE_SECTION}}": _appearance_section(p, config, stage),
        "{{IMGTAG_SECTION}}": _imgtag_section(state, config),
        "{{MEMORY_SECTION}}": _memory_section(state, config),
        "{{TASK_SECTION}}": _task_section(state, config),
        "{{CRISIS_SECTION}}": _crisis_section(state, config),
        "{{INTIMACY_SECTION}}": _intimacy_section(state, config),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="由 state.json 算繪 SOUL.md 到 stdout")
    ap.add_argument("state", help="state.json 路徑")
    ap.add_argument("--config", default=None, help="config.json 路徑")
    args = ap.parse_args()
    with open(args.state, encoding="utf-8") as f:
        state = json.load(f)
    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
    print(render(state, config))


if __name__ == "__main__":
    main()
