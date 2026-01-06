"""
SQLite Database Manager for Nanobananapro Batch Processing
生成ジョブ、ログ、結果を管理
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


class Database:
    def __init__(self, db_path: str = "batch_jobs.db"):
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # バッチジョブテーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    total_count INTEGER DEFAULT 0,
                    completed_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    prompt_template TEXT,
                    settings JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 生成タスクテーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS generation_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_job_id INTEGER NOT NULL,
                    api_request_id TEXT,
                    status TEXT DEFAULT 'pending',
                    face_image_path TEXT,
                    outfit_image_path TEXT,
                    background_image_path TEXT,
                    prompt TEXT,
                    result_url TEXT,
                    local_path TEXT,
                    error_message TEXT,
                    api_response JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (batch_job_id) REFERENCES batch_jobs(id)
                )
            """)

            # 使用済み組み合わせテーブル（重複防止用）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS used_combinations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_job_id INTEGER NOT NULL,
                    combination_hash TEXT NOT NULL,
                    face_image TEXT,
                    outfit_image TEXT,
                    background_image TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (batch_job_id) REFERENCES batch_jobs(id),
                    UNIQUE(batch_job_id, combination_hash)
                )
            """)

            # クレジット履歴テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credit_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    balance REAL,
                    used REAL,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    # === Batch Job Operations ===

    def create_batch_job(self, name: str, total_count: int,
                         prompt_template: str, settings: Dict) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO batch_jobs (name, total_count, prompt_template, settings)
                VALUES (?, ?, ?, ?)
            """, (name, total_count, prompt_template, json.dumps(settings)))
            conn.commit()
            return cursor.lastrowid

    def update_batch_job_status(self, job_id: int, status: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE batch_jobs
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status, job_id))
            conn.commit()

    def increment_batch_job_count(self, job_id: int,
                                   completed: bool = True):
        field = "completed_count" if completed else "failed_count"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE batch_jobs
                SET {field} = {field} + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (job_id,))
            conn.commit()

    def get_batch_job(self, job_id: int) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_all_batch_jobs(self, limit: int = 100) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM batch_jobs
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # === Generation Task Operations ===

    def create_generation_task(self, batch_job_id: int,
                                face_path: str, outfit_path: str,
                                background_path: str, prompt: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO generation_tasks
                (batch_job_id, face_image_path, outfit_image_path,
                 background_image_path, prompt)
                VALUES (?, ?, ?, ?, ?)
            """, (batch_job_id, face_path, outfit_path, background_path, prompt))
            conn.commit()
            return cursor.lastrowid

    def update_task_status(self, task_id: int, status: str,
                           api_request_id: str = None,
                           result_url: str = None,
                           local_path: str = None,
                           error_message: str = None,
                           api_response: Dict = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]

            if api_request_id:
                updates.append("api_request_id = ?")
                params.append(api_request_id)
            if result_url:
                updates.append("result_url = ?")
                params.append(result_url)
            if local_path:
                updates.append("local_path = ?")
                params.append(local_path)
            if error_message:
                updates.append("error_message = ?")
                params.append(error_message)
            if api_response:
                updates.append("api_response = ?")
                params.append(json.dumps(api_response))

            params.append(task_id)
            cursor.execute(f"""
                UPDATE generation_tasks
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()

    def get_pending_tasks(self, batch_job_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ? AND status = 'pending'
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_tasks_by_batch(self, batch_job_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ?
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_task(self, task_id: int) -> Optional[Dict]:
        """単一タスクを取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE id = ?
            """, (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_tasks_with_results(self, batch_job_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ? AND status = 'completed'
                AND result_url IS NOT NULL
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_downloadable_tasks(self, batch_job_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ? AND status = 'completed'
                AND result_url IS NOT NULL AND local_path IS NULL
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    # === Combination Tracking ===

    def is_combination_used(self, batch_job_id: int,
                            combination_hash: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM used_combinations
                WHERE batch_job_id = ? AND combination_hash = ?
            """, (batch_job_id, combination_hash))
            return cursor.fetchone() is not None

    def mark_combination_used(self, batch_job_id: int,
                               combination_hash: str,
                               face: str, outfit: str, background: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO used_combinations
                    (batch_job_id, combination_hash, face_image,
                     outfit_image, background_image)
                    VALUES (?, ?, ?, ?, ?)
                """, (batch_job_id, combination_hash, face, outfit, background))
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # Already exists

    def get_used_combination_count(self, batch_job_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM used_combinations
                WHERE batch_job_id = ?
            """, (batch_job_id,))
            return cursor.fetchone()[0]

    # === Credit History ===

    def log_credit_check(self, balance: float, used: float = 0):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO credit_history (balance, used)
                VALUES (?, ?)
            """, (balance, used))
            conn.commit()

    def get_latest_credit(self) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM credit_history
                ORDER BY checked_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_processing_tasks(self, batch_job_id: int) -> List[Dict]:
        """ステータス確認が必要なタスク（processing状態でapi_request_idあり）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ?
                AND status IN ('processing', 'pending')
                AND api_request_id IS NOT NULL
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_incomplete_tasks(self, batch_job_id: int) -> List[Dict]:
        """未完了のタスク（completed/failed以外）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM generation_tasks
                WHERE batch_job_id = ?
                AND status NOT IN ('completed', 'failed')
                ORDER BY id
            """, (batch_job_id,))
            return [dict(row) for row in cursor.fetchall()]

    # === Statistics ===

    def get_batch_statistics(self, batch_job_id: int) -> Dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing
                FROM generation_tasks
                WHERE batch_job_id = ?
            """, (batch_job_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}
