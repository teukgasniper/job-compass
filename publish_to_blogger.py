"""채용 상세 글 자동 발행 (hiring03.ddolbestory.com)
─────────────────────────────────────────────
jobs.json → 아직 글이 없는 공고를 골라 → 템플릿으로 글 생성 → Blogger 발행 → job_posts.json 매핑 저장
- 한 번 실행에 PUBLISH_PER_RUN개만 발행 (기본 5개, 4시간마다 → 하루 30개)
- 새 공고 먼저, 남는 자리에 기존 공고를 추천 점수순으로
- 마감 2일 이내 공고는 건너뜀 / 마감된 글은 삭제하지 않음(축적)
- 퍼머링크: 영문 제목으로 먼저 발행해 주소 고정 → 한글 제목으로 수정
로컬 미리보기: python publish_to_blogger.py --preview 3   (API 없이 preview/ 폴더에 HTML 생성)
필요한 Secrets: BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID
"""
import json, os, sys, time, re, urllib.request, urllib.parse, urllib.error
from datetime import datetime
from post_template import build_html, make_title, make_labels, days_left, clean_inst, ncs_list, hire_list, KST

JOBS_FILE, MAPPING_FILE = "jobs.json", "job_posts.json"
PER_RUN = int(os.environ.get("PUBLISH_PER_RUN", "5"))
MIN_DAYS_LEFT = 2
NEW_WITHIN_DAYS = 2   # 접수 시작 2일 이내 = 새 공고

# 주요 기관 영문 약칭 (퍼머링크용) — 없으면 job-번호
ABBR = {
    "한국전력공사": "kepco", "한전KDN": "kdn", "한전KPS": "kps", "국민건강보험공단": "nhis",
    "한국공항공사": "kac", "인천국제공항공사": "iiac", "한국토지주택공사": "lh", "한국도로공사": "ex",
    "한국철도공사": "korail", "한국수자원공사": "kwater", "한국가스공사": "kogas", "한국가스기술공사": "kogas-tech",
    "한국남부발전": "kospo", "한국중부발전": "komipo", "한국서부발전": "kowepo", "한국남동발전": "koen",
    "한국동서발전": "ewp", "한국수력원자력": "khnp", "대한무역투자진흥공사": "kotra", "국민연금공단": "nps",
    "근로복지공단": "comwel", "한국산업인력공단": "hrdkorea", "건강보험심사평가원": "hira", "한국자산관리공사": "kamco",
    "예금보험공사": "kdic", "한국주택금융공사": "hf", "신용보증기금": "kodit", "기술보증기금": "kibo",
    "중소벤처기업진흥공단": "kosmes", "한국관광공사": "kto", "국립공원공단": "knps", "대한법률구조공단": "klac",
    "한국농어촌공사": "ekr", "한국환경공단": "keco", "한국교통안전공단": "kotsa", "한국산업은행": "kdb",
    "한국수출입은행": "koreaexim", "한국전기안전공사": "kesco", "한국지역난방공사": "kdhc", "한국조폐공사": "komsco",
    "한국마사회": "kra", "한국인터넷진흥원": "kisa", "한국장학재단": "kosaf", "한국부동산원": "reb",
    "공무원연금공단": "geps", "도로교통공단": "koroad", "한국소비자원": "kca", "한국원자력연구원": "kaeri",
    "한국전자통신연구원": "etri", "서울대학교병원": "snuh", "분당서울대학교병원": "snubh", "국립암센터": "ncc",
    "국립중앙의료원": "nmc", "대한적십자사": "redcross", "한국보훈복지의료공단": "bohun", "한국장애인고용공단": "kead",
    "한국국토정보공사": "lx", "주택관리공단": "khmc", "한국원자력의학원": "kirams", "기초과학연구원": "ibs",
    "한국개발연구원": "kdi", "해양환경공단": "koem", "한국폴리텍": "kopo",
}

def slug_for(job):
    name = clean_inst(job["instNm"])
    for k, v in sorted(ABBR.items(), key=lambda kv: -len(kv[0])):
        if k in name:
            return f"{v}-{job['recrutPblntSn']}"
    return f"job-{job['recrutPblntSn']}"

def score(job):
    s = 0
    name = clean_inst(job["instNm"])
    if any(k in name for k in ABBR): s += 30                     # 브랜드
    hl = hire_list(job)
    if "정규직" in hl: s += 25
    if "무기계약직" in hl: s += 12
    if "신입" in (job.get("recrutSeNm") or ""): s += 10
    n = job.get("recrutNope") or 0
    s += min(n, 100) * 0.3                                       # 대규모 채용
    return s

