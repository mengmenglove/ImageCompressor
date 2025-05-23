import os
import argparse
import subprocess
import logging
import json
import shutil
import tempfile
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Tuple, Optional
#
#   brew install mozjpeg optipng pngquant zopfli webp gifsicle
#   pip3 install tqdm
#   python3 -m pip install tqdm
#
# ###


# 配置常量
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff']
DEFAULT_BACKUP_DIR = '.image_backup'
DEFAULT_LOG_FILE = 'compression.log'

class ImageCompressor:
    def __init__(self, backup_enabled=True, backup_dir=DEFAULT_BACKUP_DIR, force_no_backup_check=False):
        self.backup_enabled = backup_enabled
        self.backup_dir = backup_dir
        self.force_no_backup_check = force_no_backup_check
        self.stats = {
            'total_files': 0,
            'processed': 0,
            'compressed': 0,
            'failed': 0,
            'original_size': 0,
            'compressed_size': 0,
            'space_saved': 0
        }
        self.setup_logging()
        self.check_dependencies()
    
    def setup_logging(self):
        """设置日志记录"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(DEFAULT_LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def check_dependencies(self):
        """检查外部工具依赖"""
        self.available_tools = {
            'mozjpeg': shutil.which('cjpeg') is not None,
            'optipng': shutil.which('optipng') is not None,
            'pngquant': shutil.which('pngquant') is not None,
            'zopflipng': shutil.which('zopflipng') is not None,
            'cwebp': shutil.which('cwebp') is not None,
            'gifsicle': shutil.which('gifsicle') is not None
        }
        
        missing_tools = [tool for tool, available in self.available_tools.items() if not available]
        if missing_tools:
            self.logger.warning(f"缺少以下工具，部分功能可能受限: {', '.join(missing_tools)}")
            self.logger.info("安装建议 (macOS): brew install mozjpeg optipng pngquant zopfli webp gifsicle")
    
    def create_backup(self, file_path: str) -> bool:
        """创建文件备份"""
        # 如果强制禁用备份检查，直接返回成功
        if self.force_no_backup_check:
            return True
            
        if not self.backup_enabled:
            return True
        
        try:
            backup_path = Path(self.backup_dir)
            backup_path.mkdir(exist_ok=True)
            
            # 保持原始目录结构
            rel_path = Path(file_path).relative_to(Path.cwd())
            backup_file = backup_path / rel_path
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(file_path, backup_file)
            return True
        except Exception as e:
            self.logger.error(f"备份失败 {file_path}: {e}")
            return False
    
    def compress_jpeg(self, temp_path: str, quality: int) -> bool:
        """压缩JPEG文件"""
        try:
            if self.available_tools['mozjpeg']:
                # 使用mozjpeg压缩
                result = subprocess.run([
                    'cjpeg', '-quality', str(quality), '-optimize', 
                    '-progressive', '-outfile', f'{temp_path}.tmp', temp_path
                ], capture_output=True, text=True, check=True)
                
                if os.path.exists(f'{temp_path}.tmp'):
                    os.replace(f'{temp_path}.tmp', temp_path)
                    return True
            else:
                self.logger.warning("mozjpeg不可用，跳过JPEG优化")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"JPEG压缩失败: {e.stderr}")
            return False
        except Exception as e:
            self.logger.error(f"JPEG压缩异常: {e}")
            return False
    
    def compress_png(self, temp_path: str) -> bool:
        """压缩PNG文件"""
        compressed = False
        
        try:
            # 使用pngquant进行有损压缩（可选）
            if self.available_tools['pngquant']:
                result = subprocess.run([
                    'pngquant', '--quality=65-80', '--output', f'{temp_path}.tmp', temp_path
                ], capture_output=True, text=True)
                
                if result.returncode == 0 and os.path.exists(f'{temp_path}.tmp'):
                    os.replace(f'{temp_path}.tmp', temp_path)
                    compressed = True
            
            # 使用optipng进行无损优化
            if self.available_tools['optipng']:
                subprocess.run([
                    'optipng', '-o2', '-quiet', temp_path
                ], capture_output=True, check=True)
                compressed = True
            
            # 使用zopflipng进一步优化
            elif self.available_tools['zopflipng']:
                subprocess.run([
                    'zopflipng', '-y', temp_path, temp_path
                ], capture_output=True, check=True)
                compressed = True
            
            return compressed
        except subprocess.CalledProcessError as e:
            self.logger.error(f"PNG压缩失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"PNG压缩异常: {e}")
            return False
    
    def compress_gif(self, temp_path: str) -> bool:
        """压缩GIF文件"""
        try:
            if self.available_tools['gifsicle']:
                subprocess.run([
                    'gifsicle', '-O3', '--batch', temp_path
                ], capture_output=True, check=True)
                return True
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"GIF压缩失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"GIF压缩异常: {e}")
            return False
    
    def compress_image(self, input_path: str, quality: int = 85) -> bool:
        """压缩单个图片文件"""
        try:
            file_ext = Path(input_path).suffix.lower()
            original_size = os.path.getsize(input_path)
            
            # 创建备份
            if not self.create_backup(input_path):
                self.logger.error(f"无法创建备份，跳过文件: {input_path}")
                return False
            
            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as temp_file:
                temp_path = temp_file.name
            
            try:
                # 复制到临时文件
                shutil.copy2(input_path, temp_path)
                
                # 根据文件类型选择压缩方法
                compressed = False
                if file_ext in ['.jpg', '.jpeg']:
                    compressed = self.compress_jpeg(temp_path, quality)
                elif file_ext == '.png':
                    compressed = self.compress_png(temp_path)
                elif file_ext == '.gif':
                    compressed = self.compress_gif(temp_path)
                else:
                    self.logger.info(f"不支持的格式，跳过: {input_path}")
                    return False
                
                if not compressed:
                    self.logger.warning(f"压缩工具不可用，跳过: {input_path}")
                    return False
                
                # 检查压缩效果
                compressed_size = os.path.getsize(temp_path)
                if compressed_size < original_size:
                    # 压缩有效，替换原文件
                    shutil.copy2(temp_path, input_path)
                    
                    # 更新统计信息
                    self.stats['compressed'] += 1
                    self.stats['original_size'] += original_size
                    self.stats['compressed_size'] += compressed_size
                    self.stats['space_saved'] += (original_size - compressed_size)
                    
                    reduction = 100 * (1 - compressed_size / original_size)
                    self.logger.info(f"✓ 压缩成功: {input_path} ({self._format_size(original_size)} → {self._format_size(compressed_size)}, 减少 {reduction:.1f}%)")
                    return True
                else:
                    self.logger.info(f"○ 跳过: {input_path} (压缩后更大)")
                    return False
                    
            finally:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except FileNotFoundError:
            self.logger.error(f"文件不存在: {input_path}")
            self.stats['failed'] += 1
            return False
        except PermissionError:
            self.logger.error(f"权限不足: {input_path}")
            self.stats['failed'] += 1
            return False
        except Exception as e:
            self.logger.error(f"处理失败: {input_path} - {e}")
            self.stats['failed'] += 1
            return False
        finally:
            self.stats['processed'] += 1
    
    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"
    
    def find_image_files(self, directory: str, recursive: bool = True) -> List[str]:
        """查找图片文件"""
        image_files = []
        directory_path = Path(directory)
        
        if recursive:
            pattern = '**/*'
        else:
            pattern = '*'
        
        for file_path in directory_path.glob(pattern):
            if (file_path.is_file() and 
                file_path.suffix.lower() in IMAGE_EXTENSIONS and
                not str(file_path).startswith(self.backup_dir)):
                image_files.append(str(file_path))
        
        return sorted(image_files)
    
    def process_files(self, files: List[str], quality: int = 85, max_workers: int = 4) -> None:
        """并行处理文件列表"""
        self.stats['total_files'] = len(files)
        
        if max_workers == 1:
            # 单线程处理
            for file_path in tqdm(files, desc="压缩进度"):
                self.compress_image(file_path, quality)
        else:
            # 多线程处理
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_file = {
                    executor.submit(self.compress_image, file_path, quality): file_path 
                    for file_path in files
                }
                
                # 显示进度
                with tqdm(total=len(files), desc="压缩进度") as pbar:
                    for future in as_completed(future_to_file):
                        pbar.update(1)
    
    def print_summary(self):
        """打印处理摘要"""
        print("\n" + "="*50)
        print("压缩完成摘要")
        print("="*50)
        print(f"总文件数: {self.stats['total_files']}")
        print(f"已处理: {self.stats['processed']}")
        print(f"成功压缩: {self.stats['compressed']}")
        print(f"失败: {self.stats['failed']}")
        
        if self.stats['compressed'] > 0:
            print(f"原始总大小: {self._format_size(self.stats['original_size'])}")
            print(f"压缩后大小: {self._format_size(self.stats['compressed_size'])}")
            print(f"节省空间: {self._format_size(self.stats['space_saved'])}")
            
            total_reduction = 100 * (self.stats['space_saved'] / self.stats['original_size'])
            print(f"总体压缩率: {total_reduction:.1f}%")
        
        print("="*50)
        
        # 保存统计信息到文件
        stats_file = f"compression_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump({
                **self.stats,
                'timestamp': datetime.now().isoformat(),
                'available_tools': self.available_tools
            }, f, indent=2, ensure_ascii=False)
        print(f"详细统计已保存到: {stats_file}")

# 在main函数中添加新参数
def main():
    parser = argparse.ArgumentParser(
        description='高级图片批量压缩工具 - 支持多种格式和并行处理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  %(prog)s /path/to/images --recursive --quality 80
  %(prog)s /path/to/images --no-backup --workers 8
  %(prog)s /path/to/images --formats jpg png --quality 90
  %(prog)s /path/to/images --force-no-backup-check  # 完全跳过备份检查
        """
    )
    
    parser.add_argument('directory', help='要处理的目录路径')
    parser.add_argument('--quality', type=int, default=85, 
                       help='JPEG压缩质量 (1-100), 默认85')
    parser.add_argument('--recursive', action='store_true', 
                       help='递归处理子目录')
    parser.add_argument('--no-backup', action='store_true', 
                       help='不创建备份文件')
    parser.add_argument('--backup-dir', default=DEFAULT_BACKUP_DIR,
                       help=f'备份目录路径，默认: {DEFAULT_BACKUP_DIR}')
    parser.add_argument('--workers', type=int, default=4,
                       help='并行处理线程数，默认4')
    parser.add_argument('--formats', nargs='+', 
                       choices=['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff'],
                       help='指定要处理的图片格式')
    parser.add_argument('--dry-run', action='store_true',
                       help='预览模式，只显示将要处理的文件')
    parser.add_argument('--force-no-backup-check', action='store_true',
                       help='完全跳过备份检查，适用于处理不在当前目录的文件')
    
    args = parser.parse_args()
    
    # 验证参数
    if not os.path.isdir(args.directory):
        print(f"错误: 目录不存在 - {args.directory}")
        return 1
    
    if not 1 <= args.quality <= 100:
        print("错误: 质量参数必须在1-100之间")
        return 1
    
    if args.workers < 1:
        print("错误: 线程数必须大于0")
        return 1
    
    # 创建压缩器
    compressor = ImageCompressor(
        backup_enabled=not args.no_backup,
        backup_dir=args.backup_dir,
        force_no_backup_check=args.force_no_backup_check
    )
    
    # 查找图片文件
    print(f"正在扫描目录: {args.directory}")
    image_files = compressor.find_image_files(args.directory, args.recursive)
    
    # 过滤文件格式
    if args.formats:
        format_extensions = [f'.{fmt}' for fmt in args.formats]
        image_files = [
            f for f in image_files 
            if Path(f).suffix.lower() in format_extensions
        ]
    
    if not image_files:
        print("未找到符合条件的图片文件")
        return 0
    
    print(f"找到 {len(image_files)} 个图片文件")
    
    # 预览模式
    if args.dry_run:
        print("\n预览模式 - 将要处理的文件:")
        for i, file_path in enumerate(image_files[:10], 1):
            size = compressor._format_size(os.path.getsize(file_path))
            print(f"{i:3d}. {file_path} ({size})")
        
        if len(image_files) > 10:
            print(f"... 还有 {len(image_files) - 10} 个文件")
        
        print(f"\n总计: {len(image_files)} 个文件")
        return 0
    
    # 开始处理
    print(f"开始压缩，使用 {args.workers} 个线程...")
    compressor.process_files(image_files, args.quality, args.workers)
    
    # 显示摘要
    compressor.print_summary()
    
    return 0

if __name__ == "__main__":
    exit(main())



# Basic usage with recursive directory scanning
#python image_batch_compressor.py /path/to/images --recursive

# Specify JPEG quality (1-100)
#python image_batch_compressor.py /path/to/images --recursive --quality 80

# Process without creating backups
#python image_batch_compressor.py /path/to/images --no-backup

# Use more worker threads for faster processing
#python image_batch_compressor.py /path/to/images --workers 8

# Only process specific image formats
#python image_batch_compressor.py /path/to/images --formats jpg png

# Preview mode (doesn't actually compress files)
#python image_batch_compressor.py /path/to/images --dry-run