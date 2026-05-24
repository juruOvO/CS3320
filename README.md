# 戏曲文本可视化系统

## 运行前准备

需要提前安装：

- `Node.js 18+`
- `npm`（通常随 Node.js 一起安装）
- `Git`（如果你需要从 GitHub 拉代码）

可先检查版本：

```bash
node -v
npm -v
```

## Windows

建议安装：

- Node.js: [https://nodejs.org/](https://nodejs.org/)
- Git: [https://git-scm.com/download/win](https://git-scm.com/download/win)

运行：

```bash
git clone https://github.com/juruOvO/CS3320.git
cd CS3320
npm install
npm run dev
```

浏览器打开：

```bash
http://localhost:4173/
```

## macOS

建议安装：

- Node.js: [https://nodejs.org/](https://nodejs.org/)
- Git: 一般系统自带；没有的话可安装 Xcode Command Line Tools

运行：

```bash
git clone https://github.com/juruOvO/CS3320.git
cd CS3320
npm install
npm run dev
```

浏览器打开：

```bash
http://localhost:4173/
```

## Linux

先确保安装好 `node`、`npm`、`git`。

运行：

```bash
git clone https://github.com/juruOvO/CS3320.git
cd CS3320
npm install
npm run dev
```

浏览器打开：

```bash
http://localhost:4173/
```

## 常用命令

```bash
npm run dev
npm run build
npm run lint
npm run test
```

## 生产构建

```bash
npm install
npm run build
```

构建产物目录：

```bash
dist
```