"""
Batch Downloader
生成結果の一括ダウンロード機能
"""

import os
import requests
import zipfile
import io
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import Database


class BatchDownloader:
    """一括ダウンローダー"""

    def __init__(self, database: Database, output_dir: str = "./outputs"):
        self.db = database
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """進捗コールバックを設定"""
        self._progress_callback = callback

    def _notify_progress(self, message: str, progress: float = 0):
        if self._progress_callback:
            self._progress_callback({"message": message, "progress": progress})

    def download_single(self, url: str, save_path: Path,
                        timeout: int = 60) -> bool:
        """単一ファイルをダウンロード"""
        try:
            response = requests.get(url, timeout=timeout, stream=True)
            response.raise_for_status()

            save_path.parent.mkdir(parents=True, exist_ok=True)

            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except Exception as e:
            print(f"Download error: {e}")
            return False

    def download_batch_results(self, batch_job_id: int,
                                max_workers: int = 3) -> Dict:
        """バッチジョブの結果を一括ダウンロード"""
        tasks = self.db.get_downloadable_tasks(batch_job_id)

        if not tasks:
            return {"downloaded": 0, "failed": 0, "skipped": 0}

        # ジョブ専用フォルダを作成
        job = self.db.get_batch_job(batch_job_id)
        job_name = job["name"] if job else f"job_{batch_job_id}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = self.output_dir / f"{job_name}_{timestamp}"
        job_dir.mkdir(parents=True, exist_ok=True)

        results = {"downloaded": 0, "failed": 0, "skipped": 0, "paths": []}

        def download_task(task):
            task_id = task["id"]
            url = task["result_url"]

            if not url:
                return (task_id, "skipped", None)

            # ファイル名を生成
            ext = ".png"
            if "jpg" in url.lower() or "jpeg" in url.lower():
                ext = ".jpg"

            filename = f"task_{task_id:04d}{ext}"
            save_path = job_dir / filename

            if self.download_single(url, save_path):
                return (task_id, "success", str(save_path))
            else:
                return (task_id, "failed", None)

        # 並列ダウンロード
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_task, t): t for t in tasks}
            total = len(futures)

            for i, future in enumerate(as_completed(futures)):
                task_id, status, path = future.result()
                progress = ((i + 1) / total) * 100

                if status == "success":
                    results["downloaded"] += 1
                    results["paths"].append(path)
                    # DBを更新
                    self.db.update_task_status(task_id, "completed",
                                               local_path=path)
                elif status == "failed":
                    results["failed"] += 1
                else:
                    results["skipped"] += 1

                self._notify_progress(
                    f"Downloaded {i+1}/{total}",
                    progress=progress
                )

        return results

    def create_zip_archive(self, batch_job_id: int) -> Optional[bytes]:
        """ダウンロード済み画像をZIPアーカイブ化"""
        tasks = self.db.get_tasks_with_results(batch_job_id)

        if not tasks:
            return None

        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for task in tasks:
                local_path = task.get("local_path")
                if local_path and Path(local_path).exists():
                    arcname = Path(local_path).name
                    zf.write(local_path, arcname)
                elif task.get("result_url"):
                    # ローカルにない場合は直接ダウンロード
                    try:
                        response = requests.get(task["result_url"], timeout=60)
                        if response.status_code == 200:
                            filename = f"task_{task['id']:04d}.png"
                            zf.writestr(filename, response.content)
                    except:
                        pass

        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    def export_metadata_csv(self, batch_job_id: int) -> str:
        """タスクメタデータをCSV出力"""
        import csv
        import io

        tasks = self.db.get_tasks_by_batch(batch_job_id)

        output = io.StringIO()
        writer = csv.writer(output)

        # ヘッダー
        writer.writerow([
            "task_id", "status", "face_image", "outfit_image",
            "background_image", "prompt", "result_url", "local_path",
            "error", "created_at"
        ])

        for task in tasks:
            writer.writerow([
                task["id"],
                task["status"],
                task["face_image_path"],
                task["outfit_image_path"],
                task["background_image_path"],
                task["prompt"],
                task["result_url"],
                task["local_path"],
                task["error_message"],
                task["created_at"]
            ])

        return output.getvalue()

    def get_download_stats(self, batch_job_id: int) -> Dict:
        """ダウンロード統計を取得"""
        tasks = self.db.get_tasks_by_batch(batch_job_id)

        stats = {
            "total": len(tasks),
            "completed": 0,
            "with_url": 0,
            "downloaded": 0,
            "pending_download": 0
        }

        for task in tasks:
            if task["status"] == "completed":
                stats["completed"] += 1
            if task["result_url"]:
                stats["with_url"] += 1
            if task["local_path"]:
                stats["downloaded"] += 1

        stats["pending_download"] = stats["with_url"] - stats["downloaded"]

        return stats
