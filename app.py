"""
Nanobananapro Batch Generator - Gradio GUI
メインアプリケーション（日本語版・ダークテーマ）
"""

import os
import json
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

import gradio as gr

from database import Database
from api_client import KieAPI, TaskStatus
from batch_processor import BatchProcessor, BatchConfig, ImageSource, PromptSource
from downloader import BatchDownloader


# グローバル変数
CONFIG_FILE = "config.json"
BATCH_SETTINGS_KEY = "batch_settings"
db: Optional[Database] = None
api: Optional[KieAPI] = None
processor: Optional[BatchProcessor] = None
downloader: Optional[BatchDownloader] = None
current_thread: Optional[threading.Thread] = None


# カスタムCSS
CUSTOM_CSS = """
/* メインコンテナ */
.gradio-container {
    max-width: 1400px !important;
    margin: auto !important;
}

/* ヘッダー */
.header-title {
    text-align: center;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-size: 2.5rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.5rem !important;
}

.header-subtitle {
    text-align: center;
    color: #888 !important;
    font-size: 1rem !important;
    margin-bottom: 1.5rem !important;
}

/* カード風セクション */
.section-card {
    background: rgba(30, 30, 40, 0.6) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 12px !important;
    padding: 1.5rem !important;
    margin-bottom: 1rem !important;
}

/* ボタンスタイル */
.primary-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    font-weight: 600 !important;
}

.primary-btn:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px) !important;
}

.stop-btn {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
}

/* 入力フィールド */
.dark-input textarea, .dark-input input {
    background: rgba(20, 20, 30, 0.8) !important;
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    border-radius: 8px !important;
}

.dark-input textarea:focus, .dark-input input:focus {
    border-color: #667eea !important;
    box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2) !important;
}

/* テーブル */
.job-table {
    border-radius: 8px !important;
    overflow: hidden !important;
}

/* タブ */
.tabs {
    border-radius: 12px !important;
}

/* ステータスバッジ */
.status-badge {
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 500;
}

/* プログレス表示 */
.progress-box {
    font-family: 'Consolas', 'Monaco', monospace !important;
    background: rgba(10, 10, 20, 0.9) !important;
    border: 1px solid rgba(102, 126, 234, 0.3) !important;
    border-radius: 8px !important;
}

/* アコーディオン */
.accordion {
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    margin-bottom: 0.5rem !important;
}

/* リンク */
a {
    color: #667eea !important;
}

a:hover {
    color: #764ba2 !important;
}
"""


