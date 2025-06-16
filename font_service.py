import concurrent
import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

from font_subset import SUBSET
from utils import find_files_by_extension

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
FONT_DIR = BASE_DIR / "fonts"

CACHE_DIR = DATA_DIR / "cache"
METADATA_DIR = DATA_DIR /"meta"

class FontService:
    def __init__(self, font_dir=FONT_DIR, cache_dir=CACHE_DIR, meta_dir=METADATA_DIR):
        self.font_dir = font_dir
        self.cache_dir = cache_dir
        self.meta_dir = meta_dir

        # 确保目录存在
        os.makedirs(self.font_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.meta_dir, exist_ok=True)

        self.meta_cache:Dict = {}

    @staticmethod
    def get_subset_cache_key(font_name, subset_name):
        """生成缓存键 - 使用字体名和文本内容的MD5哈希"""
        key_str = f"{font_name}:{subset_name}"
        return hashlib.md5(key_str.encode('utf-8')).hexdigest()

    @staticmethod
    def parse_unicode_range(range_str) -> set:
        """
        解析Unicode范围字符串，返回单个字符或范围
        支持格式: "U+4e54", "U+300c-300d", "U+91d7-91d8"
        """
        parts: list = [part.strip() for part in range_str.split(',')]
        result = set()

        for part in parts:
            if not part:
                continue

            if '-' in part:
                # 处理范围格式 "U+300c-300d"
                start_str, end_str = part.split('-', 1)
                start_str = start_str.strip().upper()
                end_str = end_str.strip().upper()

                # 提取十六进制值
                start_hex = start_str[2:] if start_str.startswith('U+') else start_str
                end_hex = end_str[2:] if end_str.startswith('U+') else end_str

                try:
                    start = int(start_hex, 16)
                    end = int(end_hex, 16)
                    result.update(range(start, end + 1))
                except ValueError:
                    print(f"无效的范围格式: {part}")
            else:
                # 处理单个字符格式 "U+4e54"
                char_str = part.strip().upper()
                hex_val = char_str[2:] if char_str.startswith('U+') else char_str

                try:
                    result.add(int(hex_val, 16))
                except ValueError:
                    print(f"无效的字符格式: {part}")
        return result

    # def parse_unicode_str(self, unicode_str):
    #     result = set()
    #     unicode_list = unicode_str.strip(",")
    #     for unicode_str in unicode_list:
    #         if unicode_str.startswith("U+"):
    #             if "-" in unicode_str:
    #                 result.update(self.parse_unicode_range(unicode_str))
    #             else:
    #                 unicode_str = unicode_str[2:]
    #                 result.add(int(unicode_str, 16))
    #     return result

    def get_cached_subset(self, cache_key):
        """检查是否有缓存的子集字体"""
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.woff2")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return f.read()
        return None

    def create_subset(self, font_file_name, force_rebuild: bool = False):
        """创建字体子集（跳过已存在文件）"""
        font_family = font_file_name.removesuffix(".ttf")
        font_family = font_family.removesuffix(".otf")
        _font_path = FONT_DIR / font_file_name
        meta_data_file_dir = METADATA_DIR / font_family
        os.makedirs(meta_data_file_dir, exist_ok=True)

        # 准备需要处理的任务
        tasks = []
        skipped_count = 0

        for subset_name, subset in enumerate(SUBSET):
            subset_name = str(subset_name)
            woff2_file_name = f"{self.get_subset_cache_key(font_family, subset_name)}"
            cached_font_file = CACHE_DIR / (woff2_file_name + ".woff2")

            # 检查文件是否存在且不需要重建
            if cached_font_file.exists() and not force_rebuild:
                skipped_count += 1
            else:
            # 添加到任务列表
                tasks.append({
                    "subset": subset,
                    "subset_name": subset_name,
                    "woff2_file_name": woff2_file_name,
                    "_font_path": _font_path
                })

        print(f"Total tasks: {len(tasks)}, Skipped: {skipped_count}")

        # 获取CPU核心数
        num_cores = int(multiprocessing.cpu_count() / 2 )

        # 如果有需要处理的任务
        if tasks:
            print(f"Processing {len(tasks)} subsets using {num_cores} cores...")

            # 使用进程池执行任务
            with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
                # 提交所有任务到进程池
                futures = {}
                for task in tasks:
                    future = executor.submit(self._process_single_subset, task)
                    futures[future] = task["subset_name"]

                # 等待所有任务完成并处理结果
                for future in concurrent.futures.as_completed(futures):
                    subset_name = futures[future]
                    try:
                        result = future.result()
                        print(result)
                    except Exception as e:
                        print(f"Error processing subset {subset_name}: {str(e)}")
        else:
            print(f"Font {font_family}. All subsets are already generated. Use force_rebuild=True to regenerate.")

        # 生成元数据文件（跳过已存在的元数据）
        for subset_name, subset in enumerate(SUBSET):
            subset_name = str(subset_name)
            woff2_file_name = f"{self.get_subset_cache_key(font_family, subset_name)}"
            meta_data_file_path = meta_data_file_dir / (woff2_file_name + ".json")

            # 检查元数据文件是否需要生成
            if not meta_data_file_path.exists() or force_rebuild:
                meta_data = {
                    "font_family": font_family,
                    "subset_range": subset,
                    "woff2_file_name": (woff2_file_name + ".woff2"),
                    "subset": subset_name
                }
                meta_data_file_path.write_text(json.dumps(meta_data))

    def _process_single_subset(self, task):
        """处理单个字体子集"""
        subset = task["subset"]
        subset_name = task["subset_name"]
        woff2_file_name = task["woff2_file_name"]
        _font_path = task["_font_path"]

        cached_font_file = CACHE_DIR / (woff2_file_name + ".woff2")

        # 生成子集字体
        options = Options()
        options.flavor = ".woff2"
        options.drop_tables += ['FFTM']
        options.with_zopfli = True
        subsetter = Subsetter(options=options)
        subsetter.populate(unicodes=self.parse_unicode_range(subset))
        font = TTFont(file=_font_path, ignoreDecompileErrors=True)
        subsetter.subset(font)
        font.save(cached_font_file,  reorderTables=False)

        return f"Generated subset {subset_name}: {woff2_file_name}.woff2"


        # TODO
        # Brotli压缩
        # compressed_data = brotli.compress(woff2_data)

    def get_meta_data(self, font_family):
        """实测这里不做缓存会导致服务器响应时间1s+"""
        if font_family not in self.meta_cache.keys():
            meta_list = [json.loads(meta_file.read_text())\
                for meta_file in find_files_by_extension(METADATA_DIR / f"{font_family}/", ['json'])]
            self.meta_cache[font_family] = meta_list
        else:
            meta_list = self.meta_cache[font_family]
        return meta_list

if __name__ == "__main__":
    font_service = FontService()
    # font_service.create_subset("OpenSans")
    font_service.create_subset("Satisfy")
    font_service.create_subset("Noto Sans SC")
