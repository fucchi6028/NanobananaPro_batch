"""
Batch Processor Engine
バッチ処理エンジン - キュー管理、重複排除、ランダム選択
kie.ai 非同期タスクモデル対応
"""

import hashlib
import random
import shutil
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from database import Database
from api_client import KieAPI, GenerationResult, TaskStatus


@dataclass
class ImageSource:
    """画像ソース（単一ファイルまたはフォルダ）"""
    path: str
    is_folder: bool = False
    files: List[str] = field(default_factory=list)

    def __post_init__(self):
        path = Path(self.path)
        if path.is_dir():
            self.is_folder = True
            self.files = self._scan_folder(path)
        elif path.is_file():
            self.is_folder = False
            self.files = [str(path)]
        else:
            self.files = []

    def _scan_folder(self, folder: Path) -> List[str]:
        """フォルダ内の画像ファイルをスキャン"""
        extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        files = []
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in extensions:
                files.append(str(f))
        return sorted(files)

    def get_random(self, exclude: set = None) -> Optional[str]:
        """ランダムに1枚選択（除外リスト対応）"""
        if not self.files:
            return None

        available = self.files
        if exclude:
            available = [f for f in self.files if f not in exclude]

        if not available:
            return None

        return random.choice(available)

    def get_all(self) -> List[str]:
        """全ファイルを取得"""
        return self.files.copy()


@dataclass
class PromptSource:
    """プロンプトソース（直接入力またはフォルダ内の.txtファイル）"""
    path: str = ""
    is_folder: bool = False
    files: List[str] = field(default_factory=list)
    _contents_cache: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.path:
            return

        path = Path(self.path)
        if path.is_dir():
            self.is_folder = True
            self.files = self._scan_folder(path)
        elif path.is_file() and path.suffix.lower() == ".txt":
            self.is_folder = False
            self.files = [str(path)]
        else:
            self.files = []

    def _scan_folder(self, folder: Path) -> List[str]:
        """フォルダ内の.txtファイルをスキャン"""
        files = []
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() == ".txt":
                files.append(str(f))
        return sorted(files)

    def _read_file(self, file_path: str) -> str:
        """ファイル内容を読み込み（キャッシュ付き）"""
        if file_path in self._contents_cache:
            return self._contents_cache[file_path]

        try:
            path = Path(file_path)
            content = path.read_text(encoding="utf-8").strip()
            self._contents_cache[file_path] = content
            return content
        except Exception as e:
            print(f"[ERROR] Failed to read prompt file: {file_path} - {e}")
            return ""

    def get_random(self, exclude: set = None) -> Optional[Tuple[str, str]]:
        """
        ランダムに1つ選択（除外リスト対応）

        Returns:
            (file_path, content) または None
        """
        if not self.files:
            return None

        available = self.files
        if exclude:
            available = [f for f in self.files if f not in exclude]

        if not available:
            return None

        selected = random.choice(available)
        content = self._read_file(selected)
        return (selected, content)

    def get_all(self) -> List[str]:
        """全ファイルパスを取得"""
        return self.files.copy()

    def get_content(self, file_path: str) -> str:
        """指定ファイルの内容を取得"""
        return self._read_file(file_path)


@dataclass
class BatchConfig:
    """バッチ処理設定"""
    name: str
    total_count: int
    prompt_template: str

    # 画像ソース
    face_source: Optional[ImageSource] = None
    outfit_source: Optional[ImageSource] = None
    background_source: Optional[ImageSource] = None

    # プロンプトソース（フォルダ指定時に使用）
    prompt_source: Optional[PromptSource] = None

    # API設定 (kie.ai モデル名)
    model: str = "google/nano-banana-pro"
    resolution: str = "2K"
    aspect_ratio: str = "1:1"

    # 処理設定
    allow_duplicate_combinations: bool = False
    request_delay: float = 2.0
    poll_interval: float = 3.0
    task_timeout: float = 300.0

    # エラー画像移動先フォルダ（file2のみ対象）
    error_folder: str = ""