def load_config() -> dict:
    """設定ファイルを読み込み"""
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """設定ファイルを保存"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_batch_settings() -> dict:
    """バッチ生成設定を取得"""
    config = load_config()
    return config.get(BATCH_SETTINGS_KEY, {})


def save_batch_settings(settings: dict):
    """バッチ生成設定を保存"""
    config = load_config()
    config[BATCH_SETTINGS_KEY] = settings
    save_config(config)


def move_error_image(image_path: str, error_folder: str) -> bool:
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
        print(f"[ERROR] Failed to move image: {e}")
        return False


def initialize_api(api_key: str) -> str:
    """APIを初期化"""
    global api, processor, downloader, db

    if not api_key:
        return "エラー: APIキーを入力してください"

    try:
        config = load_config()

        db = Database("batch_jobs.db")
        api = KieAPI(api_key)
        processor = BatchProcessor(api, db)
        downloader = BatchDownloader(db, config.get("output_directory", "./outputs"))

        config["api_key"] = api_key
        save_config(config)

        return "✓ API初期化完了 (kie.ai)"

    except Exception as e:
        return f"エラー: {str(e)}"


def scan_source(path: str) -> Tuple[str, int]:
    """画像ソースをスキャン"""
    if not path:
        return "未指定", 0

    p = Path(path)
    if not p.exists():
        return "パスが存在しません", 0

    source = ImageSource(path)

    if source.is_folder:
        return f"📁 フォルダ: {len(source.files)}枚", len(source.files)
    else:
        return f"📄 ファイル: {p.name}", 1


def scan_prompt_source(path: str) -> Tuple[str, int]:
    """プロンプトソースをスキャン"""
    if not path:
        return "未指定（直接入力を使用）", 0

    p = Path(path)
    if not p.exists():
        return "パスが存在しません", 0

    source = PromptSource(path)

    if source.is_folder:
        return f"📁 フォルダ: {len(source.files)}個の.txtファイル", len(source.files)
    elif source.files:
        return f"📄 ファイル: {p.name}", 1
    else:
        return ".txtファイルが見つかりません", 0


def calculate_max_combinations(face_path: str, outfit_path: str,
                                bg_path: str, prompt_folder: str = "") -> str:
    """最大組み合わせ数を計算"""
    face_count = 1
    outfit_count = 1
    bg_count = 1
    prompt_count = 1

    if face_path:
        _, count = scan_source(face_path)
        face_count = max(1, count)

    if outfit_path:
        _, count = scan_source(outfit_path)
        outfit_count = max(1, count)

    if bg_path:
        _, count = scan_source(bg_path)
        bg_count = max(1, count)

    if prompt_folder:
        _, count = scan_prompt_source(prompt_folder)
        prompt_count = max(1, count)

    total = face_count * outfit_count * bg_count * prompt_count

    if prompt_count > 1:
        return f"最大組み合わせ: {total}通り（顔:{face_count} × 服装:{outfit_count} × 背景:{bg_count} × プロンプト:{prompt_count}）"
    else:
        return f"最大組み合わせ: {total}通り（顔:{face_count} × 服装:{outfit_count} × 背景:{bg_count}）"


def start_batch_generation(
    job_name: str,
    prompt_template: str,
    prompt_folder: str,
    face_path: str,
    outfit_path: str,
    bg_path: str,
    total_count: int,
    model: str,
    resolution: str,
    aspect_ratio: str,
    allow_duplicates: bool,
    request_delay: float,
    error_folder: str,
    progress=gr.Progress()
):
    """バッチ生成を開始"""
    global current_thread

    if not api or not processor:
        yield "エラー: 先にAPIキーを設定してください"
        return

    # プロンプトのチェック（直接入力またはフォルダのどちらかが必要）
    if not prompt_template and not prompt_folder:
        yield "エラー: プロンプトを入力するか、プロンプトフォルダを指定してください"
        return

    if total_count < 1:
        yield "エラー: 生成枚数は1以上を指定してください"
        return

    # 設定を保存
    save_batch_settings({
        "face_path": face_path,
        "outfit_path": outfit_path,
        "bg_path": bg_path,
        "prompt_template": prompt_template,
        "prompt_folder": prompt_folder,
        "total_count": int(total_count),
        "model": model,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "allow_duplicates": allow_duplicates,
        "request_delay": request_delay,
        "error_folder": error_folder
    })

    # 画像ソースは任意（プロンプトのみでも可）
    face_source = ImageSource(face_path) if face_path else None
    outfit_source = ImageSource(outfit_path) if outfit_path else None
    bg_source = ImageSource(bg_path) if bg_path else None

    # プロンプトソース（フォルダ指定時）
    prompt_source = PromptSource(prompt_folder) if prompt_folder else None

    if prompt_source and prompt_source.files:
        yield f"📝 プロンプトフォルダ: {len(prompt_source.files)}個の.txtファイルを検出"

    # ローカルファイルの場合は警告
    has_local_files = False
    for src in [face_source, outfit_source, bg_source]:
        if src and src.files:
            for f in src.files:
                if not f.startswith(("http://", "https://")):
                    has_local_files = True
                    break

    if has_local_files:
        yield "📤 ローカルファイルは自動的にkie.aiにアップロードされます（3日間有効）"

    config = BatchConfig(
        name=job_name or f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        total_count=int(total_count),
        prompt_template=prompt_template,
        face_source=face_source,
        outfit_source=outfit_source,
        background_source=bg_source,
        prompt_source=prompt_source,
        model=model,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        allow_duplicate_combinations=allow_duplicates,
        request_delay=request_delay,
        error_folder=error_folder
    )

    max_combos = processor.get_max_combinations(config)
    if not allow_duplicates and total_count > max_combos:
        yield f"⚠️ 警告: {total_count}枚を要求していますが、{max_combos}通りの組み合わせしかありません"

    yield "📋 ジョブを作成中..."
    progress(0, desc="ジョブ作成中...")

    job_id = processor.create_batch_job(config)
    yield f"✓ ジョブ作成完了: #{job_id}"

    yield "📋 タスクを準備中..."
    progress(0.1, desc="タスク準備中...")
    created = processor.prepare_tasks(job_id, config)
    yield f"✓ {created}個のタスクを準備完了"

    def on_progress(data):
        msg = data.get("message", "")
        prog = data.get("progress", 0) / 100
        progress(0.1 + prog * 0.9, desc=msg)

    processor.set_progress_callback(on_progress)

    yield "🚀 生成開始..."
    progress(0.1, desc="生成開始...")

    try:
        results = processor.run_batch(job_id, config)

        moved_count = results.get("moved_images", 0)
        moved_info = ""
        if moved_count > 0:
            moved_info = f"\n📦 エラー画像移動: {moved_count}枚を {error_folder} に移動しました"

        summary = f"""
