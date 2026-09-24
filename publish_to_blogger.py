"""채용 상세 글 자동 발행 (hiring03.ddolbestory.com)
─────────────────────────────────────────────
jobs.json → 아직 글이 없는 공고를 골라 → 템플릿으로 글 생성 → Blogger 발행 → job_posts.json 매핑 저장
- 한 번 실행에 평균 PUBLISH_PER_RUN개 발행 (기본 5개 ±2 랜덤, 4시간마다 → 하루 약 30개)
- 랜덤 발행: 시작 전 0~30분 대기 + 글 사이 1~5분 간격 (몰아치기 방지)
- 우선순위: ① 쓰레드 글감 후보(정규직·무기계약직·채용형인턴 + 신입 + 의사직 제외)
            ② 점수순: 모집인원 + 브랜드 + 마감임박 + 학력무관 + 전국 + 새 공고 가산
- 마감 2일 이내 공고는 건너뜀 / 마감된 글은 삭제하지 않음(축적)
- 퍼머링크: 영문 제목으로 먼저 발행해 주소 고정 → 한글 제목으로 수정
- 나라일터(GJ-) 공고: getItem API로 상세 정보 보충 후 발행

로컬 미리보기: python publish_to_blogger.py --preview 3   (API 없이 preview/ 폴더에 HTML 생성)
필요한 Secrets: BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID, GOJOBS_API_KEY
"""
import json, os, sys, time, re, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from post_template import build_html, make_title, make_labels, days_left, clean_inst, ncs_list, hire_list, regions, KST
import random

JOBS_FILE, MAPPING_FILE = "jobs.json", "job_posts.json"
PER_RUN = int(os.environ.get("PUBLISH_PER_RUN", "5"))   # 1회 평균 발행 개수 (실제는 ±2 랜덤)
MIN_DAYS_LEFT = 2
NEW_WITHIN_DAYS = 2   # 접수 시작 2일 이내 = 새 공고
JITTER = os.environ.get("PUBLISH_JITTER", "1") != "0"    # 랜덤 발행 (끄려면 0)
START_WAIT_MAX = 30 * 60      # 시작 전 0~30분 랜덤 대기
GAP_MIN, GAP_MAX = 60, 300    # 글 사이 1~5분 랜덤 간격
DOCTOR_WORDS = ["전임의", "전공의", "레지던트", "임상강사", "의사직", "의무직", "촉탁의"]
GOJOBS_KEY = os.environ.get("GOJOBS_API_KEY", "").strip()

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

# ───────── 나라일터(GJ-) 공고 상세 보충 ─────────
GOJOBS_DETAIL_URL = "https://apis.data.go.kr/1760000/PblJobService/getItem"

def is_gojobs(job):
    """나라일터 출처 공고인지 확인"""
    return str(job.get("recrutPblntSn", "")).startswith("GJ-")

def gojobs_idx(job):
    """GJ-12345 → 12345"""
    return str(job.get("recrutPblntSn", "")).replace("GJ-", "")

