"""jobs.json · job_posts.json 을 저장소에 안전하게 저장 (update.yml '저장소에 백업' 단계)
[2026-10-02] 실행 중에 다른 커밋(수동 업로드·다른 워크플로)이 들어와도 충돌 없이 저장
- jobs.json      : 이번 실행 결과로 저장
- job_posts.json : 저장소 쪽 기록 + 이번에 새로 발행한 기록을 합침 (어느 쪽 기록도 잃지 않음)
[2026-10-08] 수동 공고 발행(publish_manual.py)이 바꾼 공고번호(.manual_changed.json)는 이번 실행 기록을 우선
             (직접 쓴 본문 연결·Claude 글 다시 쓰기가 저장소의 예전 기록에 덮이지 않게)
"""
import json, subprocess, sys, time
from datetime import datetime, timezone

def sh(*cmd, check=True):
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, capture_output=True)

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

ours_jobs = open("jobs.json", encoding="utf-8").read()
ours_posts = load("job_posts.json", {})
ours_changed = set(load(".manual_changed.json", []))

sh("git", "config", "user.name", "job-compass-bot")
sh("git", "config", "user.email", "actions@users.noreply.github.com")

for attempt in range(1, 6):
    sh("git", "fetch", "origin", "main")
    sh("git", "reset", "--hard", "origin/main")          # 저장소 최신 상태로 맞춘 뒤
    remote_posts = load("job_posts.json", {})
    merged = {**ours_posts, **remote_posts}               # 같은 공고는 저장소 쪽(보강 등 최신 수정) 우선
    for k in ours_changed:                                # 단, 수동 공고 발행이 이번에 바꾼 공고는 이번 기록 우선
        if k in ours_posts:
            merged[k] = ours_posts[k]
    added = len(set(merged) - set(remote_posts))
    with open("jobs.json", "w", encoding="utf-8") as f:
        f.write(ours_jobs)
    with open("job_posts.json", "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    sh("git", "add", "jobs.json", "job_posts.json")
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("변경 없음 → 저장 생략")
        sys.exit(0)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    sh("git", "commit", "-m", f"채용공고 업데이트 {stamp} UTC")
    r = sh("git", "push", "origin", "HEAD:main", check=False)
    if r.returncode == 0:
        print(f"저장 완료 (발행 기록 {added}개 추가, 시도 {attempt}회)")
        sys.exit(0)
    print(f"push 실패 → {attempt}번째 재시도: {r.stderr.strip()[:200]}")
    time.sleep(5 * attempt)

sys.exit("5번 모두 저장 실패")
