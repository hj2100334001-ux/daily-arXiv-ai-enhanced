#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
本地一键爬取脚本 / Local one-click crawl runner
=================================================

用途：不依赖 GitHub 定时任务，自己在本地运行，爬取 -> AI 中文总结 -> 更新网站数据。
特点：
  1. 顶部「参数区」可自由修改（爬取日期范围、关键词、分类、数量、模型等）。
  2. 自动维护运行记录 crawl_history.json（记录每次什么时候跑、参数、新增数量）。
  3. 自动按论文 arXiv id 去重：已经爬过 / 已发布的论文不会重复爬取。
  4. 可选择把结果推送到 data 分支，网页会自动更新。

运行方式（在 daily-arXiv-ai-enhanced 目录下）：
    .\.venv\Scripts\python.exe run_local.py
或者直接双击运行 run_local.ps1
"""

import os
import sys
import json
import shutil
import subprocess
import datetime
from pathlib import Path

# ============================================================
#  参数区：需要修改的东西都在这里
# ============================================================
CONFIG = {
    # ---------- 爬取哪段时间的论文（arXiv 提交日期，格式 "YYYY-MM-DD"）----------
    # 方式一：直接写死起止日期（含首尾两天）
    "START_DATE": "2026-07-08",
    "END_DATE":   "2026-07-09",
    # 方式二：如果把 LAST_N_DAYS 设成一个整数（例如 1），
    #         就会忽略上面的起止日期，改为「最近 N 天（含今天）」。不用就保持 None。
    "LAST_N_DAYS": None,

    # 论文在网页上归档到哪个日期（页面按此日期分组）。None = 用 END_DATE。
    "LABEL_DATE": None,

    # ---------- 过滤条件 ----------
    "CATEGORIES": "cs.CV, cs.CL, cs.AI",     # arXiv 分类，逗号分隔
    "KEYWORDS":   "gui agent, grounding",     # 只匹配「标题」；留空 "" 表示不按关键词过滤
    "KEYWORD_MODE": "any",                    # any = 命中任一关键词；all = 需要全部命中

    # ---------- 数量 ----------
    "KEEP_LATEST": 20,        # 本次去重后最多保留多少篇（取时间最新的）
    "SEARCH_POOL_SIZE": 400,  # 先从 arXiv 拉取多少篇候选，再做过滤/去重（建议 = KEEP_LATEST 的 10~20 倍）

    # ---------- AI 中文总结 ----------
    "LANGUAGE": "Chinese",                       # 网页支持 Chinese / English
    "AI_PROVIDER": "trapi",                       # 使用 TRAPI（微软内部，靠 az login 授权，无需 API key）
    "TRAPI_MODEL": "gpt-5.4-mini_2026-03-17",
    "AI_MAX_WORKERS": 4,                          # AI 并行线程数

    # ---------- 发布 ----------
    "PUSH_TO_DATA_BRANCH": True,   # True = 推送到 data 分支让网页更新；False = 只在本地生成文件
    "MAKE_MARKDOWN": True,         # 是否顺便生成 .md（网页用不到，仅作归档）
    "GIT_REMOTE": "origin",
    "DATA_BRANCH": "data",
}
# ============================================================
#  参数区结束（下面一般不需要改）
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent
MAIN_DATA = REPO_ROOT / "data"
HISTORY_FILE = REPO_ROOT / "crawl_history.json"


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None, env=None, check=True):
    """运行子进程并把输出直接打到控制台。"""
    log(f"\n$ {' '.join(str(c) for c in cmd)}   (cwd={cwd})")
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"命令执行失败（退出码 {result.returncode}）: {' '.join(str(c) for c in cmd)}")
    return result.returncode


def load_dotenv_into_environ():
    """如果仓库根目录有 .env，就把里面的 KEY=VALUE 载入环境变量。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_jsonl(path):
    items = []
    p = Path(path)
    if not p.exists():
        return items
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def write_jsonl(path, items):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def dedup_keep_order(items):
    """按 id 去重，保留首次出现的顺序。"""
    seen = set()
    result = []
    for item in items:
        pid = item.get("id", "")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        result.append(item)
    return result