def enrich_gojobs(job):
    """나라일터 getItem API로 상세 정보(contents) 가져와서 빈 필드 보충"""
    if not is_gojobs(job) or not GOJOBS_KEY:
        return job

    idx = gojobs_idx(job)
    try:
        q = urllib.parse.urlencode({"serviceKey": GOJOBS_KEY, "idx": idx}, safe="%")
        req = urllib.request.Request(f"{GOJOBS_DETAIL_URL}?{q}",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_data = r.read().decode("utf-8")
        root = ET.fromstring(xml_data)
        item = root.find(".//item")
        if item is None:
            print(f"  [나라일터] idx={idx} 상세 없음")
            return job

        contents = item.findtext("contents") or ""
        areaname = item.findtext("areaname") or ""
        begindate = item.findtext("begindate") or ""
        link01 = item.findtext("link01") or ""

        # 지역 보충
        if not job.get("workRgnNmLst") and areaname:
            job["workRgnNmLst"] = areaname

        # 접수시작일 보충
        if not job.get("pbancBgngYmd") and begindate:
            job["pbancBgngYmd"] = begindate

        # 원문 링크 보충 (첨부파일 링크가 있으면)
        if link01 and job.get("srcUrl", "").endswith("gojobs.go.kr/"):
            job["srcUrl"] = link01

        # contents에서 핵심 정보 파싱
        parsed = parse_contents(contents)
        if parsed.get("hire_type") and not job.get("hireTypeNmLst"):
            job["hireTypeNmLst"] = parsed["hire_type"]
        if parsed.get("headcount") and not job.get("recrutNope"):
            job["recrutNope"] = parsed["headcount"]
        if parsed.get("edu") and not job.get("acbgCondNmLst"):
            job["acbgCondNmLst"] = parsed["edu"]
        if parsed.get("career") and not job.get("recrutSeNm"):
            job["recrutSeNm"] = parsed["career"]

        # 원본 contents 저장 (템플릿에서 활용 가능)
        job["_gojobs_contents"] = contents

        print(f"  [나라일터] 보충 완료: {job['instNm']} | 인원={job.get('recrutNope')} | 고용={job.get('hireTypeNmLst')} | 지역={areaname}")
        return job

    except Exception as e:
        print(f"  [나라일터] idx={idx} 보충 실패: {e}")
        return job


def parse_contents(text):
    """공고 전문 텍스트에서 고용형태·인원·학력·경력 추출"""
    result = {}

    # 고용형태 추출
    hire_keywords = ["정규직", "무기계약직", "계약직", "기간제", "임기제", "공무직", "인턴"]
    found_hires = [k for k in hire_keywords if k in text]
    if found_hires:
        result["hire_type"] = ",".join(found_hires)

    # 모집인원 추출 (예: "총 6명", "00명", "0명 채용", "채용인원 : 0명")
    m = re.search(r'(?:총\s*)?(\d{1,4})\s*명', text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 5000:
            result["headcount"] = n

    # 학력 추출
    edu_keywords = ["학력무관", "학력제한없음", "고졸", "대졸", "석사", "박사", "전문대졸"]
    found_edu = [k for k in edu_keywords if k in text]
    if found_edu:
        result["edu"] = ",".join(found_edu)
    elif "학력" in text and ("제한" in text and "없" in text):
        result["edu"] = "학력무관"

    # 경력 추출
    if "신입" in text and "경력" in text:
        result["career"] = "신입+경력"
    elif "경력무관" in text or "경력 무관" in text:
        result["career"] = "신입+경력"
    elif "신입" in text:
        result["career"] = "신입"

    return result


def slug_for(job):
    sn = str(job.get("recrutPblntSn", ""))
    # 나라일터 공고: gj-{idx} 형식
    if sn.startswith("GJ-"):
        idx = sn.replace("GJ-", "")
        name = clean_inst(job["instNm"])
        for k, v in sorted(ABBR.items(), key=lambda kv: -len(kv[0])):
            if k in name:
                return f"{v}-gj{idx}"
        return f"gj-{idx}"
    # 잡알리오 공고: 기존 로직
    name = clean_inst(job["instNm"])
    for k, v in sorted(ABBR.items(), key=lambda kv: -len(kv[0])):
        if k in name:
            return f"{v}-{sn}"
    return f"job-{sn}"

def thread_eligible(job, now=None):
    """쓰레드 글감 조건 (지침서 4장): 정규직·무기계약직·채용형인턴 + 신입 가능 + 의사직 제외"""
    hl = hire_list(job)
    if not any(h in ("정규직", "무기계약직", "청년인턴(채용형)") for h in hl):
        # 나라일터 공고는 고용형태가 비어있을 수 있으므로 일단 통과시킴
        if not is_gojobs(job):
            return False
    if not is_gojobs(job) and "신입" not in (job.get("recrutSeNm") or ""):
        return False
    title = job.get("recrutPbancTtl") or ""
    if any(w in title for w in DOCTOR_WORDS):
        return False
    return True

def score(job, now=None):
    """트래픽이 몰릴 공고일수록 높은 점수 (지침서 4장 스코어링과 같은 기준)"""
    now = now or datetime.now(KST)
    s = min(job.get("recrutNope") or 0, 100)                      # 모집인원 (최대 100점)
    name = clean_inst(job["instNm"])
    if any(k in name for k in ABBR): s += 20                      # 브랜드 파워
    dl = days_left(job, now)
    if 1 <= dl <= 10: s += 15                                     # 마감 임박
    elif 11 <= dl <= 15: s += 5
    if "학력무관" in (job.get("acbgCondNmLst") or ""): s += 5      # 누구나 지원 가능
    if len(regions(job)) >= 10: s += 5                            # 전국 모집
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
    # 나라일터 공고면 발행 직전에 상세 정보 보충
    if is_gojobs(job):
        job = enrich_gojobs(job)

    slug = slug_for(job)
    src = job.get("srcUrl") or "https://www.gojobs.go.kr"
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
    # 1순위 쓰레드 글감 후보(정규직·신입 등) → 그 안에서 점수순 (새 공고는 +15점 가산)
    todo.sort(key=lambda j: (not thread_eligible(j, now), -(score(j, now) + (15 if is_new(j, now) else 0))))
    n_hot = sum(1 for j in todo if thread_eligible(j, now))
    n_new = sum(1 for j in todo if is_new(j, now))
    return todo, n_hot, n_new

def main():
    now = datetime.now(KST)
    jobs = json.load(open(JOBS_FILE, encoding="utf-8"))["result"]
    mapping = json.load(open(MAPPING_FILE, encoding="utf-8")) if os.path.exists(MAPPING_FILE) else {}
    queue, n_hot, n_new = pick_queue(jobs, mapping, now)

    if "--preview" in sys.argv:
        k = int(sys.argv[sys.argv.index("--preview") + 1]) if len(sys.argv) > sys.argv.index("--preview") + 1 else 3
        os.makedirs("preview", exist_ok=True)
        for j in queue[:k]:
            # 미리보기에서도 나라일터 보충 실행
            if is_gojobs(j):
                j = enrich_gojobs(j)
            path = f"preview/{slug_for(j)}.html"
            open(path, "w", encoding="utf-8").write(build_html(j, j.get("srcUrl", ""), related_jobs(j, jobs, now)))
            print(f"{path}\n  제목: {make_title(j)}\n  라벨: {make_labels(j)}")
        print(f"대기열 {len(queue)}개 (쓰레드 후보 {n_hot}개 / 새 공고 {n_new}개)")
        return

    count = max(1, PER_RUN + random.randint(-2, 2)) if JITTER else PER_RUN
    print(f"[대기열] {len(queue)}개 (쓰레드 후보 {n_hot}개 / 새 공고 {n_new}개) → 이번 실행 {min(count, len(queue))}개 발행")
    if not queue:
        return
    need = ["BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN", "BLOGGER_BLOG_ID"]
    if not all(os.environ.get(k) for k in need):
        print("[건너뜀] Blogger Secrets가 아직 없어요 → 채용공고 수집·배포만 진행")
        return
    if JITTER:
        wait = random.randint(0, START_WAIT_MAX)
        print(f"[랜덤 대기] {wait // 60}분 {wait % 60}초 후 시작")
        time.sleep(wait)
    token = access_token()
    done = 0
    try:
        for i, job in enumerate(queue[:count]):
            if i and JITTER:
                time.sleep(random.randint(GAP_MIN, GAP_MAX))
            info = publish(job, jobs, now, token)
            if info:
                mapping[str(job["recrutPblntSn"])] = info
                done += 1
                src_tag = " [나라일터]" if is_gojobs(job) else ""
                print(f"[발행] {datetime.now(KST).strftime('%H:%M:%S')} {info['url']}  |  {info['title'][:40]}{src_tag}")
            if not JITTER:
                time.sleep(3)
    except RuntimeError as e:
        print(f"[중단] {e}")
    finally:
        json.dump(mapping, open(MAPPING_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[완료] 이번 {done}개 발행 / 누적 {len(mapping)}개")

if __name__ == "__main__":
    main()
