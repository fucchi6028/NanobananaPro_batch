"""
Kie.ai Nanobananapro API Client
kie.ai 非同期タスクモデル対応
"""

import base64
import json
import time
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass
from enum import Enum


class TaskStatus(Enum):
    """タスクステータス"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class GenerationResult:
    """生成結果"""
    success: bool
    task_id: Optional[str] = None
    status: TaskStatus = TaskStatus.UNKNOWN
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    error: Optional[str] = None
    raw_response: Optional[Dict] = None
    credits_used: Optional[float] = None


class KieAPI:
    """Kie.ai API Client"""

    BASE_URL = "https://api.kie.ai"
    FILE_UPLOAD_URL = "https://kieai.redpandaai.co"

    def __init__(self, api_key: str):
        """
        Args:
            api_key: kie.ai APIキー（ダッシュボードから取得）
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
        # ファイルアップロード用のURL キャッシュ
        self._upload_cache: Dict[str, str] = {}

    def _encode_image_to_base64(self, image_path: Union[str, Path]) -> str:
        """画像をBase64エンコード"""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _get_mime_type(self, image_path: Union[str, Path]) -> str:
        """画像のMIMEタイプを取得"""
        suffix = Path(image_path).suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif"
        }
        return mime_types.get(suffix, "image/png")

    def upload_file_base64(self, image_path: Union[str, Path]) -> Optional[str]:
        """
        ファイルをBase64形式でアップロードし、ダウンロードURLを取得

        Args:
            image_path: ローカル画像パス

        Returns:
            アップロードされたファイルのダウンロードURL（3日間有効）
        """
        path = Path(image_path)
        if not path.exists():
            print(f"[ERROR] File not found: {path}")
            return None

        # キャッシュチェック
        cache_key = str(path.absolute())
        if cache_key in self._upload_cache:
            print(f"[DEBUG] Using cached URL for: {path.name}")
            return self._upload_cache[cache_key]

        try:
            mime_type = self._get_mime_type(path)
            encoded = self._encode_image_to_base64(path)
            data_url = f"data:{mime_type};base64,{encoded}"

            payload = {
                "base64Data": data_url,
                "uploadPath": "nanobananapro/batch",
                "fileName": path.name
            }

            print(f"[DEBUG] Uploading file: {path.name} ({len(encoded)} bytes base64)")

            response = requests.post(
                f"{self.FILE_UPLOAD_URL}/api/file-base64-upload",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=120
            )

            print(f"[DEBUG] Upload response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json() if response.text else {}
                if data.get("success") and data.get("data"):
                    download_url = data["data"].get("downloadUrl")
                    if download_url:
                        print(f"[DEBUG] Upload successful: {download_url}")
                        # キャッシュに保存
                        self._upload_cache[cache_key] = download_url
                        return download_url

                error_msg = data.get("msg") or "Upload failed"
                print(f"[ERROR] Upload failed: {error_msg}")
                return None
            else:
                print(f"[ERROR] Upload HTTP error: {response.status_code}")
                print(f"[ERROR] Response: {response.text[:500] if response.text else 'empty'}")
                return None

        except Exception as e:
            print(f"[ERROR] Upload exception: {e}")
            return None

    def upload_file_stream(self, image_path: Union[str, Path]) -> Optional[str]:
        """
        ファイルをストリーム形式でアップロード（大きいファイル向け）

        Args:
            image_path: ローカル画像パス

        Returns:
            アップロードされたファイルのダウンロードURL（3日間有効）
        """
        path = Path(image_path)
        if not path.exists():
            print(f"[ERROR] File not found: {path}")
            return None

        # キャッシュチェック
        cache_key = str(path.absolute())
        if cache_key in self._upload_cache:
            print(f"[DEBUG] Using cached URL for: {path.name}")
            return self._upload_cache[cache_key]

        try:
            print(f"[DEBUG] Uploading file (stream): {path.name}")

            with open(path, "rb") as f:
                files = {"file": (path.name, f, self._get_mime_type(path))}
                data = {
                    "uploadPath": "nanobananapro/batch",
                    "fileName": path.name
                }

                response = requests.post(
                    f"{self.FILE_UPLOAD_URL}/api/file-stream-upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    data=data,
                    timeout=120
                )

            print(f"[DEBUG] Upload response status: {response.status_code}")

            if response.status_code == 200:
                resp_data = response.json() if response.text else {}
                if resp_data.get("success") and resp_data.get("data"):
                    download_url = resp_data["data"].get("downloadUrl")
                    if download_url:
                        print(f"[DEBUG] Upload successful: {download_url}")
                        self._upload_cache[cache_key] = download_url
                        return download_url

                error_msg = resp_data.get("msg") or "Upload failed"
                print(f"[ERROR] Upload failed: {error_msg}")
                return None
            else:
                print(f"[ERROR] Upload HTTP error: {response.status_code}")
                return None

        except Exception as e:
            print(f"[ERROR] Upload exception: {e}")
            return None

    def get_image_url(self, image_path: Union[str, Path]) -> Optional[str]:
        """
        画像のURLを取得（ローカルファイルの場合はアップロード）

        Args:
            image_path: 画像パスまたはURL

        Returns:
            画像URL
        """
        path_str = str(image_path)

        # 既にURLの場合はそのまま返す
        if path_str.startswith(("http://", "https://")):
            return path_str

        # ローカルファイルをアップロード
        path = Path(image_path)
        if path.exists():
            # ファイルサイズで方式を選択（10MB以上はストリーム）
            file_size = path.stat().st_size
            if file_size > 10 * 1024 * 1024:
                return self.upload_file_stream(path)
            else:
                return self.upload_file_base64(path)

        return None

    def check_balance(self) -> Dict[str, Any]:
        """
        クレジット残高を確認

        Note: kie.aiは残高確認APIを公開していないため、
        ダッシュボード（https://kie.ai/api-key）で確認が必要
        """
        # kie.aiは残高APIを提供していない
        return {
            "success": False,
            "error": "Balance API not available",
            "message": "Please check your balance at: https://kie.ai/api-key"
        }

    def create_task(
        self,
        prompt: str,
        reference_images: Optional[List[str]] = None,
        model: str = "nano-banana-pro",
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        callback_url: Optional[str] = None,
        additional_params: Optional[Dict] = None
    ) -> GenerationResult:
        """
        生成タスクを作成（非同期）

        Args:
            prompt: 生成プロンプト
            reference_images: 参照画像パスのリスト
            model: モデル名 (nano-banana, nano-banana-pro)
            aspect_ratio: アスペクト比 (1:1, 16:9, 9:16, 4:3, 3:4, etc.)
            resolution: 解像度 (1K, 2K, 4K)
            callback_url: 完了時のWebhook URL（オプション）
            additional_params: 追加パラメータ

        Returns:
            GenerationResult (task_idを含む)
        """
        try:
            # kie.ai API: パラメータはinputオブジェクト内にネスト
            input_params = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": "png"
            }

            # 参照画像を追加
            # ローカルファイルは先にアップロードしてURLを取得
            if reference_images:
                image_urls = []
                for img_path in reference_images:
                    if img_path:
                        # URLを取得（ローカルファイルの場合はアップロード）
                        url = self.get_image_url(img_path)
                        if url:
                            image_urls.append(url)
                            print(f"[DEBUG] Added image URL: {url[:80]}...")
                        else:
                            print(f"[WARNING] Failed to get URL for: {img_path}")

                if image_urls:
                    input_params["image_input"] = image_urls
                    print(f"[DEBUG] Total {len(image_urls)} images in image_input")

            # モデル名から google/ プレフィックスを除去
            model_name = model.replace("google/", "")

            payload = {
                "model": model_name,
                "input": input_params
            }

            # Webhook URL
            if callback_url:
                payload["callBackUrl"] = callback_url

            # 追加パラメータをマージ
            if additional_params:
                payload["input"].update(additional_params)

            print(f"[DEBUG] API Request: {self.BASE_URL}/api/v1/jobs/createTask")
            print(f"[DEBUG] Payload model: {payload.get('model')}")
            print(f"[DEBUG] Payload prompt: {payload.get('input', {}).get('prompt', '')[:50]}...")

            response = self.session.post(
                f"{self.BASE_URL}/api/v1/jobs/createTask",
                json=payload,
                timeout=60
            )

            print(f"[DEBUG] Response status: {response.status_code}")
            print(f"[DEBUG] Response body: {response.text[:500] if response.text else 'empty'}")

            if response.status_code == 200:
                data = response.json() if response.text else {}
                if data is None:
                    data = {}

                # kie.ai のエラーレスポンスをチェック (code != 0 or code >= 400)
                api_code = data.get("code")
                if api_code and api_code >= 400:
                    error_msg = data.get("msg") or f"API Error code {api_code}"
                    print(f"[DEBUG] API Error: {error_msg}")
                    return GenerationResult(
                        success=False,
                        error=error_msg,
                        raw_response=data
                    )

                # kie.ai のレスポンス形式に対応
                # APIは "data": {"taskId": "..."} の形式で返す（camelCase）
                task_id = (
                    data.get("task_id") or
                    data.get("taskId") or
                    data.get("id") or
                    (data.get("data") or {}).get("task_id") or
                    (data.get("data") or {}).get("taskId") or
                    (data.get("data") or {}).get("id")
                )
                print(f"[DEBUG] Extracted task_id: {task_id}")
                print(f"[DEBUG] Full response data: {data}")

                if not task_id:
                    return GenerationResult(
                        success=False,
                        error="No task_id returned from API",
                        raw_response=data
                    )

                return GenerationResult(
                    success=True,
                    task_id=task_id,
                    status=TaskStatus.PENDING,
                    raw_response=data
                )
            elif response.status_code == 429:
                error_data = None
                try:
                    error_data = response.json() if response.text else None
                except:
                    pass
                return GenerationResult(
                    success=False,
                    error="Rate limit exceeded (max 20 requests per 10 seconds)",
                    raw_response=error_data
                )
            else:
                error_data = {}
                try:
                    error_data = response.json() if response.text else {}
                    if error_data is None:
                        error_data = {}
                except:
                    error_data = {}
                error_msg = error_data.get("msg") or error_data.get("message") or f"HTTP {response.status_code}"
                return GenerationResult(
                    success=False,
                    error=error_msg,
                    raw_response=error_data
                )

        except requests.Timeout:
            return GenerationResult(
                success=False,
                error="Request timeout"
            )
        except requests.RequestException as e:
            return GenerationResult(
                success=False,
                error=str(e)
            )

    def query_task(self, task_id: str) -> GenerationResult:
        """
        タスクステータスを照会

        Args:
            task_id: タスクID

        Returns:
            GenerationResult（完了時はimage_urlを含む）
        """
        try:
            # kie.ai API: パラメータは taskId (camelCase)
            response = self.session.get(
                f"{self.BASE_URL}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                timeout=30
            )

            print(f"[DEBUG] Query task {task_id}: status={response.status_code}")

            if response.status_code == 200:
                data = response.json() if response.text else {}
                if data is None:
                    data = {}

                print(f"[DEBUG] Query response: {str(data)[:500]}")

                # kie.ai のレスポンス形式に対応
                # data.data 内に結果がある
                inner_data = data.get("data") or {}

                # ステータスを解析 - kie.ai の state フィールド
                # 値: waiting, success, fail
                state_str = (inner_data.get("state") or data.get("state") or "").lower()

                if state_str == "success":
                    status = TaskStatus.COMPLETED
                elif state_str == "fail":
                    status = TaskStatus.FAILED
                elif state_str in ["waiting", "processing", "running"]:
                    status = TaskStatus.PROCESSING
                else:
                    status = TaskStatus.UNKNOWN

                print(f"[DEBUG] Parsed state: {state_str} -> {status.value}")

                # 結果URLを取得
                image_url = None
                image_urls = None

                if status == TaskStatus.COMPLETED:
                    # kie.ai のレスポンス形式: resultJson フィールドに JSON 文字列
                    # JSON.parse(resultJson).resultUrls で URL 配列を取得
                    result_json_str = inner_data.get("resultJson") or data.get("resultJson")

                    if result_json_str:
                        try:
                            if isinstance(result_json_str, str):
                                result_json = json.loads(result_json_str)
                            else:
                                result_json = result_json_str

                            # resultUrls 配列から URL を取得
                            result_urls = result_json.get("resultUrls") or []
                            if result_urls and len(result_urls) > 0:
                                image_urls = result_urls
                                image_url = result_urls[0]

                            print(f"[DEBUG] Parsed resultJson: {len(result_urls)} URLs")
                        except (json.JSONDecodeError, TypeError) as e:
                            print(f"[DEBUG] Failed to parse resultJson: {e}")

                    # フォールバック: output フィールドも確認
                    if not image_url:
                        output = (
                            inner_data.get("output") or
                            inner_data.get("result") or
                            data.get("output")
                        )
                        if isinstance(output, list) and len(output) > 0:
                            image_urls = output
                            image_url = output[0]
                        elif isinstance(output, str) and output.startswith("http"):
                            image_url = output
                            image_urls = [output]

                    print(f"[DEBUG] Completed - image_url: {image_url}")

                # 失敗時のエラーメッセージ
                error_msg = None
                if status == TaskStatus.FAILED:
                    error_msg = inner_data.get("errorMsg") or inner_data.get("error") or data.get("msg") or "Task failed"
                    print(f"[DEBUG] Failed - error: {error_msg}")

                return GenerationResult(
                    success=True,
                    task_id=task_id,
                    status=status,
                    image_url=image_url,
                    image_urls=image_urls,
                    error=error_msg,
                    credits_used=inner_data.get("credits_used") or inner_data.get("cost") or data.get("cost"),
                    raw_response=data
                )

            else:
                error_data = None
                try:
                    error_data = response.json() if response.text else None
                except:
                    pass
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    error=f"HTTP {response.status_code}",
                    raw_response=error_data
                )

        except requests.RequestException as e:
            return GenerationResult(
                success=False,
                task_id=task_id,
                error=str(e)
            )

    def wait_for_completion(
        self,
        task_id: str,
        timeout: float = 300,
        poll_interval: float = 3.0,
        progress_callback: Optional[callable] = None
    ) -> GenerationResult:
        """
        タスク完了を待機（ポーリング）

        Args:
            task_id: タスクID
            timeout: タイムアウト秒数
            poll_interval: ポーリング間隔秒数
            progress_callback: 進捗コールバック (status, elapsed) -> None

        Returns:
            GenerationResult
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time

            if elapsed > timeout:
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    error=f"Timeout after {timeout}s"
                )

            result = self.query_task(task_id)

            if progress_callback:
                progress_callback(result.status, elapsed)

            if result.status == TaskStatus.COMPLETED:
                return result

            if result.status == TaskStatus.FAILED:
                # エラーメッセージは query_task で既に取得済み
                error_msg = result.error or "Task failed"
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=error_msg,
                    raw_response=result.raw_response
                )

            time.sleep(poll_interval)

    def generate_and_wait(
        self,
        prompt: str,
        reference_images: Optional[List[str]] = None,
        model: str = "google/nano-banana-pro",
        timeout: float = 300,
        poll_interval: float = 3.0,
        progress_callback: Optional[callable] = None,
        **kwargs
    ) -> GenerationResult:
        """
        画像を生成して完了を待機（同期的に使用可能）

        Args:
            prompt: 生成プロンプト
            reference_images: 参照画像パスのリスト
            model: モデル名
            timeout: タイムアウト秒数
            poll_interval: ポーリング間隔秒数
            progress_callback: 進捗コールバック
            **kwargs: create_taskへの追加パラメータ

        Returns:
            GenerationResult
        """
        # タスク作成
        create_result = self.create_task(
            prompt=prompt,
            reference_images=reference_images,
            model=model,
            **kwargs
        )

        if not create_result.success:
            return create_result

        # 完了を待機
        return self.wait_for_completion(
            task_id=create_result.task_id,
            timeout=timeout,
            poll_interval=poll_interval,
            progress_callback=progress_callback
        )

    def download_image(self, url: str, timeout: int = 60) -> Optional[bytes]:
        """画像URLからダウンロード"""
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            return None

    def check_multiple_tasks(self, task_ids: List[str]) -> Dict[str, GenerationResult]:
        """
        複数タスクのステータスを一括確認

        Args:
            task_ids: タスクIDのリスト

        Returns:
            {task_id: GenerationResult} の辞書
        """
        results = {}
        for task_id in task_ids:
            if task_id:
                results[task_id] = self.query_task(task_id)
        return results


# 後方互換性のためのエイリアス
NanobanaproAPI = KieAPI
