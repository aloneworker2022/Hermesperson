#!/usr/bin/env bash
# 把 companion-soul 安裝到 Hermes 的 skills 目錄（建立連結）。
# 用法：bash install.sh [--copy]
#   預設用 symlink；--copy 則改成複製。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILLS_DIR="$HERMES_HOME/skills"
DEST="$SKILLS_DIR/companion-soul"

mkdir -p "$SKILLS_DIR"

if [[ "${1:-}" == "--copy" ]]; then
  rm -rf "$DEST"
  cp -r "$SRC" "$DEST"
  echo "已複製 skill 到 $DEST"
else
  rm -rf "$DEST"
  ln -s "$SRC" "$DEST"
  echo "已連結 skill 到 $DEST -> $SRC"
fi

# 確保包裝可執行
chmod +x "$SRC/bin/companion" "$SRC/bin/newOne" 2>/dev/null || true

# 安裝短指令到 ~/.local/bin（companion / newOne 可在任何目錄呼叫）
BINDIR="${COMPANION_BINDIR:-$HOME/.local/bin}"
mkdir -p "$BINDIR"
for cmd in companion newOne; do
  ln -sf "$SRC/bin/$cmd" "$BINDIR/$cmd"
done
echo "已安裝短指令到 $BINDIR：companion、newOne"

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
    companion status  看目前狀態
    companion <cmd>   等同 python3 scripts/relationship.py <cmd>

── 選用：讓她主動傳訊（Cron）──
本 skill 提供 `cron-msg` 產生「她主動傳訊」的指引。請在 Hermes 的 Cron（第 4 支柱）新增排程，
讓 agent 在指定時段執行：
    python3 ~/.hermes/skills/companion-soul/scripts/relationship.py cron-msg
建議時段：早上 / 中午 / 下班 / 睡前。Hermes 會把回傳的指引演成她主動發來的訊息。
（若你偏好用系統 crontab，也可自行排程，但 Hermes 內建 Cron 能直接讓她「開口」。）
EOF
