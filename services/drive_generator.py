"""
Drive Generator Service
從 Google Drive PDF 文件產生 iPAS 考試題目。
支援掃描圖檔 PDF（無文字層），透過 Gemini 多模態能力讀取。
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pdf2image import convert_from_path

from services.question_generator import _parse_response, insert_question_with_dedup

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL = "gemini-2.5-flash"
PAGES_PER_BATCH = 20
DPI = 150
IPAS_FOLDER_ID = "1QutCz68R8-7UX2tPD7AzRI5zxAg0msiG"

SYSTEM_PROMPT = """你是一位 iPAS 產業人才能力鑑定的出題專家。
請根據教材頁面內容產生高品質考試題目。

請嚴格遵守以下 JSON 格式輸出，不要輸出任何其他文字：

[
  {
    "type": "choice",
    "content": "題目內容",
    "option_a": "選項A",
    "option_b": "選項B",
    "option_c": "選項C",
    "option_d": "選項D",
    "answer": "A",
    "difficulty": 1,
    "explanation": "說明正確答案的理由，並簡述干擾選項為何錯誤"
  },
  {
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": 2,
    "explanation": "說明該敘述為何正確或錯誤，引用教材中的具體內容"
  }
]

規則：
1. 選擇題 answer 只能是 A/B/C/D
2. 是非題 answer 只能是 T/F
3. difficulty 只能是 1(簡單)、2(中等)、3(困難)
4. 簡單題：定義、基本概念
5. 中等題：比較、應用、流程
6. 困難題：計算、整合分析、情境判斷
7. 題目必須基於教材內容，不可憑空捏造
8. 每題必須有明確唯一正確答案
9. explanation 必須基於教材內容，1-3 句話
10. 選擇題的 explanation 須說明正確選項理由，並提及至少一個干擾選項為何錯
11. 是非題的 explanation 須說明該敘述為何正確或錯誤
"""


def list_drive_pdfs(folder_id: str = IPAS_FOLDER_ID) -> list[dict]:
    """列出 Google Drive 資料夾中的 PDF 檔案"""
    result = subprocess.run(
        [
            "gws", "drive", "files", "list",
            "--params", json.dumps({
                "q": f"'{folder_id}' in parents and mimeType = 'application/pdf'",
                "pageSize": 50,
                "fields": "files(id,name,size)",
            }),
        ],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return data.get("files", [])


def download_pdf(file_id: str, output_path: str) -> str:
    """從 Google Drive 下載 PDF"""
    result = subprocess.run(
        [
            "gws", "drive", "files", "get",
            "--params", json.dumps({"fileId": file_id, "alt": "media"}),
            "--output", output_path,
        ],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    if data.get("status") != "success":
        raise RuntimeError(f"Download failed: {data}")
    return output_path


def _pdf_to_images(pdf_path: str, first_page: int, last_page: int,
                   output_dir: str) -> list[Path]:
    """將 PDF 指定頁面轉為 JPEG 圖片"""
    images = convert_from_path(
        pdf_path, first_page=first_page, last_page=last_page, dpi=DPI,
    )
    paths = []
    for i, img in enumerate(images):
        page_num = first_page + i
        path = Path(output_dir) / f"page_{page_num:03d}.jpg"
        img.save(str(path), "JPEG", quality=80)
        paths.append(path)
    return paths


def _generate_from_images(
    image_paths: list[Path],
    num_choice: int = 3,
    num_tf: int = 2,
    difficulty: Optional[int] = None,
) -> list[dict]:
    """將頁面圖片送給 Gemini 出題"""
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))

    diff_hint = ""
    if difficulty:
        labels = {1: "簡單（定義、基本概念）", 2: "中等（比較、應用）", 3: "困難（計算、整合分析）"}
        diff_hint = f"\n請只產生難度 {difficulty} 的題目：{labels.get(difficulty, '')}"

    parts.append(
        f"請根據以上教材頁面內容產生 {num_choice} 題選擇題和 {num_tf} 題是非題。"
        f"{diff_hint}\n請直接輸出 JSON 陣列，不要加其他說明文字。"
    )

    response = _client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    return _parse_response(response.text)


def get_pdf_page_count(pdf_path: str) -> int:
    """取得 PDF 總頁數"""
    from pdfplumber import open as pdf_open
    with pdf_open(pdf_path) as pdf:
        return len(pdf.pages)


def generate_from_drive_pdf(
    file_id: str,
    file_name: str,
    num_choice: int = 3,
    num_tf: int = 2,
    difficulty: Optional[int] = None,
    pages_per_batch: int = PAGES_PER_BATCH,
    db_path: str = "data/questions.db",
    chroma_dir: str = "data/chroma",
) -> dict:
    """完整流程：下載 PDF → 分批出題 → 去重入庫"""
    results = {
        "file_name": file_name,
        "total_generated": 0,
        "total_inserted": 0,
        "total_duplicates": 0,
        "batches": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 下載 PDF
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"📥 下載 {file_name}...")
        download_pdf(file_id, pdf_path)

        # 2. 取得頁數
        total_pages = get_pdf_page_count(pdf_path)
        print(f"📄 共 {total_pages} 頁，每 {pages_per_batch} 頁一批")

        # 3. 分批處理
        chapter = file_name.replace(".pdf", "")
        for start in range(1, total_pages + 1, pages_per_batch):
            end = min(start + pages_per_batch - 1, total_pages)
            print(f"\n📝 處理第 {start}-{end} 頁...")

            # 轉圖片
            img_dir = os.path.join(tmpdir, f"batch_{start}")
            os.makedirs(img_dir, exist_ok=True)
            image_paths = _pdf_to_images(pdf_path, start, end, img_dir)

            # 出題
            try:
                questions = _generate_from_images(
                    image_paths, num_choice, num_tf, difficulty,
                )
            except Exception as e:
                print(f"   ⚠️ 出題失敗: {e}")
                results["batches"].append({
                    "pages": f"{start}-{end}",
                    "error": str(e),
                })
                continue

            # 入庫（含去重）
            batch_inserted = 0
            batch_dupes = 0
            for q in questions:
                q["chapter"] = chapter
                q["source_file"] = f"{file_name} (p.{start}-{end})"
                result = insert_question_with_dedup(
                    q, db_path=db_path, chroma_dir=chroma_dir,
                )
                if result["inserted"]:
                    batch_inserted += 1
                else:
                    batch_dupes += 1

            results["total_generated"] += len(questions)
            results["total_inserted"] += batch_inserted
            results["total_duplicates"] += batch_dupes
            results["batches"].append({
                "pages": f"{start}-{end}",
                "generated": len(questions),
                "inserted": batch_inserted,
                "duplicates": batch_dupes,
            })
            print(f"   ✅ 產生 {len(questions)} 題，入庫 {batch_inserted}，重複 {batch_dupes}")

    return results


def generate_all_drive_pdfs(
    folder_id: str = IPAS_FOLDER_ID,
    num_choice: int = 3,
    num_tf: int = 2,
    difficulty: Optional[int] = None,
    db_path: str = "data/questions.db",
    chroma_dir: str = "data/chroma",
) -> list[dict]:
    """處理 Drive 資料夾中所有 PDF"""
    pdfs = list_drive_pdfs(folder_id)
    print(f"找到 {len(pdfs)} 個 PDF 檔案\n")

    all_results = []
    for pdf in sorted(pdfs, key=lambda x: x["name"]):
        print(f"\n{'='*60}")
        print(f"📚 {pdf['name']}")
        print(f"{'='*60}")
        result = generate_from_drive_pdf(
            file_id=pdf["id"],
            file_name=pdf["name"],
            num_choice=num_choice,
            num_tf=num_tf,
            difficulty=difficulty,
            db_path=db_path,
            chroma_dir=chroma_dir,
        )
        all_results.append(result)

    return all_results
