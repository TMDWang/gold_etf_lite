# 金笺 · 黄金 ETF 518880

手机使用的个人账本与到价提醒。Django + Vue 3 / Vant + PostgreSQL，部署在飞牛 NAS；沿用你已有的 Cloudflare 隧道。

这是首版可运行源码。**本地功能及页面已验证，尚未在你的 NAS 启动容器。**完整验证范围见 [验收记录](docs/验收记录.md)。构建不使用 GitHub Actions。

2026-10-22 启动优化版：打开先显示页面框架；账户、行情、计划和记录分别加载并提供错误重试；请求最长等待 12 秒。支持 PWA 页面资源缓存，曾成功联网缓存后，断开服务器仍能打开连接提示页。账户、密钥、交易响应不会放入离线缓存，也不离线提交或自动重试成交。

发现新版时会显示“更新页面”，由本人在没有打开编辑表单时点击更新，不强制打断正在填写的成交。图表单独按需加载；缓存被系统清理或第一次访问仍需联网下载，NAS 和网络本身的等待无法由缓存消除。

## 已有功能

- 一次性邀请码注册、登录、修改自己的密码；管理员只能发邀请、启停普通账号和看系统状态。
- 期初预算、现金、已有份额及成本；买入、部分卖出、清仓、现金变动、成交纠错与收益计算。
- 各一条买入／卖出计划；买入支持跌到买、涨到买；卖出支持目标价或本笔净收益率，并检查预计扣费后不亏损。
- 首页有当前价格、当天分时曲线、现金和持仓；行情失效仍可记账。
- 共享东财主行情、新浪备用行情；源时间校验；PushPlus 个人绑定、重复提醒、忽略及发送记录。
- 两个持久运行容器；进程心跳、每日数据库备份、受限日志大小。

系统不会连接券商或自动下单。每笔真实成交由你自己录入；提醒不是投资建议或收益保证。

## 飞牛 NAS 首次安装

将整个 `gold-etf-lite` 文件夹放到 NAS 上，例如 `/vol1/1000/docker/gold-etf-lite`。文件夹内必须有本说明、`compose.yaml`、`Dockerfile` 和代码目录。不要把 `sources/` 或整个 ChatGPT 项目当作构建目录。

1. 在 NAS 的终端进入此文件夹。以下命令都在此处执行。
2. 生成配置。已有 `.env` 时不要重复生成或替换密钥：

```sh
docker run --rm -it -v "$PWD:/work" -w /work python:3.12-slim python deploy/setup.py
```

按提示填**已有隧道的域名**，不带 `https://`。脚本在本地生成 `.env`，不会把密钥发到外部。NAS 已有 Python 3 时也可直接 `python3 deploy/setup.py`。

3. 检查 `.env`：`APP_PORT=8088` 是 NAS 端口，可改成未占用端口；域名、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS` 与 `PUBLIC_URL` 必须一致。生成后的 `.env` 包含数据库密码和加密密钥，请单独保存一份。
4. 构建并启动：

```sh
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

首次构建会下载公开依赖和镜像，需要 NAS 能访问 Docker Hub、npm、PyPI 及 PostgreSQL 软件源。无需 GitHub Actions。镜像未预先编译；NAS 首次构建可能需要数分钟。

5. 创建首个应用管理员（把 `owner` 换成你的用户名，密码按提示输入，不写在命令中）：

```sh
docker compose exec app python manage.py bootstrap_admin owner
```

6. 让已有隧道访问 NAS 的 `8088` 端口（或你设置的端口），从**已有 HTTPS 域名**打开网页。无需新建隧道。该应用为 HTTPS 设置了安全 Cookie，直接用 NAS 的 HTTP IP 地址不能完成正式登录。
7. 登录后录入期初资金和持仓；有持仓时须先核对并填写大于 0 的单位成本，未知成本不能填 0。点击右上角头像，填写自己券商的 ETF 费用参数。费率用小数：万分之 0.5 填 `0.00005`；最低收费和额外费用没有时明确填 `0`。未知参数留空时不会发送相关交易提醒。
8. 在个人设置绑定自己的 PushPlus Token，并按 PushPlus 要求实名认证。保存后由本人点击“向自己发送测试”。每位亲友绑定自己的 Token。管理员在头像中的管理页生成一次性邀请码，7 天内使用。

数据库只在 Docker 内网提供连接，不对 NAS 开放数据库端口。NAS 应用端口供已有隧道和可信局域网访问；不要另行把这个 HTTP 端口直接转发到公网。`.env`、数据库目录和备份目录由 NAS 维护者管理。

### 安装后核对

```sh
docker compose ps
docker compose logs --tail=80 app
docker compose exec app python manage.py probe_market
docker compose exec app python manage.py test --verbosity 1
docker compose exec app python manage.py backup
```

- `app`、`db` 应持续运行，`app` 在初始化约 90 秒后应变为 healthy。
- `probe_market` 应显示东财和新浪两个来源成功。非交易时段 `fresh=False` 正常；**还需在交易日 9:30–11:30 或 13:00–15:00 检查两个来源的时间足够新**。
- NAS 上运行测试使用独立测试数据库，不修改正式账本。默认初始化的 PostgreSQL 用户具有创建测试库的能力；如以后收紧数据库权限，应另行提供测试数据库。
- 所有推送自动化测试使用模拟发送器，不向真实微信发送。只有本人点击测试按钮或有效计划监测会实际推送。
- 故障时普通账号仍能使用记账接口；行情与监测状态在首页／系统页显示。

