"""
第三輪 B：針對 01-05 核心教材，用不同出題角度產生新題。
三種角度：計算題、易混淆概念比較、情境案例分析。
"""
import json
import gc
import os
import sys
import time
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from pdf2image import convert_from_path

from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma
from services.drive_generator import download_pdf, get_pdf_page_count
from services.question_generator import _parse_response, insert_question_with_dedup

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"

PAGES_PER_BATCH = 10
DPI = 100
JPEG_QUALITY = 60
MAX_PAGES = 200
MAX_WORKERS = 8

CORE_TEXTBOOKS = [
    "01氣候變遷與溫室氣體管理(上).pdf",
    "02氣候變遷與溫室氣體管理(下).pdf",
    "03溫室氣體盤查作業.pdf",
    "04溫室氣體減量作業與減量額度.pdf",
    "05產品碳足跡.pdf",
]

SUMMARY_PROMPT = """請仔細閱讀以上教材頁面，擷取所有重要知識點。

輸出格式（純文字條列）：
- 每個知識點一行
- 包含：專有名詞定義、數據數字、公式、流程步驟、法規條文、比較差異、案例
- 盡量保留原文的精確用詞和數據
- 不要省略細節，寧可多列不要少列
"""

# 三種不同角度的出題 prompt
ANGLE_PROMPTS = {
    "calculation": {
        "label": "計算與數據題",
        "prompt": """你是 iPAS 出題專家。請根據以下教材重點，專門出「計算題」和「數據記憶題」。

教材重點：
{summary}

要求：
- 選擇題必須涉及具體數字、百分比、換算公式、GWP 值、排放係數等
- 是非題要考具體數據的正確性（例如：CO2 的 GWP 為 1，CH4 的 GWP 為 28）
- 如果頁面沒有數據內容，就出「流程步驟排序」或「時間先後」相關的題目
- 不要出純定義題，要有數字或順序

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 3, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 2, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
    "comparison": {
        "label": "易混淆概念比較題",
        "prompt": """你是 iPAS 出題專家。請根據以下教材重點，專門出「概念比較題」和「易混淆辨析題」。

教材重點：
{summary}

要求：
- 找出容易混淆的概念對（如：範疇一 vs 範疇二、直接排放 vs 間接排放、碳稅 vs 碳交易）
- 選擇題要考「以下哪個屬於 X 而非 Y」、「X 和 Y 的差異在於」
- 是非題要考容易搞混的敘述（把 A 的特徵說成 B 的）
- 干擾選項要用相似概念製造混淆

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 2, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 2, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
    "scenario": {
        "label": "情境案例分析題",
        "prompt": """你是 iPAS 出題專家。請根據以下教材重點，專門出「情境題」和「案例應用題」。

教材重點：
{summary}

要求：
- 每題先描述一個企業或組織的情境（例如：某製造業公司要進行碳盤查...）
- 然後問在這個情境下應該如何操作、適用什麼標準、歸類為哪個範疇
- 是非題要描述一個做法，問這個做法是否正確
- 情境要具體且貼近實務，不要太抽象

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 3, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 2, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
}


def load_drive_files():
    with open("data/drive_files.json") as f:
        return {f["name"]: f["id"] for f in json.load(f)}


def pdf_to_images(pdf_path, first_page, last_page, output_dir):
    images = convert_from_path(
        pdf_path, first_page=first_page, last_page=last_page, dpi=DPI,
    )
    paths = []
    for i, img in enumerate(images):
        path = Path(output_dir) / f"page_{first_page + i:03d}.jpg"
        img.save(str(path), "JPEG", quality=JPEG_QUALITY)
        paths.append(path)
    del images
    gc.collect()
    return paths


def step1_summarize(image_paths):
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))
    parts.append(SUMMARY_PROMPT)

    response = _client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )
    return response.text


def step2_generate(summary, angle_key, num_choice, num_tf):
    angle = ANGLE_PROMPTS[angle_key]
    prompt = angle["prompt"].format(
        summary=summary,
        num_choice=num_choice,
        num_tf=num_tf,
    )
    response = _client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.95,
            max_output_tokens=4096,
        ),
    )
    return _parse_response(response.text)


def _call_with_retry(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
            time.sleep(20)
            return fn(*args)
        raise


def process_batch(pdf_path, start, end, tmpdir, file_name, angle_key):
    img_dir = os.path.join(tmpdir, f"{angle_key}_p{start}")
    os.makedirs(img_dir, exist_ok=True)

    # Step 1: 圖片 → 摘要
    image_paths = pdf_to_images(pdf_path, start, end, img_dir)
    try:
        summary = _call_with_retry(step1_summarize, image_paths)
    except Exception as e:
        print(f"    p.{start}-{end} summary error: {str(e)[:80]}")
        return []
    finally:
        for p in image_paths:
            p.unlink(missing_ok=True)

    if not summary or len(summary.strip()) < 50:
        return []

    # Step 2: 摘要 → 角度出題
    num_choice = 3 if angle_key == "comparison" else 2
    num_tf = 2 if angle_key == "scenario" else 1

    try:
        questions = _call_with_retry(
            step2_generate, summary, angle_key, num_choice, num_tf,
        )
    except Exception as e:
        print(f"    p.{start}-{end} {angle_key} error: {str(e)[:80]}")
        return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end},{angle_key},r3b)"

    return questions


def process_one_pdf(file_id, file_name):
    print(f"\n{'='*60}")
    print(f"R3B: {file_name}")
    print(f"{'='*60}")

    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"  Downloading...")
        download_pdf(file_id, pdf_path)

        total_pages = min(get_pdf_page_count(pdf_path), MAX_PAGES)
        print(f"  {total_pages} pages")

        batches = []
        for start in range(1, total_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, total_pages)
            batches.append((start, end))

        angles = list(ANGLE_PROMPTS.keys())
        total_tasks = len(batches) * len(angles)
        print(f"  {len(batches)} batches x {len(angles)} angles = {total_tasks} tasks")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for start, end in batches:
                for angle_key in angles:
                    future = executor.submit(
                        process_batch, pdf_path, start, end, tmpdir,
                        file_name, angle_key,
                    )
                    futures[future] = (start, end, angle_key)

            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                questions = future.result()
                inserted = 0
                duped = 0
                for q in questions:
                    result = insert_question_with_dedup(q)
                    if result["inserted"]:
                        inserted += 1
                    else:
                        duped += 1
                results["generated"] += len(questions)
                results["inserted"] += inserted
                results["duplicates"] += duped

                if done_count % 10 == 0:
                    print(f"  [{done_count}/{total_tasks}] "
                          f"+{results['generated']} gen, "
                          f"{results['inserted']} new, "
                          f"{results['duplicates']} dup")

    gc.collect()
    print(f"  Done: +{results['generated']} gen, "
          f"{results['inserted']} new, {results['duplicates']} dup")
    return results


def main():
    init_db()
    migrate_add_explanation()
    init_chroma()

    name_to_id = load_drive_files()

    total_gen = 0
    total_ins = 0
    total_dup = 0

    print(f"Round 3B: {len(CORE_TEXTBOOKS)} core textbooks x 3 angles")
    print(f"Angles: {', '.join(a['label'] for a in ANGLE_PROMPTS.values())}")
    print(f"DPI={DPI}, pages/batch={PAGES_PER_BATCH}, workers={MAX_WORKERS}\n")

    for i, name in enumerate(CORE_TEXTBOOKS):
        file_id = name_to_id.get(name)
        if not file_id:
            print(f"[{i+1}/{len(CORE_TEXTBOOKS)}] SKIP: {name}")
            continue

        try:
            result = process_one_pdf(file_id, name)
            total_gen += result["generated"]
            total_ins += result["inserted"]
            total_dup += result["duplicates"]
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

        print(f"  Cooling down...")
        gc.collect()
        time.sleep(5)

    print(f"\n{'='*60}")
    print(f"Round 3B complete!")
    print(f"  Generated: {total_gen}")
    print(f"  Inserted:  {total_ins}")
    print(f"  Duplicates: {total_dup}")

    conn = sqlite3.connect(DB_PATH)
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"  Total questions: {total_q}")


if __name__ == "__main__":
    main()