def is_new(job, now):
    try:
        return (now.date() - datetime.strptime(job["pbancBgngYmd"], "%Y%m%d").date()).days <= NEW_WITHIN_DAYS
    except Exception:
        return False

def related_jobs(job, jobs, now):
    main = (ncs_list(job) or [""])[0]
    cand = [j for j in jobs if j["recrutPblntSn"] != job["recrutPblntSn"]
            and main and main in ncs_list(j) and days_left(j, now) >= 1
            and clean_inst(j["instNm"]) != clean_inst(job["instNm"])]
    cand.sort(key=lambda j: -score(j))
    return cand[:3]

# ───────── Blogger API ─────────
def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["BLOGGER_CLIENT_ID"], "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]

def api(method, path, token, body=None):
    blog = os.environ["BLOGGER_BLOG_ID"]
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog}/{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:300]
        print(f"[API 오류] {e.code} {msg}")
        if e.code in (403, 429):
            raise RuntimeError("발행 한도/권한 문제 → 이번 실행 중단")
        return None

def publish(job, jobs, now, token):
    slug = slug_for(job)
    src = job.get("srcUrl") or "https://job.alio.go.kr"
    html = build_html(job, src, related_jobs(job, jobs, now))
    # 1) 영문 제목으로 발행 → 주소 고정 (예: /2026/09/kotra-305112.html)
    post = api("POST", "posts?isDraft=false", token,
               {"kind": "blogger#post", "title": slug.replace("-", " "), "content": html, "labels": make_labels(job)})
    if not post or not post.get("id"):
        return None
    # 2) 한글 제목으로 수정 (주소는 그대로 유지)
    title = make_title(job)
    api("PATCH", f"posts/{post['id']}", token, {"title": title})
    return {"postId": post["id"], "url": post.get("url", ""), "title": title,
            "instNm": job["instNm"], "slug": slug, "published": now.strftime("%Y-%m-%d %H:%M")}

# ───────── 실행 ─────────
def pick_queue(jobs, mapping, now):
    todo = [j for j in jobs if str(j["recrutPblntSn"]) not in mapping and days_left(j, now) >= MIN_DAYS_LEFT]
    new = sorted([j for j in todo if is_new(j, now)], key=lambda j: -score(j))
    old = sorted([j for j in todo if not is_new(j, now)], key=lambda j: -score(j))
    return new + old, len(new), len(old)

def main():
    now = datetime.now(KST)
    jobs = json.load(open(JOBS_FILE, encoding="utf-8"))["result"]
    mapping = json.load(open(MAPPING_FILE, encoding="utf-8")) if os.path.exists(MAPPING_FILE) else {}
    queue, n_new, n_old = pick_queue(jobs, mapping, now)

    if "--preview" in sys.argv:
        k = int(sys.argv[sys.argv.index("--preview") + 1]) if len(sys.argv) > sys.argv.index("--preview") + 1 else 3
        os.makedirs("preview", exist_ok=True)
        for j in queue[:k]:
            path = f"preview/{slug_for(j)}.html"
            open(path, "w", encoding="utf-8").write(build_html(j, j.get("srcUrl", ""), related_jobs(j, jobs, now)))
            print(f"{path}\n  제목: {make_title(j)}\n  라벨: {make_labels(j)}")
        print(f"대기열: 새 공고 {n_new}개 / 기존 공고 {n_old}개")
        return

    print(f"[대기열] 새 공고 {n_new}개 / 기존 공고 {n_old}개 / 이번 실행 {min(PER_RUN, len(queue))}개 발행")
    if not queue:
        return
    need = ["BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN", "BLOGGER_BLOG_ID"]
    if not all(os.environ.get(k) for k in need):
        print("[건너뜀] Blogger Secrets가 아직 없어요 → 채용공고 수집·배포만 진행")
        return
    token = access_token()
    done = 0
    try:
        for job in queue[:PER_RUN]:
            info = publish(job, jobs, now, token)
            if info:
                mapping[str(job["recrutPblntSn"])] = info
                done += 1
                print(f"[발행] {info['url']}  |  {info['title'][:40]}")
            time.sleep(3)
    except RuntimeError as e:
        print(f"[중단] {e}")
    finally:
        json.dump(mapping, open(MAPPING_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[완료] 이번 {done}개 발행 / 누적 {len(mapping)}개")

if __name__ == "__main__":
    main()
