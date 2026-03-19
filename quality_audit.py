"""
題目品質審查：本地檢測，不需要 API。
檢查項目：
1. 格式完整性（選項、答案、explanation）
2. 答案合法性
3. 重複選項
4. 題目長度異常
5. 簡體中文殘留
6. 答案分布
7. 難度分布
8. 抽樣輸出供人工檢查
"""
import sqlite3
import random
import re

DB_PATH = "data/questions.db"


def load_all():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM questions").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_format(questions):
    """檢查格式完整性"""
    issues = []
    for q in questions:
        qid = q["id"]

        # 題目內容
        if not q["content"] or len(q["content"].strip()) < 5:
            issues.append((qid, "CRITICAL", "題目內容過短或為空"))

        # 選擇題選項
        if q["type"] == "choice":
            for opt in ["option_a", "option_b", "option_c", "option_d"]:
                if not q.get(opt) or len(q[opt].strip()) == 0:
                    issues.append((qid, "CRITICAL", f"{opt} 為空"))
            if q["answer"] not in ("A", "B", "C", "D"):
                issues.append((qid, "CRITICAL", f"答案 '{q['answer']}' 不合法"))

        # 是非題
        if q["type"] == "truefalse":
            if q["answer"] not in ("T", "F"):
                issues.append((qid, "CRITICAL", f"答案 '{q['answer']}' 不合法"))

        # explanation
        if not q.get("explanation") or len(q["explanation"].strip()) < 5:
            issues.append((qid, "HIGH", "explanation 過短或缺失"))

        # 難度
        if q["difficulty"] not in (1, 2, 3):
            issues.append((qid, "HIGH", f"難度 {q['difficulty']} 不合法"))

    return issues


def check_duplicated_options(questions):
    """選擇題中有重複選項"""
    issues = []
    for q in questions:
        if q["type"] != "choice":
            continue
        opts = [q["option_a"], q["option_b"], q["option_c"], q["option_d"]]
        opts_stripped = [o.strip() for o in opts if o]
        if len(set(opts_stripped)) < len(opts_stripped):
            issues.append((q["id"], "HIGH", f"有重複選項: {opts_stripped}"))
    return issues


def check_length_anomaly(questions):
    """題目或選項長度異常"""
    issues = []
    for q in questions:
        if len(q["content"]) > 500:
            issues.append((q["id"], "MEDIUM", f"題目過長 ({len(q['content'])} 字)"))
        if len(q["content"]) < 10:
            issues.append((q["id"], "HIGH", f"題目過短 ({len(q['content'])} 字)"))

        if q["type"] == "choice":
            for opt_key in ["option_a", "option_b", "option_c", "option_d"]:
                opt = q.get(opt_key, "")
                if opt and len(opt) > 200:
                    issues.append((q["id"], "MEDIUM", f"{opt_key} 過長 ({len(opt)} 字)"))
    return issues


