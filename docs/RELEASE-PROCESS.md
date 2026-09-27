# 发版流程（分支模型 · 门禁 · 合入 master）

> 一句话：**代码只在 `dev/optimize` 上改；`master` 由脚本生成，只能经 PR + CI + Review 合入。**

---

## 1. 分支模型

```
   dev/optimize  ──●──●──●──●──●──●──●──●   ← 唯一开发入口，含 docs/ 与全部测试
                    \                    \
                     \  scripts/sync-master.sh（取代码 − 排除清单）
                      \                    ↓
   master  ────────●───┴────────────────  ●  ← 上线分支，只有一个个 release 提交
                                             部署机 /opt/orbit 只跟它
```

| 分支 | 定位 | 内容 | 谁能写 |
|---|---|---|---|
| `dev/optimize` | 开发分支 | 完整开发树：代码 + `docs/` + `backend/test/` + 前端测试 + 本地产物 | 直接 push（CI 自动跑） |
| `master` | 上线分支 | `dev/optimize` **减去**排除清单；无文档、无测试 | **只能经 PR 合入**，禁止直接 push |

**排除清单**（唯一事实源：`scripts/sync-master.sh` 的 `STATIC_EXCLUDES`）：
`docs/`、`backend/test/`、`frontend/test/`、`frontend/src/test/`、
`frontend/vitest.config.{ts,mts}`、前端 `*.test.ts(x)`、`.playwright-cli/`、
`login.yaml`、`main.png`、`ui-01-initial.png`、根目录 3 个方案 md、脚本自身。

### 两条必须遵守的不变量

1. **`dev/optimize` 必须是 `master` 的超集。**
   需要新增"只在线上存在"的文件（如 `LICENSE`）时，**加到 `dev/optimize`**，
   再由同步脚本带过去；**不要在 `master` 上单独加文件**——那会让两分支长期分叉。
2. **`master` 上不要手工改任何文件。**
   下一次同步会以 `dev/optimize` 的文件树整体覆盖 `master`，手工改动会被静默冲掉。
   CI 的 `Release sync check` 会拦住这类 PR。

### 为什么 `master` 不含测试，但 CI 仍然测它

`master` 是 `dev/optimize` 的**子集**，代码逐字节一致（仅少掉被排除的开发资产）。
所以流水线统一在 `dev/optimize` 的代码上跑——验证 dev 等价于验证上线代码。
（若直接在 `master` 上跑 pytest，会因为没有测试目录而收集不到用例、直接失败。）

---

## 2. 日常开发（改代码）

```bash
git switch dev/optimize
# ...改代码...
git commit -m "fix(xxx): ..."
git push origin dev/optimize        # CI 自动触发：后端 pytest + 前端 lint/类型/单测/构建
```

CI 挂在哪：

| 事件 | 触发的 job |
|---|---|
| `push` 到 `dev/optimize` | Backend tests、Frontend checks、Dependency scan |
| `pull_request` → `master` | 上面全部 + **Release sync check** |

**改运行时代码请在 `dev/optimize` 上改**；如果发现某个问题只在 `master` 才需要，
先想清楚——多半说明它本该属于 dev（见不变量 1）。

---

## 3. 发版（把 dev 的成果推上线）

### 步骤 1 — 生成 release 分支并发起 PR

```bash
git switch dev/optimize          # 确保工作区干净
bash scripts/sync-master.sh
```

脚本会：
1. 以 `origin/master` 为基线，套用 `dev/optimize` 的文件树，剔除排除清单；
2. **提交前自检**——「与 dev 的差异」必须恰好等于排除清单，否则直接中止；
3. 在本地与远端创建 `release/sync-<devsha>` 分支（只含 **1 个** release 提交）；
4. 打印可直接点开的 PR 链接。

> 幂等：若 dev 自上次发版后只在排除路径（如 `docs/`）有改动，脚本会提示
> "无需发版" 且不产生空提交。

### 步骤 2 — 开 PR 并等门禁

打开脚本打印的链接，创建 PR（base = `master`）。三个 job 必须全绿：

| Job | 检查什么 | 是否阻塞 |
|---|---|---|
| `Backend tests` | `pytest test/`（在 `dev/optimize` 的代码上） | ✅ 阻塞 |
| `Frontend checks` | `npm run lint` / `typecheck` / `test` / `build` | ✅ 阻塞 |
| `Release sync check` | PR 内容是否**恰好**等于「dev − 排除清单」（拦住手工改 master） | ✅ 阻塞 |
| `Dependency scan` | `pip-audit` 依赖漏洞 | ❌ 仅提示 |