def collect_seen_ids(data_dir):
    """从某个 data 目录下所有 *.jsonl 收集已存在的论文 id。"""
    ids = set()
    d = Path(data_dir)
    if not d.exists():
        return ids
    for jsonl in d.glob("*.jsonl"):
        for item in read_jsonl(jsonl):
            pid = item.get("id", "")
            if pid:
                ids.add(pid)
    return ids


def resolve_dates(cfg):
    last_n = cfg.get("LAST_N_DAYS")
    if isinstance(last_n, int) and last_n > 0:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=last_n - 1)
        end = today
        start_s, end_s = start.isoformat(), end.isoformat()
    else:
        start_s, end_s = cfg["START_DATE"], cfg["END_DATE"]
        # 校验格式
        for d in (start_s, end_s):
            datetime.datetime.strptime(d, "%Y-%m-%d")
    label = cfg.get("LABEL_DATE") or end_s
    datetime.datetime.strptime(label, "%Y-%m-%d")
    return start_s, end_s, label


def build_subprocess_env(cfg, extra):
    env = os.environ.copy()
    # 确保子进程文件读写默认 UTF-8（Windows 上很关键）
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def ensure_data_worktree(cfg):
    """准备一个指向 data 分支的 git worktree：.data-branch/"""
    remote = cfg["GIT_REMOTE"]
    branch = cfg["DATA_BRANCH"]
    wt = REPO_ROOT / ".data-branch"

    run(["git", "fetch", remote, branch], cwd=REPO_ROOT, check=False)

    if wt.exists() and (wt / ".git").exists():
        run(["git", "-C", str(wt), "checkout", branch], cwd=REPO_ROOT, check=False)
        run(["git", "-C", str(wt), "pull", "--ff-only", remote, branch], cwd=REPO_ROOT, check=False)
        return wt

    if wt.exists():
        raise RuntimeError(f"{wt} 已存在但不是 git worktree，请手动删除后重试。")

    # 本地是否已有 data 分支
    has_local = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(REPO_ROOT),
    ).returncode == 0
    if has_local:
        run(["git", "worktree", "add", str(wt), branch], cwd=REPO_ROOT)
    else:
        run(["git", "worktree", "add", "-b", branch, str(wt), f"{remote}/{branch}"], cwd=REPO_ROOT)
    return wt


def update_file_list(data_dir, assets_dir):
    """重新生成 assets/file-list.txt（网页据此发现有哪些日期的数据）。"""
    data_dir = Path(data_dir)
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    # 跳过下划线开头的临时/测试文件（如 _run_*、_test2）
    names = sorted(p.name for p in data_dir.glob("*.jsonl") if not p.name.startswith("_"))
    (assets_dir / "file-list.txt").write_text("\n".join(names) + "\n", encoding="utf-8")


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def save_history(records):
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def print_recent_history(records, n=5):
    if not records:
        log("（暂无历史运行记录）")
        return
    log(f"最近 {min(n, len(records))} 次运行记录：")
    for rec in records[-n:]:
        log(
            f"  - {rec.get('run_time', '?')} | 范围 {rec.get('start_date')}~{rec.get('end_date')} "
            f"| 关键词 '{rec.get('keywords')}' | 新增 {rec.get('new_count')} 篇 "
            f"| 归档到 {rec.get('label_date')}"
        )


