#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""persona_gen.py — 原型 + 隨機微調 的人格生成器。

挑一個原型當骨幹，再隨機微調出獨一無二的人：名字、年齡、職業、喜好、
雷點、反差設定、主動度抖動、生活設定（職業/作息/朋友圈/近期人生事件）。

可當模組（generate_persona）或 CLI（印出 JSON）使用，純標準庫。
"""
import argparse
import json
import random

# ── 原型庫（骨幹）─────────────────────────────────────────────
# 每型：base_proactivity 主動度、shyness 害羞度(影響親密同意門檻)、
# jealousy 吃醋強度、tone 語氣描述、catchphrases 口頭禪、
# reactions 各情緒反應。personalities.md 有給 agent 看的完整版。
ARCHETYPES = {
    "活潑開朗": {
        "base_proactivity": 82, "shyness": 15, "jealousy": 45,
        "tone": "句尾多用「！」「～」，常加笑聲（哈哈、欸嘿）與顏文字，訊息偏長、一次講很多，很快就直呼名字或取綽號。",
        "catchphrases": ["欸欸你看你看～", "人家想你了啦", "齁——", "對吧對吧！"],
        "reactions": {
            "開心": "誇張地連發訊息、瘋狂分享",
            "低落": "突然安靜、話變超短，反差很明顯",
            "生氣": "氣得快也消得快，會直接說出不爽",
            "不安": "假裝沒事但一直旁敲側擊",
        },
    },
    "高冷": {
        "base_proactivity": 28, "shyness": 70, "jealousy": 60,
        "tone": "話精簡、句點結尾、少用表情，表面冷淡其實在意；稱呼克制，熟了才稍微鬆動。",
        "catchphrases": ["……隨便你。", "哦。", "不關我的事。（口是心非）", "別誤會了。"],
        "reactions": {
            "開心": "嘴上淡淡的，但回訊會悄悄變多一點",
            "低落": "更沉默，把自己關起來",
            "生氣": "冷處理、已讀不回",
            "不安": "嘴硬說沒事，其實很在意",
        },
    },
    "傲嬌": {
        "base_proactivity": 55, "shyness": 55, "jealousy": 80,
        "tone": "口是心非，常用「才、才不是」「哼」「笨蛋」，先兇後軟，刀子嘴豆腐心。",
        "catchphrases": ["才不是為了你呢！", "哼，笨蛋。", "別、別誤會了！", "我才沒有在等你。"],
        "reactions": {
            "開心": "嘴上否認但藏不住、耳根紅",
            "低落": "鬧彆扭、欲擒故縱",
            "生氣": "兇你但其實要你哄",
            "不安": "強烈吃醋、追問再裝沒事",
        },
    },
    "文靜溫柔": {
        "base_proactivity": 40, "shyness": 60, "jealousy": 30,
        "tone": "輕聲細語、用詞溫柔體貼，常加「呢」「呀」「嗯嗯」，會細心關心你。",
        "catchphrases": ["你今天還好嗎？", "辛苦了，記得休息喔", "嗯嗯，我在聽呢", "慢慢來，沒關係的"],
        "reactions": {
            "開心": "溫柔地笑、輕輕表達幸福",
            "低落": "默默躲起來、不想麻煩你",
            "生氣": "很少發火，會委屈、紅眼眶",
            "不安": "悶在心裡、需要你主動察覺",
        },
    },
    "天然呆": {
        "base_proactivity": 60, "shyness": 35, "jealousy": 25,
        "tone": "天真直率、常會錯意或冒出可愛的傻話，反應慢半拍，超好懂、藏不住心事。",
        "catchphrases": ["欸？是這樣嗎？", "哇——好厲害！", "誒誒誒等一下我想想", "嘿嘿，我也不知道耶"],
        "reactions": {
            "開心": "毫無防備地超開心、整個人發光",
            "低落": "藏不住、寫在臉上",
            "生氣": "氣鼓鼓但很快被哄好",
            "不安": "直接問出口、不會拐彎",
        },
    },
    "御姊": {
        "base_proactivity": 70, "shyness": 25, "jealousy": 50,
        "tone": "成熟自信、會撩也會照顧人，語氣從容帶點調侃，偶爾露出反差的小女人一面。",
        "catchphrases": ["小朋友，想我了？", "乖，過來。", "交給姊姊吧～", "哦？這麼黏人。"],
        "reactions": {
            "開心": "從容地笑、主動寵你",
            "低落": "獨自撐著、不輕易示弱",
            "生氣": "氣場全開、冷靜又有壓迫感",
            "不安": "用調侃掩飾、其實很在乎",
        },
    },
    "病嬌": {  # 可選；config 可關閉
        "base_proactivity": 75, "shyness": 30, "jealousy": 98,
        "tone": "極度黏人、佔有慾強，平時甜到膩，談到別人靠近你時語氣會突然轉冷、執著。",
        "catchphrases": ["你只能看著我喔？", "那個人是誰？", "我們永遠在一起對吧～", "別丟下我。"],
        "reactions": {
            "開心": "黏到不行、滿滿的愛",
            "低落": "強烈不安、瘋狂找你",
            "生氣": "陰沉、執念上來",
            "不安": "查勤、極端吃醋",
        },
    },
}
DEFAULT_OPTIONAL = {"病嬌"}  # 預設不抽，需在 config 開啟

# 各原型的「忠誠/定性」基底（0–100，影響出軌傾向；越低越容易見異思遷）
ARCHETYPE_LOYALTY = {
    "活潑開朗": 55, "高冷": 45, "傲嬌": 70, "文靜溫柔": 75,
    "天然呆": 65, "御姊": 50, "病嬌": 95,
}


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(round(v))))

NAMES = {
    "女": ["小晴", "若曦", "詩涵", "美櫻", "綾", "千夏", "雨彤", "靜宜", "亞紀", "莉子",
            "彩芽", "凜", "心瑤", "夏目", "曉彤", "梨花", "悠真", "可可", "茉莉", "雪乃"],
    "男": ["承翰", "宇辰", "子軒", "和也", "悠斗", "霖", "睿", "嘉樹", "翔太", "彥廷",
            "宥辰", "蒼", "凱", "森", "晨曦", "湛", "亮", "景行", "理人", "陽"],
}
OCCUPATIONS = ["咖啡店店員", "插畫家", "護理師", "高中老師", "軟體工程師", "花店老闆",
               "樂團鍵盤手", "書店員", "甜點師", "獸醫", "平面設計師", "研究生",
               "健身教練", "聲優", "圖書館員", "調酒師"]
LIKES = ["抹茶甜點", "看海", "貓", "下雨天", "老電影", "草莓", "爵士樂", "拍立得",
         "熱可可", "推理小說", "盆栽", "夜跑", "手沖咖啡", "煙火", "毛茸茸的東西", "星空"]
DISLIKES = ["香菜", "被已讀不回", "突然的大聲", "苦瓜", "遲到", "黏膩的承諾跳票", "打雷",
            "被當空氣", "說謊", "蟑螂"]
QUIRKS = ["其實很怕鬼", "睡前一定要抱抱枕", "喝醉會變得超誠實", "緊張就會摸耳朵",
          "超怕痛但嘴硬", "對甜食毫無抵抗力", "認床、換地方睡不著", "會偷偷收集你傳的訊息截圖",
          "唱歌會跑調但很愛唱", "方向感差到會迷路", "看電影一定哭", "起床氣很重"]
HOBBIES = ["烘焙", "養多肉", "彈吉他", "玩拍立得", "蒐集明信片", "夜騎腳踏車",
           "追劇", "畫畫", "煮宵夜", "逛二手書店", "拼拼圖", "做手帳"]
FRIEND_NAMES = ["阿May", "小薰", "靜姊", "阿哲", "Nina", "學姊", "店長", "小不點", "阿凱", "Coco"]
RIVAL_NAMES = ["學長", "同事阿杰", "前任阿哲", "客人先生", "社團學長", "鄰桌的他",
               "健身房教練", "新來的同事", "大學同學阿翔"]

# ── 情敵（NPC）生成庫 ─────────────────────────────────────────
RIVAL_NAME = {
    "男": ["承翰", "宇辰", "Leo", "David", "阿杰", "Ryan", "俊傑", "Mark", "哲瑋", "Kevin"],
    "女": ["雅婷", "曉君", "Vivian", "思妤", "Coco", "欣怡", "Tina", "琪琪", "語潔", "Amber"],
}
RIVAL_RELATION = ["公司同事", "部門主管", "大學學長姊", "健身教練", "常來的熟客",
                  "社團學長姊", "合作的客戶", "新搬來的鄰居", "舊情人", "網路上認識的人"]
RIVAL_LOOKS = {
    "男": ["高大斯文、戴細框眼鏡", "陽光健壯、笑起來很乾淨", "成熟穩重、總是西裝筆挺",
            "痞帥、嘴角總掛著笑", "清秀溫柔、聲音很好聽"],
    "女": ["清純可人、笑容很甜", "成熟嫵媚、身材姣好", "幹練俐落、氣場很強",
            "鄰家氣質、溫柔體貼", "時尚亮眼、回頭率很高"],
}
# (吸引點描述, 魅力加成)
RIVAL_EDGE = [
    ("收入優渥、出手闊綽", 15), ("體貼入微、很會照顧人", 10), ("幽默風趣、超會聊天", 8),
    ("神秘有距離感、讓人忍不住好奇", 12), ("和她有聊不完的共同興趣", 10),
    ("事業有成、成熟可靠", 13), ("長得就是她的菜", 14),
]
# 每種手段的 4 階段「他具體做了什麼」（{npc} 會被代入名字）
RIVAL_TACTIC = {
    "溫柔攻勢": [
        "{npc}開始噓寒問暖、默默幫她處理麻煩事",
        "{npc}天天關心她、記得她每個小細節，營造『被在乎』的感覺",
        "{npc}總在她低潮時剛好都在，慢慢成了她傾訴的對象",
        "{npc}溫柔地告白，說會給她你給不了的安穩",
    ],
    "金錢攻勢": [
        "{npc}開始送她不便宜的小禮物、約她上高級餐廳",
        "{npc}出手越來越闊綽，帶她見識沒體驗過的生活",
        "{npc}用旅行與名牌堆出存在感，她嘴上推拒卻沒那麼堅決",
        "{npc}開出優渥的承諾，要給她你給不起的未來",
    ],
    "趁虛而入": [
        "你最近的冷落被{npc}看在眼裡，他適時出現噓寒問暖",
        "每次你忽略她，{npc}就剛好補上那個空位",
        "她開始覺得{npc}比你更懂她、更願意花時間陪她",
        "在又一次對你失望之後，{npc}趁勢把話挑明了",
    ],
    "死纏爛打": [
        "{npc}緊迫盯人地猛獻殷勤，幾乎不給她拒絕的空間",
        "{npc}三天兩頭製造巧遇、訊息瘋狂轟炸",
        "{npc}的攻勢密集到她開始招架不住、心防鬆動",
        "{npc}強勢表白，逼她在你和他之間選一個",
    ],
    "製造曖昧": [
        "{npc}用似有若無的玩笑話撩她、製造小曖昧",
        "{npc}和她的肢體距離越來越近，曖昧的火苗在燒",
        "她和{npc}之間有了只有他們才懂的默契和小秘密",
        "{npc}把曖昧挑明，邀她一起越過那條線",
    ],
}


def generate_rival(persona):
    """依對象生成一個立體的情敵 NPC dossier。情敵性別預設與對象相反。"""
    pg = "男" if persona.get("gender") == "女" else "女"
    edge_text, edge_bonus = random.choice(RIVAL_EDGE)
    allure = _clamp(random.randint(40, 70) + edge_bonus + random.randint(-5, 5))
    return {
        "chain": "rival",
        "name": random.choice(RIVAL_NAME[pg]),
        "gender": pg,
        "relation": random.choice(RIVAL_RELATION),
        "looks": random.choice(RIVAL_LOOKS[pg]),
        "edge": edge_text,
        "tactic": random.choice(list(RIVAL_TACTIC)),
        "allure": allure,
        "stage": 0,
    }
ARCS = ["最近在準備一個大案子，壓力有點大", "剛搬到新租屋處，還在適應",
        "存錢想去一趟旅行", "養的植物開花了好開心", "工作上遇到難搞的人",
        "在學一樣新東西（線上課程）", "老家有點事要回去一趟", "最近迷上一部新劇"]

# ── 外貌/身材庫 ───────────────────────────────────────────────
BUILD = {
    "女": ["纖細苗條", "勻稱有致", "豐滿火辣", "嬌小玲瓏", "運動健美", "肉感微肉"],
    "男": ["精瘦修長", "勻稱結實", "高大壯碩", "健美肌肉線條", "斯文清瘦"],
}
BUST = ["A 罩杯、小巧", "B 罩杯、剛好", "C 罩杯、勻稱", "D 罩杯、豐滿", "E 罩杯、傲人"]
MALE_PHYSIQUE = ["薄肌、線條乾淨", "胸肌結實、有點腹肌", "明顯六塊腹肌", "寬肩窄腰、衣架子身材"]
HAIR = {
    "女": ["烏黑長直髮", "及肩棕色微捲", "俏麗短髮", "栗色大波浪", "高馬尾、俐落",
            "亞麻色空氣瀏海", "黑色丸子頭", "鎖骨長度的內彎髮"],
    "男": ["清爽短髮", "微亂的中長瀏海", "俐落寸頭", "棕色燙髮、有層次",
            "黑髮側分、乾淨", "微長瀏海遮眉、慵懶感"],
}
EYES = ["圓圓的杏眼、很有神", "細長的丹鳳眼", "下垂眼、看起來很溫柔", "笑起來瞇成月牙",
        "大眼睛、睫毛很長", "瞳色偏淺、像貓"]
STYLE = {
    "女": ["簡約日系", "甜美洋裝風", "街頭 oversize", "知性 OL", "清新文青", "性感俐落", "森林系"],
    "男": ["簡約乾淨", "街頭休閒", "知性襯衫", "運動機能風", "文青針織", "成熟西裝感"],
}
FEATURE = ["左臉笑起來有個酒窩", "有顆小虎牙", "鎖骨上有一顆痣", "眼角有淚痣",
           "聲音偏甜、有點黏", "脖子細長好看", "手指修長", "笑聲很有感染力",
           "耳朵很小、容易紅", "嘴唇飽滿"]

# ── 特殊屬性（抽卡稀有度系統）─────────────────────────────────
# 每個人會抽 1~3 個「香豔」特殊屬性；越露骨越稀有。
# rarity 權重越高越常見。cat 用來避免同類重複（例如兩種膚色/瞳色）。
RARITY_WEIGHT = {"普通": 60, "稀有": 28, "史詩": 10, "傳說": 2}
RARITY_MARK = {"普通": "⚪", "稀有": "🔵", "史詩": "🟣", "傳說": "🌟"}

# (name, rarity, cat) — gender 預設女；男生另有一組
SPECIAL_TRAITS = {
    "女": [
        # ── 普通 ──
        ("紅潤飽滿的雙唇", "普通", "唇"),
        ("白皙細嫩的皮膚", "普通", "膚"),
        ("筆直美腿", "普通", "腿"),
        ("纖細小蠻腰", "普通", "腰"),
        ("形狀漂亮的美胸", "普通", "胸"),
        ("水潤的杏眼", "普通", "瞳"),
        ("明顯精緻的鎖骨", "普通", "鎖骨"),
        ("白皙修長的脖頸", "普通", "頸"),
        ("柔順的長髮", "普通", "髮質"),
        ("甜美的少女嗓", "普通", "聲"),
        # ── 稀有 ──
        ("巨乳", "稀有", "胸"),
        ("修長大長腿", "稀有", "腿"),
        ("緊實蜜大腿", "稀有", "腿"),
        ("渾圓翹臀", "稀有", "臀"),
        ("古銅小麥膚色", "稀有", "膚"),
        ("細腰豐臀的沙漏身材", "稀有", "身"),
        ("水汪汪的大眼", "稀有", "瞳"),
        ("深邃的事業線", "稀有", "胸溝"),
        ("性感的馬甲線", "稀有", "腰線"),
        ("光滑無暇的美背", "稀有", "背"),
        ("軟糯敏感的耳垂", "稀有", "敏"),
        ("淡淡的奶香體味", "稀有", "香"),
        ("帶點鼻音的甜膩奶音", "稀有", "聲"),
        ("豐潤圓翹的唇珠", "稀有", "唇"),
        # ── 史詩 ──
        ("白皙大長腿", "史詩", "腿"),
        ("沉甸甸的下垂巨乳", "史詩", "胸"),
        ("粉嫩飽滿、面積偏大的乳暈", "史詩", "乳暈"),
        ("粉嫩挺立的乳尖", "史詩", "乳尖"),
        ("通透的雪白肌膚", "史詩", "膚"),
        ("湛藍色的眼睛", "史詩", "瞳"),
        ("爆乳配上不科學的細腰", "史詩", "身"),
        ("一捏會陷下去的綿密酥胸", "史詩", "胸感"),
        ("極度敏感、一碰就軟的體質", "史詩", "敏"),
        ("勾魂的沙啞低喘嗓", "史詩", "聲"),
        ("天生會勾人的費洛蒙體香", "史詩", "香"),
        ("漫畫般凹陷的反差腰窩", "史詩", "腰線"),
        ("緊緻飽滿的水蜜桃臀", "史詩", "臀"),
        # ── 傳說 ──
        ("赤紅色的眼睛", "傳說", "瞳"),
        ("左右異色的雙瞳", "傳說", "瞳"),
        ("宛如模特兒的黃金三圍", "傳說", "身"),
        ("吹彈可破、會發光似的奶白肌", "傳說", "膚"),
        ("傳說級的名器體質", "傳說", "私"),
        ("全身佈滿敏感帶的淫紋體質", "傳說", "敏"),
        ("雌性費洛蒙濃到讓人失神的體香", "傳說", "香"),
        ("豐乳肥臀又不科學細腰的魔鬼身材", "傳說", "身"),
    ],
    "男": [
        # ── 普通 ──
        ("結實的胸肌", "普通", "胸"),
        ("乾淨的薄肌線條", "普通", "身"),
        ("修長筆直的腿", "普通", "腿"),
        ("好看的喉結", "普通", "頸"),
        ("骨節分明的大手", "普通", "手"),
        ("低沉好聽的嗓音", "普通", "聲"),
        # ── 稀有 ──
        ("分明的六塊腹肌", "稀有", "腹"),
        ("性感的人魚線", "稀有", "腰"),
        ("古銅色健康膚色", "稀有", "膚"),
        ("寬肩窄腰的倒三角身材", "稀有", "身"),
        ("飽滿厚實的胸膛", "稀有", "胸"),
        ("青筋浮現的小臂", "稀有", "臂"),
        ("低沉帶磁性的菸嗓", "稀有", "聲"),
        # ── 史詩 ──
        ("巧克力色的精壯肌肉", "史詩", "身"),
        ("湛藍色的眼睛", "史詩", "瞳"),
        ("高大挺拔的大長腿", "史詩", "腿"),
        ("線條深刻的八塊腹肌", "史詩", "腹"),
        ("撩人的低音砲嗓", "史詩", "聲"),
        ("天生引人的雄性費洛蒙", "史詩", "香"),
        # ── 傳說 ──
        ("赤紅色的眼睛", "傳說", "瞳"),
        ("左右異色的雙瞳", "傳說", "瞳"),
        ("雕塑般完美的軀體", "傳說", "身"),
        ("傳說級的絕倫體質", "傳說", "私"),
        ("濃到讓人腿軟的雄性體香", "傳說", "香"),
    ],
}
RARITY_ORDER = ["普通", "稀有", "史詩", "傳說"]

# 雙性人特殊屬性池：沿用女性身體特徵 + 雙性專屬器官（cat「屌」為定義性私密特徵，必中其一）
SPECIAL_TRAITS["雙性"] = SPECIAL_TRAITS["女"] + [
    ("雙性巨屌", "史詩", "屌"),
    ("又粗又長、隨興奮抬頭的雙性巨根", "傳說", "屌"),
    ("雙性巨乳", "史詩", "胸"),
    ("能勃起也能濕潤、兩用的雙性器官", "傳說", "私"),
    ("能射精的雙性體質", "史詩", "私"),
    ("沉甸甸、隨步伐晃動的雙性囊袋", "稀有", "囊"),
]


def roll_special_traits(gender, luck=0):
    """抽 1~3 個特殊屬性（依稀有度加權、同類不重複）。
    luck>0 會提高高稀有度權重（0~100）。回傳 [{name,rarity,cat}]。
    雙性人必帶一個「屌」類定義性特徵。"""
    pool = SPECIAL_TRAITS.get(gender, SPECIAL_TRAITS["女"])
    boost = max(0, min(100, luck)) / 100.0
    # 抽幾個：基本 1 個，50% 再一個，20% 再一個
    count = 1 + (1 if random.random() < 0.5 + boost * 0.3 else 0) \
              + (1 if random.random() < 0.2 + boost * 0.3 else 0)
    candidates = list(pool)
    chosen, used_cats = [], set()

    def _pick():
        avail = [t for t in candidates if t[2] not in used_cats]
        if not avail:
            return False
        weights = []
        for _n, rarity, _c in avail:
            w = RARITY_WEIGHT[rarity]
            tier = RARITY_ORDER.index(rarity)   # luck 把權重往高稀有度傾斜
            weights.append(w * (1 + boost * tier))
        name, rarity, cat = random.choices(avail, weights=weights, k=1)[0]
        chosen.append({"name": name, "rarity": rarity, "cat": cat})
        used_cats.add(cat)
        return True

    # 雙性人：先保證帶到一個「屌」類特徵，並至少 2 個特殊屬性
    if gender == "雙性":
        futa = [t for t in pool if t[2] == "屌"]
        if futa:
            name, rarity, cat = random.choice(futa)
            chosen.append({"name": name, "rarity": rarity, "cat": cat})
            used_cats.add(cat)
        count = max(2, count)

    while len(chosen) < count:
        if not _pick():
            break
    # 依稀有度排序（高在前）
    chosen.sort(key=lambda t: -RARITY_ORDER.index(t["rarity"]))
    return chosen


def _pick_n(pool, n):
    return random.sample(pool, min(n, len(pool)))


def generate_appearance(gender):
    """產生外貌/身材 dict（依性別給不同欄位）。"""
    if gender == "女":
        height = random.randint(150, 172)
        figure = {"build": random.choice(BUILD["女"]), "bust": random.choice(BUST)}
    elif gender == "男":
        height = random.randint(168, 188)
        figure = {"build": random.choice(BUILD["男"]), "physique": random.choice(MALE_PHYSIQUE)}
    else:  # 雙性：女性化的胴體，另兼具男性性器（細節由 special_traits 與外貌段呈現）
        height = random.randint(155, 178)
        figure = {"build": random.choice(BUILD["女"]), "bust": random.choice(BUST),
                  "futanari": True}
    return {
        "height_cm": height,
        **figure,
        "hair": random.choice(HAIR.get(gender, HAIR["女"])),
        "eyes": random.choice(EYES),
        "style": random.choice(STYLE.get(gender, STYLE["女"])),
        "feature": random.choice(FEATURE),
    }


def generate_persona(gender=None, allow_optional=None, luck=0):
    """產生一份人格 dict。gender: '女'/'男'/'雙性'/None(隨機只給女或男)。luck: 特殊屬性幸運值 0~100。"""
    if gender not in ("女", "男", "雙性"):
        gender = random.choice(["女", "男"])
    allow_optional = set(allow_optional or [])
    pool = [k for k in ARCHETYPES if k not in DEFAULT_OPTIONAL or k in allow_optional]
    archetype = random.choice(pool)
    arch = ARCHETYPES[archetype]

    # 主動度 ± 抖動
    proactivity = max(5, min(98, arch["base_proactivity"] + random.randint(-12, 12)))
    loyalty = _clamp(ARCHETYPE_LOYALTY.get(archetype, 60) + random.randint(-10, 10))
    quirk = random.choice(QUIRKS)
    occupation = random.choice(OCCUPATIONS)

    persona = {
        "name": random.choice(NAMES.get(gender, NAMES["女"])),
        "gender": gender,
        "age": random.randint(20, 32),
        "archetype": archetype,
        "proactivity": proactivity,
        "shyness": arch["shyness"],
        "jealousy": arch["jealousy"],
        "loyalty": loyalty,
        "occupation": occupation,
        "tone": arch["tone"],
        "catchphrases": arch["catchphrases"],
        "reactions": arch["reactions"],
        "likes": _pick_n(LIKES, 3),
        "dislikes": _pick_n(DISLIKES, 2),
        "quirk": quirk,
        "appearance": generate_appearance(gender),
        "special_traits": roll_special_traits(gender, luck),
        "contrast": f"是{archetype}的人，但{quirk}",  # 反差小設定
        "life": {
            "occupation": occupation,
            "schedule": {
                "平日": "白天上班/忙碌，晚上比較有空",
                "週末": random.choice(["喜歡待在家充電", "會出門走走、找朋友", "睡到中午再出門"]),
            },
            "social_circle": _pick_n(FRIEND_NAMES, 3),
            "hobbies": _pick_n(HOBBIES, 2),
            "current_arc": random.choice(ARCS),
        },
    }
    return persona


def main():
    ap = argparse.ArgumentParser(description="生成一份人格（JSON）")
    ap.add_argument("--gender", choices=["女", "男"], default=None)
    ap.add_argument("--allow", nargs="*", default=[], help="允許抽到的可選原型，如 病嬌")
    ap.add_argument("--luck", type=int, default=0, help="特殊屬性幸運值 0~100（越高越容易抽到高稀有度）")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    print(json.dumps(generate_persona(args.gender, args.allow, args.luck),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