✅ バッチ処理完了!

📊 結果サマリー
━━━━━━━━━━━━━━━━━━━━
  合計:     {results['total']}枚
  成功:     {results['completed']}枚
  失敗:     {results['failed']}枚
  中断:     {'あり' if results['stopped'] else 'なし'}
━━━━━━━━━━━━━━━━━━━━

🔖 ジョブID: #{job_id}{moved_info}
"""
        yield summary.strip()

    except Exception as e:
        yield f"❌ エラー: {str(e)}"


def stop_batch():
    """バッチ処理を停止"""
    if processor:
        processor.stop()
        return "⏹️ 停止リクエストを送信しました"
    return "アクティブなバッチがありません"


def pause_batch():
    """バッチ処理を一時停止"""
    if processor:
        processor.pause()
        return "⏸️ 一時停止しました"
    return "アクティブなバッチがありません"


def resume_batch():
    """バッチ処理を再開"""
    if processor:
        processor.resume()
        return "▶️ 再開しました"
    return "アクティブなバッチがありません"


def get_job_list() -> List[List]:
    """ジョブ一覧を取得"""
    if not db:
        return []

    jobs = db.get_all_batch_jobs(limit=50)
    data = []

    status_map = {
        "pending": "⏳ 待機中",
        "running": "🔄 実行中",
        "completed": "✅ 完了",
        "stopped": "⏹️ 停止",
        "error": "❌ エラー"
    }

    for job in jobs:
        status = status_map.get(job["status"], job["status"])
        data.append([
            job["id"],
            job["name"],
            status,
            f"{job['completed_count']}/{job['total_count']}",
            job["created_at"]
        ])

    return data


def get_job_details(job_id: int) -> str:
    """ジョブ詳細を取得"""
    if not db or not job_id:
        return "ジョブを選択してください"

    job = db.get_batch_job(int(job_id))
    if not job:
        return "ジョブが見つかりません"

    stats = db.get_batch_statistics(int(job_id))
    tasks = db.get_tasks_by_batch(int(job_id))

    # タスクステータスアイコン
    status_icons = {
        "pending": "⏳",
        "processing": "🔄",
        "completed": "✅",
        "failed": "❌"
    }

    details = f"""
📋 ジョブ詳細
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ID:       #{job['id']}
  名前:     {job['name']}
  ステータス: {job['status']}

📊 進捗状況
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  合計:     {stats.get('total', 0)}
  完了:     {stats.get('completed', 0)}
  失敗:     {stats.get('failed', 0)}
  待機中:   {stats.get('pending', 0)}
  処理中:   {stats.get('processing', 0)}

📝 プロンプトテンプレート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{job['prompt_template']}

🔖 タスクID一覧 ({len(tasks)}件)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    for task in tasks:
        icon = status_icons.get(task['status'], "❓")
        task_id = task['api_request_id'] or "(未発行)"
        result_mark = "📷" if task['result_url'] else ""
        details += f"  {icon} #{task['id']}: {task_id} {result_mark}\n"

    details += f"""
📅 タイムスタンプ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  作成: {job['created_at']}
  更新: {job['updated_at']}
"""
    return details.strip()


