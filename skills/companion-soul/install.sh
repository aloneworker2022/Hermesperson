#!/usr/bin/env bash
# 把 companion-soul 安裝到 Hermes 的 skills 目錄（建立連結）。
# 用法：bash install.sh [--copy]
#   預設用 symlink；--copy 則改成複製。
set -euo pipefail

# 解析腳本所在的「實體」路徑（pwd -P 會穿透 symlink），避免從 symlink 目錄執行時
# 把 SRC 算成 symlink 本身，導致 ln -s 自己→自己 的無限迴圈（ELOOP）。
SRC="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILLS_DIR="$HERMES_HOME/skills"
DEST="$SKILLS_DIR/companion-soul"

mkdir -p "$SKILLS_DIR"

# 防呆：若 DEST 已是壞掉/自我參照的 symlink，先清掉（rm 對 symlink 只刪連結本身）
if [[ -L "$DEST" ]]; then
  rm -f "$DEST"
fi

# 防呆：SRC 與 DEST 指向同一個實體 → 不要建立自我連結
DEST_REAL="$(cd -P "$DEST" >/dev/null 2>&1 && pwd -P || true)"
if [[ -n "$DEST_REAL" && "$DEST_REAL" == "$SRC" ]]; then
  echo "略過連結：$DEST 已指向來源 $SRC（無需重建）。"
elif [[ "${1:-}" == "--copy" ]]; then
  rm -rf "$DEST"
  cp -r "$SRC" "$DEST"
  echo "已複製 skill 到 $DEST"
else
  rm -rf "$DEST"
  ln -s "$SRC" "$DEST"
  echo "已連結 skill 到 $DEST -> $SRC"
fi

# 確保包裝可執行
chmod +x "$SRC"/bin/* 2>/dev/null || true

# 安裝短指令到 ~/.local/bin（任何目錄都能呼叫）
BINDIR="${COMPANION_BINDIR:-$HOME/.local/bin}"
mkdir -p "$BINDIR"
for cmd in companion newOne bye us; do
  ln -sf "$SRC/bin/$cmd" "$BINDIR/$cmd"
done
echo "已安裝短指令到 $BINDIR：companion、newOne、bye、us"

# 自我檢查：引擎可執行
if python3 "$DEST/scripts/relationship.py" status >/dev/null 2>&1; then
  echo "引擎自我檢查：OK"
fi

# PATH 提示
case ":$PATH:" in
  *":$BINDIR:"*) ;;
  *) echo "⚠ $BINDIR 不在 PATH。請加到你的 shell 設定（擇一）：";
     echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc   # bash";
     echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc    # zsh";
     echo "  然後重開終端機或 source 一次。" ;;
esac

cat <<'EOF'

── 完成 ──
1) 在 Hermes 裡這個 skill 會以 description 自動觸發；或直接叫它「companion-soul」。
2) 第一次使用時它會備份你現有的 SOUL.md（到 ~/.hermes/relationship/soul.original.bak），
   再生成第一個對象。隨時可用 `companion restore` 還原。

── 短指令（任何目錄都能用）──
    newOne            換一個全新的人（自動先 breakup 再生成）
    newOne 女         指定性別
    us                看目前狀態
    bye [理由]        跟目前對象分手
    companion <cmd>   等同 python3 scripts/relationship.py <cmd>

── 選用：讓她主動傳訊（Cron + 非同步信箱）──
她的主動訊息採「非同步信箱」：不推播 alert，存著等你下次打開聊天（checkin）才看到。
請在 Hermes 的 Cron（第 4 支柱）排程，讓 agent 定時執行兩步：
    1) python3 ~/.hermes/skills/companion-soul/scripts/relationship.py cron-msg
    2) 若 cron-msg 回的是生成指引（不是「不發/還在等」），就以她的身分寫出那則訊息，再執行：
       python3 .../relationship.py inbox add "<她的訊息原文>" --theme <cron-msg 指示的主題>
建議每 1~2 小時跑一次（睡覺時段會自動不發）。等不到回覆她會升級鬧脾氣（越稀有越沒耐性）。
（若你偏好用系統 crontab，也可自行排程，但 Hermes 內建 Cron 能直接讓她「開口」。）
EOF