def main():
    cfg = CONFIG
    load_dotenv_into_environ()
    MAIN_DATA.mkdir(parents=True, exist_ok=True)

    start_s, end_s, label = resolve_dates(cfg)
    lang = cfg["LANGUAGE"]
    keywords = cfg["KEYWORDS"].strip()

    log("=" * 60)
    log("本地爬取任务 / Local crawl run")
    log("=" * 60)
    log(f"日期范围 : {start_s} ~ {end_s}")
    log(f"归档日期 : {label}")
    log(f"分类     : {cfg['CATEGORIES']}")
    log(f"关键词   : {keywords or '(不过滤)'}  (模式 {cfg['KEYWORD_MODE']})")
    log(f"保留数量 : 最新 {cfg['KEEP_LATEST']} 篇（候选池 {cfg['SEARCH_POOL_SIZE']}）")
    log(f"AI 模型  : {cfg['AI_PROVIDER']}/{cfg['TRAPI_MODEL']}  语言 {lang}")
    log(f"推送网页 : {'是（data 分支）' if cfg['PUSH_TO_DATA_BRANCH'] else '否（仅本地）'}")
    log("-" * 60)

    history = load_history()
    print_recent_history(history)
    log("-" * 60)

    # 1) 确定「已发布/已爬过」的数据目录，用于去重
    if cfg["PUSH_TO_DATA_BRANCH"]:
        worktree = ensure_data_worktree(cfg)
        data_pub = worktree / "data"
        assets_pub = worktree / "assets"
    else:
        worktree = None
        data_pub = MAIN_DATA
        assets_pub = REPO_ROOT / "assets"
    data_pub.mkdir(parents=True, exist_ok=True)

    seen_ids = collect_seen_ids(data_pub)
    log(f"已发布论文去重库大小：{len(seen_ids)} 篇")

    # 2) 爬取（把 MAX_PAPERS 放大到候选池大小，等去重后再截取最新 KEEP_LATEST 篇）
    temp_raw_name = f"_run_{label}_raw.jsonl"
    temp_raw_path = MAIN_DATA / temp_raw_name
    if temp_raw_path.exists():
        temp_raw_path.unlink()

    crawl_env = build_subprocess_env(cfg, {
        "CATEGORIES": cfg["CATEGORIES"],
        "KEYWORDS": keywords,
        "KEYWORD_MODE": cfg["KEYWORD_MODE"],
        "START_DATE": start_s,
        "END_DATE": end_s,
        "MAX_PAPERS": cfg["SEARCH_POOL_SIZE"],
        "SEARCH_POOL_SIZE": cfg["SEARCH_POOL_SIZE"],
    })
    log("步骤 1/4：从 arXiv 爬取候选论文 ...")
    run(
        [sys.executable, "-m", "scrapy", "crawl", "arxiv", "-o", f"../data/{temp_raw_name}"],
        cwd=REPO_ROOT / "daily_arxiv",
        env=crawl_env,
    )

    candidates = read_jsonl(temp_raw_path)
    log(f"爬到候选 {len(candidates)} 篇（已按标题关键词/分类过滤，按提交时间从新到旧）")

    # 3) 按 id 去重 + 截取最新 KEEP_LATEST 篇
    new_items = [p for p in candidates if p.get("id", "") not in seen_ids]
    new_items = dedup_keep_order(new_items)[: cfg["KEEP_LATEST"]]
    log(f"去重后新增 {len(new_items)} 篇（跳过 {len(candidates) - len(new_items)} 篇已爬过/超额）")

    run_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not new_items:
        log("没有新的论文需要处理，结束。")
        temp_raw_path.unlink(missing_ok=True)
        history.append({
            "run_time": run_time, "start_date": start_s, "end_date": end_s,
            "label_date": label, "keywords": keywords, "categories": cfg["CATEGORIES"],
            "candidates": len(candidates), "new_count": 0, "pushed": False,
        })
        save_history(history)
        return

    # 4) AI 中文增强（只处理新增的这几篇）
    log(f"步骤 2/4：AI 中文总结（{len(new_items)} 篇）...")
    new_raw_name = f"_run_{label}_new.jsonl"
    new_raw_path = MAIN_DATA / new_raw_name
    write_jsonl(new_raw_path, new_items)

    ai_env = build_subprocess_env(cfg, {
        "AI_PROVIDER": cfg["AI_PROVIDER"],
        "TRAPI_MODEL": cfg["TRAPI_MODEL"],
        "LANGUAGE": lang,
        "ENABLE_SENSITIVE_CHECK": "false",
    })
    run(
        [sys.executable, "enhance.py", "--data", f"../data/{new_raw_name}",
         "--max_workers", str(cfg["AI_MAX_WORKERS"])],
        cwd=REPO_ROOT / "ai",
        env=ai_env,
    )
    new_enh_path = MAIN_DATA / new_raw_name.replace(".jsonl", f"_AI_enhanced_{lang}.jsonl")
    new_enhanced = read_jsonl(new_enh_path)
    if not new_enhanced:
        raise RuntimeError("AI 增强没有产生结果，请检查 az login 状态或模型配置。")

    # 5) 与该归档日期已有的数据合并（新论文放前面）
    log("步骤 3/4：合并到归档文件 ...")
    existing_raw = read_jsonl(data_pub / f"{label}.jsonl")
    existing_enh = read_jsonl(data_pub / f"{label}_AI_enhanced_{lang}.jsonl")

    merged_raw = dedup_keep_order(new_items + existing_raw)
    merged_enh = dedup_keep_order(new_enhanced + existing_enh)

    final_raw_path = MAIN_DATA / f"{label}.jsonl"
    final_enh_path = MAIN_DATA / f"{label}_AI_enhanced_{lang}.jsonl"
    write_jsonl(final_raw_path, merged_raw)
    write_jsonl(final_enh_path, merged_enh)
    log(f"归档 {label}：本次新增 {len(new_items)} 篇，合并后共 {len(merged_enh)} 篇")

    # 6) 可选：生成 Markdown
    if cfg["MAKE_MARKDOWN"]:
        try:
            md_env = build_subprocess_env(cfg, {"CATEGORIES": cfg["CATEGORIES"]})
            run(
                [sys.executable, "convert.py", "--data", f"../data/{label}_AI_enhanced_{lang}.jsonl"],
                cwd=REPO_ROOT / "to_md",
                env=md_env,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"（生成 Markdown 失败，可忽略）: {exc}")

    # 7) 先清理临时文件（避免被写入 file-list）
    for tmp in (temp_raw_path, new_raw_path, new_enh_path):
        Path(tmp).unlink(missing_ok=True)

    # 8) 发布到 data 分支（或仅更新本地 file-list）
    pushed = False
    if cfg["PUSH_TO_DATA_BRANCH"]:
        log("步骤 4/4：推送到 data 分支 ...")
        (data_pub).mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_raw_path, data_pub / final_raw_path.name)
        shutil.copy2(final_enh_path, data_pub / final_enh_path.name)
        md_local = MAIN_DATA / f"{label}.md"
        if md_local.exists():
            shutil.copy2(md_local, data_pub / md_local.name)
        update_file_list(data_pub, assets_pub)

        run(["git", "-C", str(worktree), "add", "-A"], cwd=REPO_ROOT)
        # 有变更才提交
        has_changes = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--staged", "--quiet"], cwd=str(REPO_ROOT)
        ).returncode != 0
        if has_changes:
            msg = f"data: +{len(new_items)} papers for {label} (range {start_s}..{end_s}, kw='{keywords}')"
            run(["git", "-C", str(worktree), "commit", "-m", msg], cwd=REPO_ROOT)
            push_code = run(["git", "-C", str(worktree), "push", cfg["GIT_REMOTE"], cfg["DATA_BRANCH"]],
                            cwd=REPO_ROOT, check=False)
            if push_code != 0:
                log("推送失败，尝试 pull --rebase 后重试 ...")
                run(["git", "-C", str(worktree), "pull", "--rebase", cfg["GIT_REMOTE"], cfg["DATA_BRANCH"]],
                    cwd=REPO_ROOT, check=False)
                push_code = run(["git", "-C", str(worktree), "push", cfg["GIT_REMOTE"], cfg["DATA_BRANCH"]],
                                cwd=REPO_ROOT, check=False)
            pushed = push_code == 0
        else:
            log("data 分支没有变化，无需提交。")
    else:
        update_file_list(data_pub, assets_pub)

    # 9) 记录历史
    history.append({
        "run_time": run_time, "start_date": start_s, "end_date": end_s,
        "label_date": label, "keywords": keywords, "categories": cfg["CATEGORIES"],
        "candidates": len(candidates), "new_count": len(new_items),
        "total_in_label": len(merged_enh), "pushed": pushed,
        "new_ids": [p.get("id", "") for p in new_items],
    })
    save_history(history)

    log("=" * 60)
    log(f"完成！本次新增 {len(new_items)} 篇，归档日期 {label} 现有 {len(merged_enh)} 篇。")
    if cfg["PUSH_TO_DATA_BRANCH"]:
        if pushed:
            log("已推送到 data 分支，网页约 1~5 分钟后更新：")
            log("  https://hj2100334001-ux.github.io/daily-arXiv-ai-enhanced/")
        else:
            log("未成功推送（可能没有变化或推送失败），请查看上面的日志。")
    else:
        log("仅本地生成，未推送到网页（PUSH_TO_DATA_BRANCH=False）。")
    log("运行记录已保存到 crawl_history.json")
    log("=" * 60)


if __name__ == "__main__":
    main()