def check_all_tasks(job_id: int, progress=gr.Progress()) -> str:
    """全タスクのステータスを再確認"""
    if not db or not api or not job_id:
        return "エラー: ジョブを選択してください"

    job_id = int(job_id)
    tasks = db.get_processing_tasks(job_id)

    if not tasks:
        # processing/pendingのタスクがない場合、全タスクを表示
        all_tasks = db.get_tasks_by_batch(job_id)
        stats = db.get_batch_statistics(job_id)
        return f"""
✅ 確認完了 - 未処理タスクなし

📊 最終結果
━━━━━━━━━━━━━━━━━━━━━
  完了: {stats.get('completed', 0)}件
  失敗: {stats.get('failed', 0)}件
  合計: {stats.get('total', 0)}件

ダウンロードの準備ができています。
"""

    progress(0, desc="タスクステータスを確認中...")
    updated = 0
    completed = 0
    failed = 0

    for i, task in enumerate(tasks):
        task_id = task['api_request_id']
        if not task_id:
            continue

        progress((i + 1) / len(tasks), desc=f"確認中: {i+1}/{len(tasks)}")

        result = api.query_task(task_id)

        if result.status == TaskStatus.COMPLETED:
            image_url = result.image_url
            if not image_url and result.image_urls:
                image_url = result.image_urls[0]

            db.update_task_status(
                task['id'], "completed",
                result_url=image_url,
                api_response=result.raw_response
            )
            db.increment_batch_job_count(job_id, completed=True)
            completed += 1
            updated += 1

        elif result.status == TaskStatus.FAILED:
            db.update_task_status(
                task['id'], "failed",
                error_message=result.error,
                api_response=result.raw_response
            )
            db.increment_batch_job_count(job_id, completed=False)
            failed += 1
            updated += 1

    # 全タスク完了チェック
    remaining = db.get_incomplete_tasks(job_id)
    stats = db.get_batch_statistics(job_id)

    if not remaining:
        db.update_batch_job_status(job_id, "completed")

    return f"""
🔄 ステータス確認完了

📊 今回の更新
━━━━━━━━━━━━━━━━━━━━━
  確認対象: {len(tasks)}件
  完了に更新: {completed}件
  失敗に更新: {failed}件

📊 現在の状況
━━━━━━━━━━━━━━━━━━━━━
  完了: {stats.get('completed', 0)}件
  失敗: {stats.get('failed', 0)}件
  処理中: {stats.get('processing', 0)}件
  待機中: {stats.get('pending', 0)}件
"""


def download_job_results(job_id: int, progress=gr.Progress()) -> str:
    """ジョブ結果をダウンロード"""
    if not db or not downloader or not job_id:
        return "エラー: ジョブを選択してください"

    def on_progress(data):
        msg = data.get("message", "")
        prog = data.get("progress", 0) / 100
        progress(prog, desc=msg)

    downloader.set_progress_callback(on_progress)

    results = downloader.download_batch_results(int(job_id))

    return f"""
✅ ダウンロード完了!
━━━━━━━━━━━━━━━━━━━━
  成功:   {results['downloaded']}枚
  失敗:   {results['failed']}枚
  スキップ: {results['skipped']}枚
"""


def export_zip(job_id: int) -> Optional[str]:
    """ZIPエクスポート"""
    if not db or not downloader or not job_id:
        return None

    zip_data = downloader.create_zip_archive(int(job_id))

    if zip_data:
        job = db.get_batch_job(int(job_id))
        job_name = job["name"] if job else f"job_{job_id}"
        zip_path = Path(f"./outputs/{job_name}_export.zip")
        zip_path.parent.mkdir(exist_ok=True)

        with open(zip_path, "wb") as f:
            f.write(zip_data)

        return str(zip_path)

    return None