def check_simplified_chinese(questions):
    """檢測簡體中文殘留（僅檢測確定為簡體的字，排除繁簡共用字）"""
    # 只保留「確實只在簡體中使用、繁體中不使用」的字
    # 排除了繁簡共用字如：高、通、合、善、燃、包、摘、只、几、吃 等
    # 繁簡共用字排除清單（這些字在繁體中文中正常使用，不應視為簡體殘留）：
    # 高、通、合、善、燃、包、摘、只、几、吃、渣、准、辨、焰、撤、撰、跨、卸、
    # 症、着、尸、干、并、次、涌、园、堡、塞、巡、巢、眉、穿、耀、臭、魂、鬼、片、
    # 征、径、跑、斗、奇、姊、娘、咸、几
    sc_chars = set(
        "与为从个么义乌书买产亲众优伤佣侣俭债倾偿储儿兑关兴养冲决况冻净凤"
        "凭击创别则刚剂剑剥剧劝办务劲动势勋区协压厂厅历厉厨县叁参变叙叠叹"
        "吕吗员呐呕呛呜响哟唤啰喷嘱团围图圣场坏坚块坛垄垦垫堕墙壮声壳处备复够头夸夺奋"
        "奖奥妆妇妈妒妪娱婴宁宝实宠审宪宫宽宾对导寻尔尽层属岁岂岗岛岭峡"
        "币帅师帐帧帮幂广庄庆库应庙庞废开异弃张弥弯归当录彻"
        "悦悬惊惧惩惫愿慑态怀忆忧惭愤恳恶恼悯憎戏战户执扩扫扬扰抚择担拟拢拣"
        "挚挟挡挤挥损捡换据捣掳搁摄摆摇撑擞攒敌敛数斋斓旷时昼显晋晒晕暂暧术机杀杂"
        "权条来杨极构枪柜栅标栈栋样桥桩梦检椭楼榨橱欢歼残毁毕气汇汉沟没沥沧沪泪泼泽洁洒"
        "浅浆浇浓涡涣涤润涨涩淀渊渗减温湿溃溅滚滞滤滨灭灯灵灾灿炉炼烁烂烃烛烟热焕"
        "爱爷爸牍牵犊犹独猎猕献猪猫猬猴玑玛玮环现琼瑶瓒瓯电畴疗疯痴瘫盏盐监盖盘"
        "矫码砖础硕确碍祷祸禀禄离种积称穷窃窑窜窝窥窦竖竞笔笼筑筛筝箓签简粮纠纤红纪纯"
        "纱纲纳纵纷纸纹纺纽线绊绍经绑绒结绕绘给络绝绞统继绩绪续缀缅缆缉缔缕编缘缠缩缴"
        "罗罚罢网羡习翘联聂聪肃肠肤肿胀胁胆脉脏脑脓脸腊腌腻腾"
        "举觉览观规视触计认讯记讲讹许论设访诉诊证诈词详误诱说请诸诺读调谅谈谊谋谐谓谚谜"
        "谢谱谨贝贞贡财责贤败货质贩贪贬购贮贴贵贷贸费贺贼赁赂赃资赊赋赌赎赏赐赔赖赘赛"
        "赠赢赵赶趋跃跄践跸踊蹑蹒蹿躏车轧转轮软轰辅辆辉辑输辩达迁过迈运还这进远违"
        "连迟迹选递逊逻遗遥邓邮邻郑鉴锁锅错锣锦键锻镇镜闭问闻阀阁阅阔队阴阳阶际陆陈陕"
        "陨险隐隶难雏雾韦韩页项顺须顿预领颁频颖题颜额风飞饥饭饮饰饱饲饺饼馅馆馒驰驱骂"
        "验骏骗鬓鱼鸟鸡鸣鸭鸿鹅鹏鹤鹰麦黾齐齿龙龟"
    )

    issues = []
    for q in questions:
        found = []
        text = q["content"] + (q.get("explanation") or "")
        if q["type"] == "choice":
            text += (q.get("option_a") or "") + (q.get("option_b") or "")
            text += (q.get("option_c") or "") + (q.get("option_d") or "")

        for ch in text:
            if ch in sc_chars:
                found.append(ch)

        if found:
            unique = list(set(found))[:10]
            issues.append((q["id"], "MEDIUM", f"簡體字: {''.join(unique)}"))
    return issues


def check_answer_distribution(questions):
    """答案分布統計"""
    choice_ans = {}
    tf_ans = {}
    for q in questions:
        if q["type"] == "choice":
            choice_ans[q["answer"]] = choice_ans.get(q["answer"], 0) + 1
        elif q["type"] == "truefalse":
            tf_ans[q["answer"]] = tf_ans.get(q["answer"], 0) + 1
    return choice_ans, tf_ans


def check_difficulty_distribution(questions):
    """難度分布"""
    dist = {}
    for q in questions:
        dist[q["difficulty"]] = dist.get(q["difficulty"], 0) + 1
    return dist


def sample_questions(questions, n=10):
    """隨機抽樣供人工檢查"""
    random.seed(99)
    sample = random.sample(questions, min(n, len(questions)))
    return sample


