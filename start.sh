#!/usr/bin/env bash
#
# py-music-dl 一键启动脚本（macOS / Linux）
# 用法: ./start.sh [选项] [-- 透传给 gui.py 的参数]
#

set -u

# ---------- 基本路径 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$SCRIPT_DIR"
ENTRY="$ROOT/gui.py"
REQ_FILE="$ROOT/requirements.txt"
MIN_PY="3.10"

# ---------- 输出辅助（仅在终端中着色）----------
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_RESET=""
fi

info()  { printf '%s\n' "${C_BLUE}[*]${C_RESET} $*"; }
ok()    { printf '%s\n' "${C_GREEN}[OK]${C_RESET} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}[!]${C_RESET} $*"; }
error() { printf '%s\n' "${C_RED}[x]${C_RESET} $*" >&2; }
die()   { error "$*"; exit 1; }

usage() {
    cat <<EOF
${C_BOLD}py-music-dl 启动器${C_RESET} (macOS / Linux)

用法:
  ./start.sh [选项] [-- <gui.py 参数>]

选项:
  -h, --help     显示本帮助信息
  --check        仅检查运行环境与依赖，不启动程序
  --demo         以设计预览模式启动（演示数据，等价于 gui.py --demo）

示例:
  ./start.sh               启动 GUI
  ./start.sh --demo        启动设计预览
  ./start.sh --check       检查 Python / Tk / 依赖是否就绪

透传参数需放在 -- 之后，例如:
  ./start.sh -- --demo
EOF
}

# ---------- 参数解析 ----------
CHECK_ONLY=0
PASSTHROUGH=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --check)   CHECK_ONLY=1; shift ;;
        --demo)    PASSTHROUGH+=("--demo"); shift ;;
        --)        shift; PASSTHROUGH+=("$@"); break ;;
        *) error "未知参数: $1"; echo; usage; exit 2 ;;
    esac
done

[ -f "$ENTRY" ] || die "未找到主程序 ${ENTRY}（请在项目根目录运行本脚本）"

# ---------- 环境变量 ----------
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# ---------- 1. 定位 Python（优先项目虚拟环境）----------
PY=""
if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    error "未找到 Python（要求 Python ${MIN_PY}+）。"
    cat <<EOF >&2

  macOS:  brew install python python-tk
  Ubuntu/Debian: sudo apt install python3 python3-venv python3-tk
  Fedora: sudo dnf install python3 python3-tkinter
EOF
    exit 1
fi

PY_VER="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)" || die "无法执行 $PY"
info "Python: $PY ($PY_VER)"

# ---------- 2. 版本检查 ----------
if "$PY" -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    ok "Python 版本满足要求（>= ${MIN_PY}）"
else
    die "Python 版本过低：当前 ${PY_VER}，需要 ${MIN_PY}+。请升级后重试。"
fi

# ---------- 3. Tkinter 检查 ----------
if "$PY" -c "import tkinter" >/dev/null 2>&1; then
    ok "Tkinter 可用"
else
    error "Tkinter 不可用（GUI 必需）。"
    cat <<EOF >&2

  macOS(Homebrew Python): brew install python-tk
  Ubuntu/Debian:          sudo apt install python3-tk
  Fedora:                 sudo dnf install python3-tkinter
EOF
    exit 1
fi

# ---------- 4. 业务依赖检查 ----------
MISSING="$("$PY" - <<'PYEOF'
import importlib.util
mods = {"requests": "requests", "bs4": "beautifulsoup4", "lxml": "lxml"}
missing = [pkg for mod, pkg in mods.items() if importlib.util.find_spec(mod) is None]
print(" ".join(missing))
PYEOF
)"

if [ -z "$MISSING" ]; then
    ok "依赖检查通过（requests / beautifulsoup4 / lxml）"
else
    warn "缺少依赖: $MISSING"
    cat <<EOF >&2

请按以下方式安装（推荐使用项目虚拟环境）：

  ${C_BOLD}python3 -m venv .venv${C_RESET}
  ${C_BOLD}. .venv/bin/activate${C_RESET}
  ${C_BOLD}pip install -r "$REQ_FILE"${C_RESET}

之后重新运行 ./start.sh
EOF
    exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    ok "环境检查全部通过。"
    exit 0
fi

# ---------- 5. 启动 ----------
info "启动 py-music-dl …（Ctrl+C 退出）"
cd "$ROOT" || die "无法进入目录 $ROOT"
# bash 3.2 + set -u 下展开空数组会报 unbound variable，必须分支处理
if [ "${#PASSTHROUGH[@]}" -gt 0 ]; then
    exec "$PY" "$ENTRY" "${PASSTHROUGH[@]}"
else
    exec "$PY" "$ENTRY"
fi
