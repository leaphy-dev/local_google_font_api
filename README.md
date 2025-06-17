# Local Google Font API

本项目实现了一个本地化的 Google Fonts API 服务，支持字体子集化、缓存管理，并兼容 Google Fonts CSS API 语法。适合在内网或私有环境下部署，提升字体加载速度并保护隐私。

## 特性

- 支持 TTF/OTF 字体自动扫描与子集化
- 兼容 Google Fonts CSS API（如 `/css?family=Fira+Code`）
- 支持 unicode-range 子集，自动生成 woff2 格式
- 提供字体列表、预览页面
- 支持 CORS，适合前端跨域调用
- 支持多进程并发处理字体子集

## 安装

1. 克隆本仓库：

   ```bash
   git clone https://github.com/yourname/local_google_font_api.git
   cd local_google_font_api
   ```

2. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

   主要依赖：
   - aiohttp
   - fontTools

3. 准备字体文件：

   - 将 `.ttf` 或 `.otf` 字体文件放入 `fonts/` 目录。

4. 配置参数：

   - 编辑 `config.json`，设置监听地址、缓存时间等参数。

## 启动服务

```bash
python server.py
```

默认监听 `127.0.0.1:8000`，可通过 `config.json` 修改。

## API 说明

### 1. 获取 CSS

```
GET /css?family=Fira+Code
```

- 支持多个字体：`family=Fira+Code|Satisfy`
- 支持子集参数：`subset=latin,latin-ext`
- 支持 font-display：`display=swap`

### 2. 获取字体文件

```
GET /s/{woff2文件名}
```

### 3. 字体列表

```
GET /list
```

返回所有已导入字体及其信息。

### 4. 预览页面

```
GET /preview
```

## 目录结构

```
.
├── fonts/           # 放置原始字体文件
├── data/
│   ├── cache/       # 生成的woff2字体缓存
│   └── meta/        # 字体子集元数据
├── web/             # 前端页面
├── server.py        # 主服务入口
├── font_service.py  # 字体处理核心
├── utils.py         # 工具函数
├── config.json      # 配置文件
└── README.md
```

## 常见问题

- **如何添加新字体？**
  - 直接将字体文件放入 `fonts/` 目录，重启服务即可自动处理。

- **如何强制重建字体子集？**
  - 调用 `FontService.create_subset(font_file, force_rebuild=True)`。

## License

MIT
