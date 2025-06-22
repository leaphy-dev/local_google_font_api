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

    def get_font_supported_chars(self, font_path):
        """获取字体实际支持的字符集"""
        font = TTFont(font_path)
        return set(font.getBestCmap().keys())

    def get_intersection_subset(self, font_path, requested_set):
        """计算请求字符集与字体支持字符集的交集"""
        supported_set = self.get_font_supported_chars(font_path)
        return requested_set & supported_set

    def create_subset(self, font_file_name, force_rebuild: bool = False):
        """创建字体子集（跳过已存在元数据）"""
        print(f"Start handling font: {font_file_name})")
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
            meta_data_file_path = meta_data_file_dir / (woff2_file_name + ".json")

            # 检查文件是否存在且不需要重建
            if meta_data_file_path.exists() and not force_rebuild:
                skipped_count += 1
            else:
                tasks.append({
                    "subset": subset,
                    "subset_name": subset_name,
                    "woff2_file_name": woff2_file_name,
                    "_font_path": _font_path
                })

        print(f"Total tasks: {len(tasks)}, Skipped: {skipped_count}")

        # 获取CPU核心数
        num_cores = int(multiprocessing.cpu_count() / 4 )

        if tasks:
            print(f"Processing {len(tasks)} subsets using {num_cores} cores...")

            # 使用进程池执行任务
            with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
                futures = {}
                for task in tasks:
                    future = executor.submit(self._process_single_subset, task)
                    futures[future] = task["subset_name"]

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
            # 计算实际覆盖率
                requested_set = self.parse_unicode_range(subset)
                if requested_set:
                    supported_set = self.get_font_supported_chars(_font_path)
                    actual_set = requested_set & supported_set
                    coverage = len(actual_set) / len(requested_set)
                else:
                    actual_set = 0.0
                    coverage = 0.0

                meta_data = {
                    "font_family": font_family,
                    "subset_range": subset,
                    "woff2_file_name": (woff2_file_name + ".woff2"),
                    "subset": subset_name,
                    "coverage": coverage,
                    "supported_chars": len(actual_set)
                }
                meta_data_file_path.write_text(json.dumps(meta_data, indent=2))

    def _process_single_subset(self, task):
        """处理单个字体子集 - 使用实际支持的字符交集"""
        subset = task["subset"]
        subset_name = task["subset_name"]
        woff2_file_name = task["woff2_file_name"]
        _font_path = task["_font_path"]

        cached_font_file = CACHE_DIR / (woff2_file_name + ".woff2")

        # 解析请求的Unicode范围
        requested_set = self.parse_unicode_range(subset)
        if not requested_set:
            print(f"跳过空子集 {subset_name}")
            return f"跳过空子集 {subset_name}"

        supported_set = self.get_font_supported_chars(_font_path)
        actual_set = requested_set & supported_set

        coverage = len(actual_set) / len(requested_set) if requested_set else 0
        missing_chars = requested_set - supported_set

        if not actual_set:
            return f"跳过无支持字符的子集 {subset_name}，覆盖率: {coverage:.1%}"

        # 记录字符覆盖情况
        print(f"子集 {subset_name}: 请求字符 {len(requested_set)}，支持 {len(actual_set)}，覆盖率: {coverage:.1%}")
        if missing_chars:
            missing_hex = [f"U+{hex(c)[2:].upper()}" for c in sorted(missing_chars)]
            print(f"缺失字符: {', '.join(missing_hex[:10])}{'...' if len(missing_hex) > 10 else ''}")

        # 生成子集字体
        options = Options()
        options.flavor = "woff2"
        options.with_zopfli = True
        options.drop_tables = ['FFTM', 'VDMX', 'hdmx']  # 安全删除的表

        try:
            font = TTFont(file=_font_path, ignoreDecompileErrors=True, recalcBBoxes=False)

            # 创建subsetter并设置选项
            subsetter = Subsetter(options=options)
            subsetter.populate(unicodes=actual_set)

            try:
                subsetter.subset(font)
            except Exception as e:
                print(f"子集化警告: {str(e)} - 尝试简化处理")
                # 尝试更简单的子集化方法
                options.drop_tables = []
                subsetter = Subsetter(options=options)
                subsetter.populate(unicodes=actual_set)
                subsetter.subset(font)

            # 保存生成的字体
            os.makedirs(os.path.dirname(cached_font_file), exist_ok=True)
            font.save(cached_font_file)

            return f"生成子集 {subset_name} ({len(actual_set)}字符, 覆盖率: {coverage:.1%})"

        except Exception as e:
            error_msg = f"处理子集 {subset_name} 失败: {str(e)}"
            print(error_msg)
            return error_msg


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
    font_service.create_subset("Satisfy.ttf")
    font_service.create_subset("Fira Code.ttf")
    # font_service.create_subset("Noto Sans SC.ttf")