class BatchProcessor:
    """バッチ処理エンジン"""

    def __init__(self, api_client: KieAPI, database: Database):
        self.api = api_client
        self.db = database
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._current_job_id: Optional[int] = None
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """進捗コールバックを設定"""
        self._progress_callback = callback

    def _notify_progress(self, message: str, progress: float = 0,
                         task_id: int = None, status: str = None,
                         error_message: str = None):
        """進捗を通知"""
        if self._progress_callback:
            self._progress_callback({
                "message": message,
                "progress": progress,
                "task_id": task_id,
                "status": status,
                "job_id": self._current_job_id,
                "error_message": error_message
            })

    def _is_content_policy_error(self, error_message: str) -> bool:
        """
        コンテンツポリシー違反エラーかどうかを判定

        Args:
            error_message: エラーメッセージ

        Returns:
            NSFWやコンテンツポリシー違反の場合True
        """
        if not error_message:
            return False

        error_lower = error_message.lower()

        # コンテンツポリシー関連のキーワード
        content_error_keywords = [
            "nsfw",
            "content policy",
            "content_policy",
            "policy violation",
            "inappropriate",
            "safety",
            "moderation",
            "banned",
            "prohibited",
            "explicit",
            "adult content",
            "violates",
            "not allowed",
            "restricted",
        ]

        return any(keyword in error_lower for keyword in content_error_keywords)

    def _move_error_image(self, image_path: str, error_folder: str) -> bool:
        """
        エラー画像を指定フォルダに移動

        Args:
            image_path: 移動する画像のパス
            error_folder: 移動先フォルダ

        Returns:
            成功した場合True
        """
        if not image_path or not error_folder:
            return False

        try:
            src_path = Path(image_path)
            if not src_path.exists():
                print(f"[WARNING] Image not found, cannot move: {image_path}")
                return False

            dest_folder = Path(error_folder)
            dest_folder.mkdir(parents=True, exist_ok=True)

            dest_path = dest_folder / src_path.name

            # 同名ファイルがある場合はリネーム
            if dest_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_path = dest_folder / f"{src_path.stem}_{timestamp}{src_path.suffix}"

            shutil.move(str(src_path), str(dest_path))
            print(f"[INFO] Moved error image: {src_path.name} -> {dest_path}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to move image {image_path}: {e}")
            return False

    def _generate_combination_hash(self, face: str, outfit: str,
                                    background: str, prompt_file: str = "") -> str:
        """組み合わせのハッシュを生成（プロンプトファイルも含む）"""
        combo = f"{face}|{outfit}|{background}|{prompt_file}"
        return hashlib.md5(combo.encode()).hexdigest()

    def _select_combination(self, config: BatchConfig,
                            batch_job_id: int,
                            used_prompts: set = None) -> Tuple[str, str, str, str, str]:
        """
        重複しない画像とプロンプトの組み合わせを選択

        Returns:
            (face_path, outfit_path, background_path, prompt_file_path, prompt_content)
            画像がない場合は空文字列
        """
        max_attempts = 100

        # 画像ソースの有無を確認
        has_any_image_source = any([
            config.face_source and config.face_source.files,
            config.outfit_source and config.outfit_source.files,
            config.background_source and config.background_source.files
        ])

        # プロンプトソースの有無を確認
        has_prompt_source = config.prompt_source and config.prompt_source.files

        for _ in range(max_attempts):
            face = ""
            outfit = ""
            background = ""
            prompt_file = ""
            prompt_content = ""

            # 各ソースから画像を選択
            if config.face_source and config.face_source.files:
                face = config.face_source.get_random() or ""

            if config.outfit_source and config.outfit_source.files:
                outfit = config.outfit_source.get_random() or ""

            if config.background_source and config.background_source.files:
                background = config.background_source.get_random() or ""

            # プロンプトソースからプロンプトを選択
            if has_prompt_source:
                result = config.prompt_source.get_random(exclude=used_prompts)
                if result:
                    prompt_file, prompt_content = result
                else:
                    # 全てのプロンプトを使い果たした場合、重複を許可して再取得
                    result = config.prompt_source.get_random()
                    if result:
                        prompt_file, prompt_content = result
            else:
                # 直接入力のプロンプトを使用
                prompt_content = config.prompt_template

            # 重複チェック
            if not config.allow_duplicate_combinations:
                combo_hash = self._generate_combination_hash(
                    face, outfit, background, prompt_file
                )
                if self.db.is_combination_used(batch_job_id, combo_hash):
                    continue

                # 使用済みとしてマーク
                self.db.mark_combination_used(
                    batch_job_id, combo_hash,
                    face, outfit, background
                )

            return (face, outfit, background, prompt_file, prompt_content)

        return ("", "", "", "", config.prompt_template)  # フォールバック

    # 後方互換性のため残す
    def _select_images(self, config: BatchConfig,
                       batch_job_id: int) -> Tuple[str, str, str]:
        """重複しない画像の組み合わせを選択（後方互換）"""
        face, outfit, background, _, _ = self._select_combination(config, batch_job_id)
        return (face, outfit, background)

    def _build_prompt(self, template: str, face: str,
                      outfit: str, background: str) -> str:
        """プロンプトを構築"""
        prompt = template

        # プレースホルダーの置換（必要に応じて）
        replacements = {
            "{face}": Path(face).stem if face else "",
            "{outfit}": Path(outfit).stem if outfit else "",
            "{background}": Path(background).stem if background else "",
        }

        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)

        return prompt

    def create_batch_job(self, config: BatchConfig) -> int:
        """バッチジョブを作成"""
        settings = {
            "model": config.model,
            "resolution": config.resolution,
            "aspect_ratio": config.aspect_ratio,
            "face_source": config.face_source.path if config.face_source else None,
            "outfit_source": config.outfit_source.path if config.outfit_source else None,
            "background_source": config.background_source.path if config.background_source else None,
            "allow_duplicate_combinations": config.allow_duplicate_combinations,
            "request_delay": config.request_delay,
            "poll_interval": config.poll_interval,
            "task_timeout": config.task_timeout
        }

        job_id = self.db.create_batch_job(
            name=config.name,
            total_count=config.total_count,
            prompt_template=config.prompt_template,
            settings=settings
        )

        return job_id

    def prepare_tasks(self, job_id: int, config: BatchConfig) -> int:
        """タスクを事前準備"""
        created_count = 0
        used_prompts = set()  # 使用済みプロンプトファイルを追跡

        for i in range(config.total_count):
            # 画像とプロンプトの組み合わせを選択
            result = self._select_combination(config, job_id, used_prompts)
            face, outfit, background, prompt_file, prompt_content = result

            # プロンプトファイルを使用済みとしてマーク
            if prompt_file:
                used_prompts.add(prompt_file)

            # プロンプトを構築（ファイル内容 + プレースホルダー置換）
            prompt = self._build_prompt(
                prompt_content, face, outfit, background
            )

            if not prompt:
                self._notify_progress(
                    f"Warning: Could not generate prompt for task {i+1}",
                    progress=(i / config.total_count) * 100
                )
                continue

            self.db.create_generation_task(
                batch_job_id=job_id,
                face_path=face or "",
                outfit_path=outfit or "",
                background_path=background or "",
                prompt=prompt
            )
            created_count += 1

        return created_count

    def run_batch(self, job_id: int, config: BatchConfig) -> Dict:
        """バッチ処理を実行（直列キュー）"""
        self._current_job_id = job_id
        self._stop_flag.clear()
        self.db.update_batch_job_status(job_id, "running")

        results = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "stopped": False
        }

        try:
            # 未処理タスクを取得
            tasks = self.db.get_pending_tasks(job_id)
            results["total"] = len(tasks)

            for i, task in enumerate(tasks):
                # 停止チェック
                if self._stop_flag.is_set():
                    results["stopped"] = True
                    break

                # 一時停止チェック
                while self._pause_flag.is_set():
                    time.sleep(0.5)
                    if self._stop_flag.is_set():
                        results["stopped"] = True
                        break

                if results["stopped"]:
                    break

                db_task_id = task["id"]
                progress = ((i + 1) / len(tasks)) * 100

                self._notify_progress(
                    f"Processing {i+1}/{len(tasks)}: Creating task...",
                    progress=progress,
                    task_id=db_task_id,
                    status="processing"
                )

                # タスクステータスを更新
                self.db.update_task_status(db_task_id, "processing")

                # 参照画像リストを構築
                reference_images = []
                if task["face_image_path"]:
                    reference_images.append(task["face_image_path"])
                if task["outfit_image_path"]:
                    reference_images.append(task["outfit_image_path"])
                if task["background_image_path"]:
                    reference_images.append(task["background_image_path"])

                # 進捗コールバック（ポーリング中）
                def on_poll_progress(status: TaskStatus, elapsed: float):
                    self._notify_progress(
                        f"Processing {i+1}/{len(tasks)}: {status.value} ({elapsed:.0f}s)",
                        progress=progress,
                        task_id=db_task_id,
                        status=status.value
                    )

                # kie.ai API呼び出し（非同期タスク作成 + ポーリング）
                result = self.api.generate_and_wait(
                    prompt=task["prompt"],
                    reference_images=reference_images if reference_images else None,
                    model=config.model,
                    resolution=config.resolution,
                    aspect_ratio=config.aspect_ratio,
                    timeout=config.task_timeout,
                    poll_interval=config.poll_interval,
                    progress_callback=on_poll_progress
                )

                if result.success and result.status == TaskStatus.COMPLETED:
                    # 成功
                    image_url = result.image_url
                    if not image_url and result.image_urls:
                        image_url = result.image_urls[0]

                    self.db.update_task_status(
                        db_task_id, "completed",
                        api_request_id=result.task_id,
                        result_url=image_url,
                        api_response=result.raw_response
                    )
                    self.db.increment_batch_job_count(job_id, completed=True)
                    results["completed"] += 1

                    self._notify_progress(
                        f"Completed {i+1}/{len(tasks)}",
                        progress=progress,
                        task_id=db_task_id,
                        status="completed"
                    )
                else:
                    # 失敗
                    error_msg = result.error or "Unknown error"
                    print(f"[DEBUG] Task {db_task_id} failed with error: {error_msg}")

                    self.db.update_task_status(
                        db_task_id, "failed",
                        api_request_id=result.task_id,
                        error_message=error_msg,
                        api_response=result.raw_response
                    )
                    self.db.increment_batch_job_count(job_id, completed=False)
                    results["failed"] += 1

                    # コンテンツポリシー違反の場合のみ、file2（outfit）の画像を移動
                    if config.error_folder and task["outfit_image_path"]:
                        if self._is_content_policy_error(error_msg):
                            if self._move_error_image(task["outfit_image_path"], config.error_folder):
                                results["moved_images"] = results.get("moved_images", 0) + 1
                                print(f"[INFO] Content policy error - moved image: {task['outfit_image_path']}")
                        else:
                            print(f"[DEBUG] Non-content error, image not moved: {error_msg}")

                    self._notify_progress(
                        f"Failed {i+1}/{len(tasks)}: {error_msg}",
                        progress=progress,
                        task_id=db_task_id,
                        status="failed",
                        error_message=error_msg
                    )

                # リクエスト間隔（レート制限対策）
                if i < len(tasks) - 1:
                    time.sleep(config.request_delay)

            # 最終ステータス更新
            final_status = "stopped" if results["stopped"] else "completed"
            self.db.update_batch_job_status(job_id, final_status)

            self._notify_progress(
                f"Batch {final_status}: {results['completed']}/{results['total']} successful",
                progress=100,
                status=final_status
            )

        except Exception as e:
            self.db.update_batch_job_status(job_id, "error")
            self._notify_progress(f"Error: {str(e)}", status="error")
            raise

        finally:
            self._current_job_id = None

        return results

    def stop(self):
        """処理を停止"""
        self._stop_flag.set()

    def pause(self):
        """処理を一時停止"""
        self._pause_flag.set()

    def resume(self):
        """処理を再開"""
        self._pause_flag.clear()

    def get_max_combinations(self, config: BatchConfig) -> int:
        """可能な最大組み合わせ数を計算"""
        face_count = len(config.face_source.files) if config.face_source else 1
        outfit_count = len(config.outfit_source.files) if config.outfit_source else 1
        bg_count = len(config.background_source.files) if config.background_source else 1
        prompt_count = len(config.prompt_source.files) if config.prompt_source else 1

        return face_count * outfit_count * bg_count * prompt_count

    def get_prompt_count(self, config: BatchConfig) -> int:
        """プロンプトファイル数を取得"""
        if config.prompt_source and config.prompt_source.files:
            return len(config.prompt_source.files)
        return 0