def export_csv(job_id: int) -> Optional[str]:
    """CSVエクスポート"""
    if not db or not downloader or not job_id:
        return None

    csv_data = downloader.export_metadata_csv(int(job_id))

    job = db.get_batch_job(int(job_id))
    job_name = job["name"] if job else f"job_{job_id}"
    csv_path = Path(f"./outputs/{job_name}_metadata.csv")
    csv_path.parent.mkdir(exist_ok=True)

    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_data)

    return str(csv_path)


# =====================
# カスタムダークテーマ
# =====================
def create_dark_theme():
    """Gradio 4.x 対応ダークテーマ"""
    try:
        # Gradio 4.x
        return gr.themes.Base(
            primary_hue=gr.themes.colors.purple,
            secondary_hue=gr.themes.colors.indigo,
            neutral_hue=gr.themes.colors.slate,
            font=gr.themes.GoogleFont("Noto Sans JP"),
        ).set(
            # 背景色
            body_background_fill="#0a0a0f",
            body_background_fill_dark="#0a0a0f",
            background_fill_primary="#12121a",
            background_fill_primary_dark="#12121a",
            background_fill_secondary="#1a1a25",
            background_fill_secondary_dark="#1a1a25",

            # ブロック
            block_background_fill="#15151f",
            block_background_fill_dark="#15151f",
            block_border_color="rgba(255,255,255,0.1)",
            block_border_width="1px",
            block_label_background_fill="#1a1a28",
            block_label_text_color="#a0a0b0",
            block_radius="12px",
            block_shadow="0 4px 20px rgba(0,0,0,0.3)",

            # 入力
            input_background_fill="#0d0d12",
            input_background_fill_dark="#0d0d12",
            input_border_color="rgba(255,255,255,0.15)",
            input_border_width="1px",
            input_radius="8px",

            # ボタン
            button_primary_background_fill="linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            button_primary_background_fill_dark="linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            button_primary_background_fill_hover="linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%)",
            button_primary_text_color="white",
            button_secondary_background_fill="#2a2a3a",
            button_secondary_background_fill_dark="#2a2a3a",
            button_border_width="0px",

            # テキスト
            body_text_color="#e0e0e8",
            body_text_color_dark="#e0e0e8",
            body_text_color_subdued="#808090",

            # ボーダー
            border_color_primary="rgba(255,255,255,0.1)",
            border_color_accent="rgba(102,126,234,0.5)",

            # シャドウ
            shadow_spread="8px",
        )
    except TypeError:
        # フォールバック: 最小限の設定
        return gr.themes.Base(
            primary_hue=gr.themes.colors.purple,
            secondary_hue=gr.themes.colors.indigo,
            neutral_hue=gr.themes.colors.slate,
        )


