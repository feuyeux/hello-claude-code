# Claude Code 源码在 WebStorm 中 Debug 的可行性方案


这个项目的实际启动入口是 `src/entrypoints/cli.tsx`，`package.json` 中的开发脚本也是直接执行它：

- `bun run dev`
- `bun run src/entrypoints/cli.tsx`

从源码看，这个仓库不是“先编译再用 Node 调试”的典型 Node CLI 项目，而是 **Bun 直接运行 TypeScript/TSX 源码** 的项目。源码里还直接使用了 `bun:bundle`：

- `src/main.tsx`
- `src/QueryEngine.ts`
- `src/query.ts`

所以：

1. `Node.js + ts-node/tsx` 直接替代 Bun 跑源码，不是主路径。
2. 最稳妥的方案是 `WebStorm + Bun 运行/调试配置`。
3. 如果 WebStorm 对 Bun 断点支持不稳定，再退回到 `Bun inspector + WebStorm Attach`。


已验证以下命令可直接运行：

```bash
bun run src/entrypoints/cli.tsx --version
```

输出：

```text
2.1.888 (Claude Code)
```

同时也确认到一个调试相关事实：

- Bun 支持 `--inspect` / `--inspect-wait` / `--inspect-brk`
- 也就是说，Bun 侧本身具备调试能力

## 可行方案（可多轮调试）

### 适用场景

你希望在 WebStorm 里：

- 直接打开源码断点
- 从入口启动 CLI
- 单步进入 `main.tsx`、`query.ts`、`QueryEngine.ts`

### 核心思路

直接把 `src/entrypoints/cli.tsx` 作为运行入口，让 WebStorm 通过 Bun 启动它。

这条链路的好处是：

- 没有额外构建步骤
- 断点就是源码断点
- 不依赖 `dist/cli.js` 的 sourcemap
- 与仓库当前开发方式一致

### WebStorm 配置建议

先确认两件事：

1. WebStorm 已启用 Bun 支持
2. WebStorm 已识别本机 Bun 可执行文件

然后创建一个新的 Bun 运行配置，推荐参数如下：

- Working directory: 项目根目录
- JavaScript file: `src/entrypoints/cli.tsx`
- Bun arguments: 先留空
- Application arguments: `--version`

第一步先用 `--version` 做连通性验证，确认 WebStorm 能从 IDE 内成功拉起该 CLI。

验证通过后，再切到真实调试参数，例如：

```text
-p  -c "我们刚才聊了些什么"
```
-p 为控制台打印输出，  -c 为继续上一轮谈话

```

如果你已经配置了 API Key，也可以直接调试主对话链路，但我不建议第一步就这么做，因为交互链路更长，排障成本更高。

### 推荐断点位置

第一批断点建议下在这些文件：

- `src/entrypoints/cli.tsx`
- `src/main.tsx`
- `src/query.ts`
- `src/QueryEngine.ts`

建议优先看的位置：

1. `src/entrypoints/cli.tsx`
   先看参数分流和动态 import 逻辑。
2. `src/main.tsx`
   这里是 Commander 注册、初始化流程、print 模式和 REPL 主流程。
3. `src/query.ts`
   这里是一次 agentic turn 的主循环。
4. `src/QueryEngine.ts`
   这里是会话状态和流式处理的核心。

### 适合先用的启动参数

优先级从低风险到高风险：

1. `--version`
2. `doctor`
3. `-p "hello"`
4. 直接无参数进入交互模式

建议不要一开始就用“纯交互 REPL + 真实 API 请求 + 工具调用”，这样一旦断点没命中，很难判断是 IDE 配置问题还是业务流程问题。

## 备用方案 B

### 适用场景

如果 WebStorm 直接调 Bun 配置时出现以下问题，可以切到这个方案：

- 断点不命中
- Bun 运行正常，但 IDE 无法进入调试态
- 某些 TSX 文件断点映射异常

### 核心思路

先在终端用 Bun 以 inspector 模式启动，再让 WebStorm 用 “Attach to Node.js/Chrome” 之类的方式附加。

参考命令：

```bash
bun run --inspect-wait=127.0.0.1:9229 src/entrypoints/cli.tsx --version
```

或者：

```bash
bun run --inspect-brk=127.0.0.1:9229 src/entrypoints/cli.tsx doctor
```

然后在 WebStorm 里创建 attach 配置，连到 `127.0.0.1:9229`。

### 这个方案的价值

- 启动和附加分离，排查更直接
- 如果问题出在 WebStorm 的 Bun Run 配置，这个方案通常更稳
- 适合精确排查某个入口函数是否已执行

### 注意事项

如果 inspector 端口冲突，就换端口，例如：

- `9229`
- `9230`
- `9329`

如果 attach 不上，不要先怀疑业务代码，先确认：

1. 端口没被占用
2. WebStorm attach 的目标端口与 Bun 启动端口一致
3. 你是以 `src/entrypoints/cli.tsx` 启动，而不是调了别的包装脚本


## 相关源码入口

- `src/entrypoints/cli.tsx`
- `src/main.tsx`
- `src/query.ts`
- `src/QueryEngine.ts`
- `package.json`

