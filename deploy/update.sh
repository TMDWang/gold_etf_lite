#!/bin/sh
# Run as the Git checkout owner. Docker access uses the current user or sudo.
set -eu

# Git may replace this script while it is running. Execute a temporary snapshot.
if [ "${GOLD_ETF_UPDATE_SNAPSHOT:-0}" != 1 ]; then
    project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
    snapshot=$(mktemp "${TMPDIR:-/tmp}/gold-etf-update.XXXXXX")
    trap 'rm -f -- "$snapshot"' EXIT HUP INT TERM
    cp -- "$0" "$snapshot"
    GOLD_ETF_UPDATE_SNAPSHOT=1 GOLD_ETF_PROJECT_DIR="$project_dir" sh "$snapshot"
    exit $?
fi

cd -- "${GOLD_ETF_PROJECT_DIR:?缺少项目目录}"
root=$(git rev-parse --show-toplevel) || { printf '%s\n' '无法找到 Git 仓库，请在克隆的项目中运行。' >&2; exit 1; }
[ "$root" = "$(pwd -P)" ] || { printf '%s\n' '当前目录不是项目仓库根目录。' >&2; exit 1; }
branch=$(git symbolic-ref --quiet --short HEAD) || { printf '%s\n' '当前没有处于分支上，已停止更新。' >&2; exit 1; }
[ "$branch" = main ] || { printf '%s\n' '当前分支不是 main，已停止更新。' >&2; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
    printf '%s\n' '发现未提交的项目文件，请先检查 git status；未拉取或更改文件。' >&2
    exit 1
fi

if docker info >/dev/null 2>&1; then
    use_sudo=0
elif command -v sudo >/dev/null 2>&1 && sudo -v && sudo docker info >/dev/null 2>&1; then
    use_sudo=1
else
    printf '%s\n' '无法访问 Docker，请检查服务及当前账号权限。' >&2
    exit 1
fi
docker_cmd() {
    if [ "$use_sudo" = 1 ]; then
        sudo GOLD_ETF_BUILD_REVISION="${GOLD_ETF_BUILD_REVISION:-unknown}" docker "$@"
    else
        docker "$@"
    fi
}

previous_revision=$(git rev-parse HEAD)
printf '%s\n' '1/4 正在备份数据库…'
docker_cmd compose exec -T app python manage.py backup
printf '%s\n' '2/4 正在安全拉取 main 分支…'
git pull --ff-only origin main
GOLD_ETF_BUILD_REVISION=$(git rev-parse HEAD)
export GOLD_ETF_BUILD_REVISION

printf '%s\n' '3/4 正在构建并等待 app 和 db 健康…'
if ! docker_cmd compose up -d --build --wait --wait-timeout 240; then
    docker_cmd compose ps >&2 || true
    printf '%s\n' '构建、启动或健康检查失败，请查看上方错误及容器状态。' >&2
    exit 1
fi

printf '%s\n' '4/4 正在核对运行版本…'
app_id=$(docker_cmd compose ps -q app)
running_revision=''
if [ -n "$app_id" ]; then
    running_revision=$(docker_cmd inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$app_id")
fi
if [ "$running_revision" != "$GOLD_ETF_BUILD_REVISION" ]; then
    printf '运行版本不符：期望 %s，实际 %s。\n' "$GOLD_ETF_BUILD_REVISION" "${running_revision:-未知}" >&2
    exit 1
fi
docker_cmd compose ps
printf '更新验收通过：%s → %s\n' "$previous_revision" "$running_revision"