# =====================
# Gradio UI
# =====================
def create_ui():
    """GradioのUIを作成"""

    config = load_config()
    batch_settings = get_batch_settings()
    theme = create_dark_theme()

    with gr.Blocks(
        title="Nanobananapro バッチ生成",
        theme=theme,
        css=CUSTOM_CSS
    ) as app:

        # ヘッダー
        gr.HTML("""
            <div style="text-align: center; padding: 2rem 0 1rem 0;">
                <h1 style="
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    font-size: 2.2rem;
                    font-weight: 700;
                    margin: 0;
                ">Nanobananapro バッチ生成</h1>
                <p style="color: #707080; margin-top: 0.5rem; font-size: 0.95rem;">
                    kie.ai API で画像を一括生成
                </p>
            </div>
        """)

        with gr.Tabs():
            # ============ 設定タブ ============
            with gr.Tab("⚙️ 設定"):
                with gr.Group():
                    gr.HTML("""
                        <div style="padding: 0.5rem 0;">
                            <span style="color: #667eea;">🔑</span>
                            APIキーは <a href="https://kie.ai/api-key" target="_blank"
                            style="color: #667eea;">kie.ai/api-key</a> で取得できます
                        </div>
                    """)

                    with gr.Row():
                        api_key_input = gr.Textbox(
                            label="APIキー",
                            placeholder="kie.ai のAPIキーを入力",
                            value=config.get("api_key", ""),
                            type="password",
                            scale=4
                        )
                        init_btn = gr.Button(
                            "🔌 接続",
                            variant="primary",
                            scale=1
                        )

                    init_status = gr.Textbox(
                        label="接続状態",
                        interactive=False,
                        lines=1
                    )

                    gr.HTML("""
                        <div style="
                            background: rgba(102,126,234,0.1);
                            border: 1px solid rgba(102,126,234,0.3);
                            border-radius: 8px;
                            padding: 1rem;
                            margin-top: 1rem;
                        ">
                            <p style="margin: 0; color: #a0a0b0; font-size: 0.9rem;">
                                💰 <strong>残高確認:</strong>
                                <a href="https://kie.ai/api-key" target="_blank" style="color: #667eea;">
                                    kie.ai/api-key
                                </a> で確認できます
                            </p>
                        </div>
                    """)

                init_btn.click(
                    initialize_api,
                    inputs=[api_key_input],
                    outputs=[init_status]
                )

            # ============ バッチ生成タブ ============
            with gr.Tab("🎨 バッチ生成"):
                with gr.Row(equal_height=False):
                    # 左カラム: 画像ソース
                    with gr.Column(scale=1):
                        gr.HTML("""
                            <h3 style="color: #e0e0e8; margin-bottom: 0.5rem;">
                                📁 画像ソース
                            </h3>
                            <div style="
                                background: rgba(74, 222, 128, 0.15);
                                border: 1px solid rgba(74, 222, 128, 0.4);
                                border-radius: 8px;
                                padding: 0.8rem;
                                margin-bottom: 1rem;
                                font-size: 0.85rem;
                                color: #4ade80;
                            ">
                                ✅ ローカルファイル対応: 画像は自動的にkie.aiにアップロードされます（3日間有効）
                            </div>
                        """)

                        with gr.Accordion("👤 顔画像（被写体）- file1", open=True):
                            face_input = gr.Textbox(
                                label="パス",
                                placeholder="C:/images/faces/ または画像ファイル",
                                value=batch_settings.get("face_path", ""),
                                lines=1
                            )
                            face_info = gr.Textbox(
                                label="状態",
                                interactive=False,
                                lines=1
                            )

                        with gr.Accordion("👗 服装・ポーズ - file2", open=True):
                            outfit_input = gr.Textbox(
                                label="パス",
                                placeholder="C:/images/outfits/",
                                value=batch_settings.get("outfit_path", ""),
                                lines=1
                            )
                            outfit_info = gr.Textbox(
                                label="状態",
                                interactive=False,
                                lines=1
                            )

                        with gr.Accordion("🏞️ 背景・その他 - file3", open=True):
                            bg_input = gr.Textbox(
                                label="パス",
                                placeholder="C:/images/backgrounds/",
                                value=batch_settings.get("bg_path", ""),
                                lines=1
                            )
                            bg_info = gr.Textbox(
                                label="状態",
                                interactive=False,
                                lines=1
                            )

                        combo_info = gr.Textbox(
                            label="📊 組み合わせ",
                            interactive=False,
                            lines=1
                        )

                        # 自動スキャン
                        face_input.change(
                            lambda x: scan_source(x)[0],
                            inputs=[face_input],
                            outputs=[face_info]
                        )
                        outfit_input.change(
                            lambda x: scan_source(x)[0],
                            inputs=[outfit_input],
                            outputs=[outfit_info]
                        )
                        bg_input.change(
                            lambda x: scan_source(x)[0],
                            inputs=[bg_input],
                            outputs=[bg_info]
                        )

                        for inp in [face_input, outfit_input, bg_input]:
                            inp.change(
                                calculate_max_combinations,
                                inputs=[face_input, outfit_input, bg_input],
                                outputs=[combo_info]
                            )

                    # 右カラム: 生成設定
                    with gr.Column(scale=1):
                        gr.HTML("""
                            <h3 style="color: #e0e0e8; margin-bottom: 1rem;">
                                ⚡ 生成設定
                            </h3>
                        """)

                        job_name_input = gr.Textbox(
                            label="ジョブ名",
                            placeholder="my_batch_job",
                            lines=1
                        )

                        prompt_input = gr.Textbox(
                            label="プロンプト（直接入力）",
                            placeholder="参照画像を組み合わせて、人物の顔で、服装を着せて、背景に配置した画像を生成してください...",
                            value=batch_settings.get("prompt_template", ""),
                            lines=5
                        )

                        with gr.Accordion("📝 プロンプトフォルダ（バッチ処理）", open=True):
                            gr.HTML("""
                                <div style="
                                    background: rgba(74, 222, 128, 0.15);
                                    border: 1px solid rgba(74, 222, 128, 0.4);
                                    border-radius: 8px;
                                    padding: 0.8rem;
                                    margin-bottom: 0.5rem;
                                    font-size: 0.85rem;
                                    color: #4ade80;
                                ">
                                    フォルダを指定すると、中の.txtファイルからランダムにプロンプトを選択します（重複なし）
                                </div>
                            """)
                            prompt_folder_input = gr.Textbox(
                                label="プロンプトフォルダ",
                                placeholder="C:/prompts/ （フォルダ内に複数の.txtファイル）",
                                value=batch_settings.get("prompt_folder", ""),
                                lines=1
                            )
                            prompt_folder_info = gr.Textbox(
                                label="状態",
                                interactive=False,
                                lines=1
                            )
                            prompt_folder_input.change(
                                lambda x: scan_prompt_source(x)[0],
                                inputs=[prompt_folder_input],
                                outputs=[prompt_folder_info]
                            )

                        gr.HTML("""
                            <div style="
                                background: rgba(102,126,234,0.1);
                                border-radius: 8px;
                                padding: 0.8rem;
                                margin: 0.5rem 0;
                                font-size: 0.85rem;
                                color: #a0a0b0;
                            ">
                                💡 <strong>ヒント:</strong> {face}, {outfit}, {background} でファイル名を参照可能
                            </div>
                        """)

                        total_count_input = gr.Number(
                            label="生成枚数",
                            value=batch_settings.get("total_count", 10),
                            minimum=1,
                            maximum=1000,
                            precision=0
                        )

                        with gr.Row():
                            model_input = gr.Dropdown(
                                label="モデル",
                                choices=[
                                    ("Nano Banana Pro（高品質）", "google/nano-banana-pro"),
                                    ("Nano Banana（高速）", "google/nano-banana")
                                ],
                                value=batch_settings.get("model", "google/nano-banana-pro")
                            )
                            resolution_input = gr.Dropdown(
                                label="解像度",
                                choices=["1K", "2K", "4K"],
                                value=batch_settings.get("resolution", "2K")
                            )

                        with gr.Row():
                            aspect_ratio_input = gr.Dropdown(
                                label="アスペクト比",
                                choices=["1:1", "2:3", "3:2", "3:4", "4:3",
                                         "4:5", "5:4", "9:16", "16:9"],
                                value=batch_settings.get("aspect_ratio", "1:1")
                            )
                            delay_input = gr.Slider(
                                label="リクエスト間隔（秒）",
                                minimum=0.5,
                                maximum=10,
                                value=batch_settings.get("request_delay", 2),
                                step=0.5
                            )

                        allow_duplicates_input = gr.Checkbox(
                            label="重複組み合わせを許可",
                            value=batch_settings.get("allow_duplicates", False)
                        )

                        with gr.Accordion("🚫 エラー画像の自動移動", open=True):
                            gr.HTML("""
                                <div style="
                                    background: rgba(245, 87, 108, 0.15);
                                    border: 1px solid rgba(245, 87, 108, 0.4);
                                    border-radius: 8px;
                                    padding: 0.8rem;
                                    margin-bottom: 0.5rem;
                                    font-size: 0.85rem;
                                    color: #f5576c;
                                ">
                                    生成に失敗した場合、<strong>file2（服装・ポーズ）</strong>の画像を指定フォルダに自動移動します
                                </div>
                            """)
                            error_folder_input = gr.Textbox(
                                label="エラー画像移動先フォルダ",
                                placeholder="C:/images/error_images/",
                                value=batch_settings.get("error_folder", ""),
                                lines=1
                            )

                # 実行ボタン
                with gr.Row():
                    start_btn = gr.Button(
                        "🚀 生成開始",
                        variant="primary",
                        size="lg",
                        scale=3
                    )
                    pause_btn = gr.Button("⏸️ 一時停止", scale=1)
                    resume_btn = gr.Button("▶️ 再開", scale=1)
                    stop_btn = gr.Button("⏹️ 停止", variant="stop", scale=1)

                progress_output = gr.Textbox(
                    label="📋 進捗ログ",
                    lines=10,
                    interactive=False,
                    elem_classes=["progress-box"]
                )

                start_btn.click(
                    start_batch_generation,
                    inputs=[
                        job_name_input, prompt_input, prompt_folder_input,
                        face_input, outfit_input, bg_input,
                        total_count_input, model_input, resolution_input,
                        aspect_ratio_input, allow_duplicates_input,
                        delay_input, error_folder_input
                    ],
                    outputs=[progress_output]
                )

                # プロンプトフォルダ変更時に組み合わせ数を更新
                prompt_folder_input.change(
                    calculate_max_combinations,
                    inputs=[face_input, outfit_input, bg_input, prompt_folder_input],
                    outputs=[combo_info]
                )

                stop_btn.click(stop_batch, outputs=[progress_output])
                pause_btn.click(pause_batch, outputs=[progress_output])
                resume_btn.click(resume_batch, outputs=[progress_output])

            # ============ 履歴・ダウンロードタブ ============
            with gr.Tab("📥 履歴・ダウンロード"):
                with gr.Row():
                    refresh_btn = gr.Button("🔄 一覧を更新", variant="secondary")

                job_table = gr.Dataframe(
                    headers=["ID", "ジョブ名", "ステータス", "進捗", "作成日時"],
                    datatype=["number", "str", "str", "str", "str"],
                    interactive=False,
                    elem_classes=["job-table"]
                )

                refresh_btn.click(get_job_list, outputs=[job_table])

                with gr.Row():
                    job_id_input = gr.Number(
                        label="ジョブID",
                        precision=0,
                        scale=1
                    )
                    details_btn = gr.Button("📋 詳細表示", scale=1)
                    check_tasks_btn = gr.Button(
                        "🔄 全タスク確認",
                        variant="secondary",
                        scale=1
                    )
                    download_btn = gr.Button(
                        "📥 ダウンロード",
                        variant="primary",
                        scale=1
                    )

                job_details = gr.Textbox(
                    label="ジョブ詳細",
                    lines=18,
                    interactive=False,
                    elem_classes=["progress-box"]
                )

                with gr.Row():
                    zip_btn = gr.Button("📦 ZIPエクスポート", scale=1)
                    csv_btn = gr.Button("📊 CSVエクスポート", scale=1)

                with gr.Row():
                    zip_output = gr.File(label="ZIPファイル")
                    csv_output = gr.File(label="CSVファイル")

                details_btn.click(
                    get_job_details,
                    inputs=[job_id_input],
                    outputs=[job_details]
                )

                check_tasks_btn.click(
                    check_all_tasks,
                    inputs=[job_id_input],
                    outputs=[job_details]
                )

                download_btn.click(
                    download_job_results,
                    inputs=[job_id_input],
                    outputs=[job_details]
                )

                zip_btn.click(
                    export_zip,
                    inputs=[job_id_input],
                    outputs=[zip_output]
                )

                csv_btn.click(
                    export_csv,
                    inputs=[job_id_input],
                    outputs=[csv_output]
                )

        # フッター
        gr.HTML("""
            <div style="
                text-align: center;
                padding: 1.5rem;
                margin-top: 1rem;
                border-top: 1px solid rgba(255,255,255,0.1);
                color: #606070;
                font-size: 0.85rem;
            ">
                Powered by <a href="https://kie.ai" target="_blank" style="color: #667eea;">kie.ai</a>
                • Nanobananapro API
            </div>
        """)

        # 起動時に自動初期化
        if config.get("api_key"):
            app.load(
                lambda: initialize_api(config["api_key"]),
                outputs=[init_status]
            )

    return app


if __name__ == "__main__":
    app = create_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True
    )
