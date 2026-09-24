# 火山灰喷发端元混合审计

火山灰层可能由多个喷发端元混合而成。本系统用**精确有理数**寻找解释目标示踪值的
**最小端元凸组合**，避免把落在凸包内部的混合误判为单一来源：

1. **最少化正权端元数**（最小支撑，R³ 中至多 4 个端元）；
2. 再**最小化所选端元的复核代价和**；
3. 同优时按**标识序列字典序**确定唯一规范解；
4. 并把每个端元归类为在前两级（最少端元数 ∧ 最小代价）同优解中
   **所有（always）/ 部分（partial）/ 从不（never）** 出现。

- `api/` — FastAPI 后端，`fractions.Fraction` 精确算术（Bareiss/RREF，无浮点）
- `web/` — React + TypeScript + Vite 前端，nginx 提供静态文件与 API 反代
- `verify/` — Compose 中的一次性校验服务
- `docker-compose.yml` — 三服务协同

## 快速开始

```bash
cp .env.example .env        # 可选：修改宿主机端口 API_PORT / WEB_PORT
docker compose up --build
# Web:  http://localhost:${WEB_PORT:-8080}
# API:  http://localhost:${API_PORT:-8000}/health
```

宿主机端口均可通过环境变量配置（`.env` 或 shell）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `API_PORT` | 8000 | API 发布到宿主机的端口（容器内固定 8000） |
| `WEB_PORT` | 8080 | Web 发布到宿主机的端口（容器内固定 80） |

两个容器均带 Docker `HEALTHCHECK`（API 检 `/health`，Web 检 `/healthz`）。

## 一次性校验（verify）

```bash
docker compose build verify
docker compose run --rm verify
```

`verify` 是一次性服务，依次检查并**按结果退出码**（0 全通过 / 1 有失败）：

1. 后端代码测试（容器内运行 pytest）；
2. 规范分数权重（四面体内点 → 四个 `1/4`；四位小数目标 `0.125` → `7/8 + 1/8`）；
3. 凸包外目标 `feasible=false` 且无解；
4. 同优归类（等代价两条对角线 → 四个端元皆 partial；唯一解 → always/never）；
5. 构建产物（Web 容器返回构建后的 `index.html` 且 JS bundle 可访问）；
6. API 冒烟（直连与经 Web 代理的 `/health`、`POST /api/audit`）；
7. 长标识大同优集（30 个约 1000 字符标识、四组 7/7/8/8 → `tie_count=3136`）：
   首次响应只内联一页且远小于全量展开，规范解与 1/4 精确权重保留，30 个端元
   全部归类 partial，并逐页取回全部 3136 组同优解核对顺序、权重与出现计数；
   构建后的 UI 必须使用编号懒加载同优解浏览器（`/api/audit/ties`）。

## HTTP 接口

- `GET /health` → `{"status":"ok"}`
- `POST /api/audit`

```json
{
  "endmembers": [
    {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"}
  ],
  "target": ["1", "1", "1"]
}
```

响应仍给出规范解、精确权重、精确 `tie_count` 与基于**全部**前两级同优解的
`classification`，但同优解明细只内联第一页（`tied` 至多 `tie_page_size` 组，
默认 20；另含 `tie_offset`）。同优解很多、标识很长时，这避免首次响应反复展开
全部解（数万 KB）。其余同优解经无状态分页接口按需获取：

- `POST /api/audit/ties`

```json
{
  "endmembers": [ /* 与 /api/audit 完全相同的审计输入 */ ],
  "target": ["1", "1", "1"],
  "offset": 20,
  "limit": 20
}
```

返回 `{"offset", "tie_count", "solutions": [...]}`，`solutions` 为按标识字典序
排列的同优解中 `[offset, offset+limit)` 这一页。客户端每次重放审计输入，服务端
不保存结果集；翻页不改变 `tie_count` 与归类，二者始终由完整枚举得出。

输入以原始文本提交，错误按字段定位（如 `endmembers[2].t1`、`target[0]`），
非法输入或凸包外无解时前端**保留全部编辑内容**并就地高亮反馈。

### 输入规则

- 每批 3–30 个端元，标识为唯一 ASCII 非空字符串；
- 三个示踪值为整数，绝对值 ≤ 1,000,000；
- 复核代价为正整数；
- 目标三值为至多四位小数的数值（允许负数）。

### 求解正确性要点

- 权重恒为既约分数（`numerator/denominator`，附规范字符串 `fraction`）；
- 枚举 1–4 元子集，对仿射无关列解齐次线性方程组，严格正权才接受；
  零权情形归入更小的子集，因此“最少化正权端元数”语义精确；
- 30 端元最坏规模（枚举 C(30,4)）秒级完成。

## 本地开发（不经 Docker）

```bash
# API
python3 -m venv .venv && . .venv/bin/activate
pip install -r api/requirements-dev.txt
(cd api && uvicorn app.main:app --reload --port 8000)

# Web（Vite 把 /api 与 /health 代理到 8000）
(cd web && npm install && npm run dev)
```

## 测试

```bash
(cd api && pytest -q)
```