## 日常使用

**首页**：看价格、今日曲线、持仓和待处理提醒。当天缺少的数据留空；备用源只补采集到的时点，不伪造完整历史。

**计划**：同时保留下一笔买入和一条卖出计划。买入金额包含估计费用，并受现金、预算剩余成本额度和每手 100 份限制。卖出净收益率是**本笔预计卖出收益扣估算费用后，除以本笔结转成本**；价和收益率都填时任一达标即可，同时要求预计净收益不为负。

**记录**：到券商实际成交后返回确认，也可以不关联计划手工记账。计划实际成交一次即结束，部分成交后的剩余安排请重新建计划。实际亏损卖出仍可如实记录。重复点击同一张确认表只记一次。

**纠错**：原成交保留，追加纠错事件，然后重算本账户。资金变动录错时追加反向流水并写明原编号。重算会校验当时现金与份额；出现不足则整次纠错回滚，不丢原记录。

**成本顺序**：本版按**记账顺序**计算移动平均成本，成交时间用于标注。补录更早的成交不会自动重新插入历史成本顺序；请从期初之后按真实发生顺序记账，录错的原笔使用纠错入口。期初时点以前的交易已包含在期初余额中，不要重复入账。

**提醒**：默认每轮间隔 30 分钟、最多 3 次，可在个人设置调整；“暂不操作”只停止本轮，计划保留。条件退出再进入可开启新一轮；跨天、重启不自动清零。免费行情按约 60 秒采集，网页显示时每 30 秒刷新，不承诺捕捉每次瞬间触价。

推送成功表示服务已接收，不等于微信已送达。网络超时标为“结果未确认”，停止本轮自动重发，避免不确定的重复；明确拒绝最多尝试 3 次，并受额度约束。应用采用每 Token 保守上限：滚动 60 秒 4 次、24 小时 180 次，同内容滚动 1 小时 3 次，测试发送也计入。服务本身仍可能拒绝或调整规则。

## 更新与数据目录

```sh
docker compose build
docker compose up -d
```

启动自动运行数据库迁移。更新前先做备份，保留旧版源码包与 `.env`；数据库升级后不要直接用旧代码回退。不要运行 `docker compose down -v` 或删除 `data/postgres`。

| 位置 | 含义 |
| --- | --- |
| `data/postgres/` | PostgreSQL 正式数据，不能当成普通文件复制来做在线一致性备份 |
| `backups/gold_*.dump` | 每天北京时间 03:10 的数据库一致性备份，验证目录后保留最新 30 份 |
| `.env` | 密钥与连接配置，需独立安全保存；丢失原 ENCRYPTION_KEY 无法解密已绑定 Token |

备份在同一 NAS 上，不覆盖整台 NAS 或全部磁盘损毁。全库文件包含个人数据，不提供应用管理员下载入口。恢复前须停止正式写入；完整步骤见 [备份与恢复](docs/备份与恢复.md)。

## 忘记密码

NAS 维护者核实账号本人后执行：

```sh
docker compose exec app python manage.py recover_password 用户名
```

应用管理员网页不提供任意重置他人密码、代登录或资金查询。应用管理员不是 Django 超级用户；本项目不挂载 Django `/admin/`。NAS／数据库最高权限维护者仍可读取存储数据，这是本版明确的信任边界。

## 开发验证

Python 3.12、Node 24、pnpm 11.25。先在独立 Python 虚拟环境安装 `requirements.lock`。Windows 本地开发允许 `DEBUG=1` 的 SQLite 验证；正式环境必须 PostgreSQL。

```sh
pip install -r requirements.lock
cd frontend
pnpm install --frozen-lockfile
pnpm test
pnpm build
cd ..
python manage.py test
```

本地启动另设 `DEBUG=1`、随机 `SECRET_KEY`；运行 `python manage.py migrate`、`python manage.py collectstatic --noinput` 后 `python -m waitress --listen=127.0.0.1:8000 config.wsgi:application`。监测另开终端运行 `python manage.py monitor`；可选真实推送仍须配置 ENCRYPTION_KEY。本地只使用测试账号和虚构金额。不要将 DEBUG=1 用于对外部署。

交易日历由固定版本 `exchange-calendars` 的 XSHG 提供。本次实测覆盖到 **2026-12-31**。超过有效范围停止提醒，需要维护者根据正式交易所日历更新依赖并验证，不按工作日猜测开市日期。源接口变化、免费限流及 NAS 网络也需要维护。

## 主要依据

- [上交所 ETF 常见问题（100份、0.001元）](https://www.sse.com.cn/assortment/fund/etf/question/)
- [Django 事务与锁](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [AKShare ETF 数据适配文档](https://akshare.akfamily.xyz/data/fund/fund_public.html)（本版直接使用 requests 窄接口适配，减少全量行情组件依赖）
- [XSHG 日历源码](https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar_xshg.py)
- [PushPlus 使用及额度](https://pushplus.plus/doc/guide/use.html)、[消息接口](https://pushplus.plus/doc/guide/api.html)
- [PostgreSQL 一致性备份](https://www.postgresql.org/docs/17/backup-dump.html)
