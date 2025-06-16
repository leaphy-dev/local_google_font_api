import hashlib
import io
import json
import logging
from importlib.metadata import metadata
from pathlib import Path
from sys import meta_path
from textwrap import dedent
from typing import Dict

from aiohttp import web
import os

from font_service import FontService
from utils import find_files_by_extension

BASE_DIR = Path(__file__).parent

WEB_DIR = BASE_DIR / "web"
LOG_DIR = BASE_DIR / "logs"

DATA_DIR = BASE_DIR / "data"
METADATA_DIR = DATA_DIR /"meta"
FONT_DIR = BASE_DIR / "fonts"


config_file = open("./config.json", "r")
config: Dict = json.loads(config_file.read())
config_file.close()

BASE_URL: str = config["BASE_URL"]
CACHE_MAX_AGE: int = config["CACHE_MAX_AGE"]
FONT_MAX_AGE: int = config["FONT_MAX_AGE"]
LOG_RETENTION_DAYS: int = config["LOG_RETENTION_DAYS"]




def setup_logging():
    """配置日志系统"""
    LOG_DIR.mkdir(exist_ok=True, parents=True)

    # 主日志
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
setup_logging()


async def handle_index(request):
    """处理主页请求"""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        return web.Response(text="Homepage not found", status=404)

    return web.FileResponse(index_file)


async def handle_css(request):
    font_family = request.query.get("family", "")
    display = request.query.get("display", "swap")
    subsets = request.query.get("subset", "").split(',')
    font_family = font_family.replace("+", " ")
    if not font_family:
        return web.Response(text="family parameter is required", status=400)

    try:
        css_rules = []
        for font_spec in set(font_family.split('|')):  # 改集合，去重
            parts = font_spec.split(':')
            font_name = parts[0]
            variants = parts[1].split(',') if len(parts) > 1 else ['400']

            weight, style = "400", "normal"
            for variant in variants:
                if 'italic' in variant:
                    style = "italic"
                    weight = variant.replace('italic', '') or '400'
                else:
                    weight = variant

                font_service: FontService = request.app["font_service"]
                meta_data_list = font_service.get_meta_data(font_name)
                # 生成每个子集的@font-face规则
                for meta_data in meta_data_list:
                    font_url = f"/s/{meta_data['woff2_file_name']}"
                    unicode_range = meta_data["subset_range"]
                    css_rules.append(dedent(f"""
                        /* [{meta_data['subset']}] */
                        @font-face {{
                            font-family: '{font_name}';
                            font-style: {style};
                            font-weight: {weight};
                            src: url('{font_url}') format('woff2');
                            unicode-range: {unicode_range};
                            font-display: {display};
                        }}
                        """))

        css = "\n".join(css_rules)
        return web.Response(text=css, content_type="text/css")

    except Exception as e:
        return web.Response(text=str(e), status=500)


async def handel_preview(request):
    preview_file = WEB_DIR / "preview.html"
    if not preview_file.exists():
        return web.Response(text="Page not found", status=404)
    return web.FileResponse(preview_file)


async def handel_font_list(request):
    """列出fonts目录下所有TTF字体并自动演示的handler"""
    font_service = request.app["font_service"]
    font_dir = font_service.font_dir

    try:
        # 获取所有.ttf文件
        fonts = []
        for filename in os.listdir(font_dir):
            if filename.lower().endswith('.ttf') or filename.lower().endswith('.otf'):
                font_name = os.path.splitext(filename)[0]
                font_path = os.path.join(font_dir, filename)
                file_size = os.path.getsize(font_path)

                fonts.append({
                    "name": font_name,
                    "filename": filename,
                    "size": file_size,
                    "size_mb": round(file_size / (1024 * 1024), 2),
                    "url": f"{BASE_URL}/font?family={font_name}"})

        # 按字体名排序
        fonts.sort(key=lambda x: x["name"].lower())

        # 构建响应数据
        response_data = {
            "status": "success",
            "count": len(fonts),
            "fonts": fonts
        }

        return web.Response(
            text=json.dumps(response_data),
            status=200,
            content_type="application/json"
        )

    except Exception as e:
        error_response = {
            "status": "error",
            "message": str(e)
        }
        return web.Response(
            text=json.dumps(error_response),
            status=500,
            content_type="application/json"
        )

async def init_app():
    app = web.Application()
    front_server = app["font_service"] = FontService()
    for ttf in find_files_by_extension(FONT_DIR, ["ttf", "otf"]):
        front_server.create_subset(ttf.name)

    app.router.add_get("/css", handle_css)
    app.router.add_get("/css2", handle_css)
    app.router.add_get("/preview", handel_preview)
    app.router.add_get("/list", handel_font_list)
    app.router.add_get("/", handle_index)
    app.router.add_static("/s", BASE_DIR / "data/cache")

    return app


if __name__ == "__main__":
    web.run_app(init_app(), port=8080)