### 步骤 3 — Code Review

在 PR 的 **Files changed** 页逐文件过一遍 diff。重点看：

- 有没有把不该上线的东西带进来（`.env`、密钥、本地路径、调试开关）；
- `Release sync check` 报出的差异列表是否都是"本来就不该上线"的文件；
- 改动的行为面（鉴权、迁移、配置默认值）是否有对应测试。

### 步骤 4 — 合入并部署

Review 通过、CI 全绿后合并 PR。因为 `release/*` 就是 `master` + 1 个提交，
合并是 fast-forward，`master` 历史仍然只有一个个 release 提交。

```bash
# 服务器
cd /opt/orbit
git pull --ff-only origin master
docker compose build
docker compose up -d
docker compose ps
curl -s localhost/ready
```

---

## 4. master 分支保护配置（一次性，需在 GitHub 网页操作）

本机没有 `gh` 也没有 token，所以这一步需要手工点一次。

`Repository → Settings → Branches → Add branch protection rule`（或 `Rulesets`）：

| 配置项 | 值 | 作用 |
|---|---|---|
| Branch name pattern | `master` | |
| ✅ Require a pull request before merging | 开 | **禁止直接 push master**，这是硬门槛 |
| └ Required approvals | `1`（有第二个协作者时）／`0`（单人仓库） | 单人仓库无法给自己点赞同，见下方说明 |
| ✅ Require status checks to pass | 开 | 强制 CI 门禁 |
| └ 勾选这三个 | `Backend tests`、`Frontend checks`、`Release sync check` | |
| ✅ Require branches to be up to date before merging | 开 | 防止"绿了之后 base 又变了" |
| ✅ Require conversation resolution | 开 | 未处理的 review 意见不能合 |
| ⬜ Do not allow bypassing the above settings | **保持不勾** | 留出紧急 bypass 通道，`--direct` 才有意义 |
| ❌ Allow force pushes / deletions | 关 | 禁止改写与删除上线分支 |

> **单人仓库的 review 怎么办**：GitHub 不允许给自己的 PR 点赞同，所以把自己设成
> required approver 会导致永远合不进去。单人可以设 `Required approvals = 0`，
> 但**保留**"Require a pull request"与三个必过检查——这样 CI 与"必须走 PR"是强制的，
> Review 变成你的自觉动作：在 Files changed 里过完 diff，留一条 review comment
> 说明结论，再合。

---

## 5. 应急通道与回滚

### 线上出事，要绕过门禁直推

```bash
bash scripts/sync-master.sh --direct     # 需手工输入 yes 确认
```

会绕过 PR 与 CI 直接改写 `master`。**仅限线上回滚等紧急场景**，事后补一次 PR 说明。
注意：如果分支保护里勾了 "Do not allow bypassing"，这条路径会被 GitHub 拒绝。

### 回滚到上一个 release

```bash
git switch master && git pull
git log --oneline -5              # 找到上一个 release 提交
```

不要用 `reset --hard` 改写已上线的历史，走 PR 反向恢复：

```bash
git switch -c hotfix/revert-release <坏提交的父提交>
git push -u origin hotfix/revert-release
# 开 PR 合入 master
```

或者直接 `git revert <sha>` 开 PR。

### 本地安全点

改造为"干净上线分支"之前的历史保存在本地标签 `backup/master-pre-release-sync`。

---

## 6. 常见问题

**Q：脚本说"无需发版"但 dev 明明有新提交？**
看那些提交是否只动了排除清单里的路径（`docs/`、测试、截图）。是的话 `master`
本来就应该没有变化，属于正常。

**Q：`Release sync check` 失败了怎么办？**
它列出的每一行都是"dev 有、release 没有，但**不在排除清单里**"的文件，
或者"已排除的文件却出现在 release 上"。前者说明发版时 dev 已推进、需要重跑
`scripts/sync-master.sh`；后者说明有人在 release 分支上手工改了东西。

**Q：CI 里 `Backend tests` 在 PR 上测的是哪个版本？**
测 `dev/optimize` 的当前 tip，不是 PR 分支。因为 PR 分支就是它的子集，
而 `Release sync check` 保证了两者一致。