def main():
    questions = load_all()
    total = len(questions)
    choice_qs = [q for q in questions if q["type"] == "choice"]
    tf_qs = [q for q in questions if q["type"] == "truefalse"]

    print(f"{'='*60}")
    print(f"題目品質審查報告")
    print(f"{'='*60}")
    print(f"總題數: {total} (選擇 {len(choice_qs)}, 是非 {len(tf_qs)})")
    print()

    # 1. 格式檢查
    all_issues = []
    all_issues.extend(check_format(questions))
    all_issues.extend(check_duplicated_options(questions))
    all_issues.extend(check_length_anomaly(questions))
    all_issues.extend(check_simplified_chinese(questions))

    critical = [i for i in all_issues if i[1] == "CRITICAL"]
    high = [i for i in all_issues if i[1] == "HIGH"]
    medium = [i for i in all_issues if i[1] == "MEDIUM"]

    print(f"--- 問題統計 ---")
    print(f"  CRITICAL: {len(critical)}")
    print(f"  HIGH:     {len(high)}")
    print(f"  MEDIUM:   {len(medium)}")
    print()

    if critical:
        print(f"--- CRITICAL 問題 ---")
        for qid, sev, msg in critical[:20]:
            print(f"  ID {qid}: {msg}")
        print()

    if high:
        print(f"--- HIGH 問題 ---")
        for qid, sev, msg in high[:20]:
            print(f"  ID {qid}: {msg}")
        print()

    if medium:
        print(f"--- MEDIUM 問題 (前 20) ---")
        for qid, sev, msg in medium[:20]:
            print(f"  ID {qid}: {msg}")
        print()

    # 2. 答案分布
    choice_ans, tf_ans = check_answer_distribution(questions)
    print(f"--- 選擇題答案分布 ---")
    total_c = sum(choice_ans.values())
    for ans in "ABCD":
        cnt = choice_ans.get(ans, 0)
        pct = cnt / total_c * 100 if total_c else 0
        bar = "#" * int(pct)
        print(f"  {ans}: {cnt:>4} ({pct:>5.1f}%) {bar}")
    print()

    print(f"--- 是非題答案分布 ---")
    total_tf = sum(tf_ans.values())
    for ans in "TF":
        cnt = tf_ans.get(ans, 0)
        pct = cnt / total_tf * 100 if total_tf else 0
        print(f"  {ans}: {cnt:>4} ({pct:>5.1f}%)")
    print()

    # 3. 難度分布
    diff_dist = check_difficulty_distribution(questions)
    print(f"--- 難度分布 ---")
    for d in [1, 2, 3]:
        cnt = diff_dist.get(d, 0)
        pct = cnt / total * 100
        label = {1: "簡單", 2: "中等", 3: "困難"}[d]
        print(f"  {label} (d={d}): {cnt:>4} ({pct:>5.1f}%)")
    print()

    # 4. 章節分布
    ch_dist = {}
    for q in questions:
        ch_dist[q["chapter"]] = ch_dist.get(q["chapter"], 0) + 1
    print(f"--- 章節分布 (前 15) ---")
    for ch, cnt in sorted(ch_dist.items(), key=lambda x: -x[1])[:15]:
        print(f"  {cnt:>4} 題  {ch}")
    print()

    # 5. 隨機抽樣
    print(f"--- 隨機抽樣 (5 題選擇 + 5 題是非) ---")
    for q in sample_questions(choice_qs, 5):
        print(f"\n  [ID {q['id']}] d={q['difficulty']} ch={q['chapter'][:20]}")
        print(f"  Q: {q['content'][:100]}")
        print(f"  A:{q['option_a'][:30]}  B:{q['option_b'][:30]}")
        print(f"  C:{q['option_c'][:30]}  D:{q['option_d'][:30]}")
        print(f"  Ans: {q['answer']}  Exp: {(q.get('explanation') or '')[:80]}")

    print()
    for q in sample_questions(tf_qs, 5):
        print(f"\n  [ID {q['id']}] d={q['difficulty']} ch={q['chapter'][:20]}")
        print(f"  Q: {q['content'][:120]}")
        print(f"  Ans: {q['answer']}  Exp: {(q.get('explanation') or '')[:80]}")

    # 總結
    print(f"\n{'='*60}")
    print(f"審查總結")
    print(f"{'='*60}")
    health = "PASS" if len(critical) == 0 and len(high) == 0 else "FAIL"
    print(f"  狀態: {health}")
    print(f"  CRITICAL: {len(critical)}, HIGH: {len(high)}, MEDIUM: {len(medium)}")

    # 回傳需要刪除的 ID
    delete_ids = [qid for qid, sev, _ in all_issues if sev == "CRITICAL"]
    if delete_ids:
        print(f"\n  建議刪除 {len(delete_ids)} 題 CRITICAL 問題: {delete_ids}")


if __name__ == "__main__":
    main()
