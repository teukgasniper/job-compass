"""hiring03 글별 조회수 수집 (GA4) + 자동 보강 대상 선정
─────────────────────────────────────────────
GA4 Data API → hiring03.ddolbestory.com 페이지 경로별 누적 조회수
→ 주소 끝 공고번호(-305277.html)로 묶어서 views.json 저장
→ 조건에 맞는 공고번호를 골라 GITHUB_OUTPUT 의 ids 로 넘김 (enhance_posts.py 입력)

선정 조건
  ① 조회수 AUTO_ENHANCE_MIN_VIEWS 이상 (기본 50)
  ② jobs.json 에 진행 중 + job_posts.json 에 본문 글 있음
  ③ 아직 보강 안 됨 (enhanced_posts.json 에 없음)
  ④ 마감까지 2일 이상 남음 (곧 닫힐 글은 보강해도 효과 없음)
  ⑤ 최근 3일 안에 시도했다가 실패한 공고는 건너뜀 (enhance_tried.json)
  [2026-10-08] 글 주소 → 공고번호를 job_posts.json 기준으로 찾음 (GJ-·WK-·CE- 공고가 숫자만 남아 매칭 안 되던 문제)
  → 조회수 높은 순으로 AUTO_ENHANCE_PER_RUN 개 (기본 3)

필요한 값
  Secrets  : BLOGGER_CLIENT_ID, GA4_CLIENT_SECRET, GA4_REFRESH_TOKEN
  Variables: GA4_PROPERTY_ID
"""
import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HOST = "hiring03.ddolbestory.com"
VIEWS_FILE, TRIED_FILE = "views.json", "enhance_tried.json"
JOBS_FILE, MAPPING_FILE, STATE_FILE = "jobs.json", "job_posts.json", "enhanced_posts.json"

MIN_VIEWS = int(os.environ.get("AUTO_ENHANCE_MIN_VIEWS") or 50)
PER_RUN = int(os.environ.get("AUTO_ENHANCE_PER_RUN") or 3)
MIN_DAYS_LEFT = 2
RETRY_DAYS = 3
DRY = os.environ.get("ENHANCE_DRY_RUN") == "true"


def post_json(url, data, headers=None, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def ga4_token():
    need = ["BLOGGER_CLIENT_ID", "GA4_CLIENT_SECRET", "GA4_REFRESH_TOKEN", "GA4_PROPERTY_ID"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        sys.exit(f"GA4 설정값 없음: {', '.join(miss)}")
    return post_json("https://oauth2.googleapis.com/token", {
        "client_id": os.environ["BLOGGER_CLIENT_ID"],
        "client_secret": os.environ["GA4_CLIENT_SECRET"],
        "refresh_token": os.environ["GA4_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, form=True)["access_token"]


def path_index():
    """job_posts.json의 글 주소 경로 → 공고번호 (예: /2026/10/gj-305182.html → GJ-305182)"""
    idx = {}
    for sn, info in load(MAPPING_FILE, {}).items():
        path = urllib.parse.urlparse((info or {}).get("url", "")).path
        if path:
            idx[path] = str(sn)
    return idx


def fetch_views():
    """{공고번호: 누적 조회수} — 최근 90일"""
    by_path = path_index()
    token = ga4_token()
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{os.environ['GA4_PROPERTY_ID']}:runReport"
    views, offset = {}, 0
    while True:
        res = post_json(url, {
            "dateRanges": [{"startDate": "90daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}],
            "dimensionFilter": {"filter": {"fieldName": "hostName", "stringFilter": {"value": HOST}}},
            "limit": 10000, "offset": offset,
        }, headers={"Authorization": f"Bearer {token}"})
        rows = res.get("rows", [])
        for r in rows:
            path = r["dimensionValues"][0]["value"].split("?")[0].split("#")[0]
            sn = by_path.get(path) or by_path.get(re.sub(r"_\d+(\.html)$", r"\1", path))   # _1 붙은 주소도
            if not sn and not re.search(r"/(gj|wk|ce|mn)-", path):            # 매핑에 없는 예전 글: 알리오 숫자 번호만
                m = re.search(r"-(\d{5,7})(?:_\d+)?\.html$", path)
                sn = m.group(1) if m else None
            if sn:
                views[sn] = views.get(sn, 0) + int(r["metricValues"][0]["value"])
        offset += len(rows)
        if not rows or offset >= int(res.get("rowCount", 0)):
            break
    return views


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def days_left(end_ymd, today):
    try:
        return (datetime.strptime(str(end_ymd), "%Y%m%d").date() - today).days
    except Exception:
        return -1


def main():
    now = datetime.now(KST)
    today = now.date()
    views = fetch_views()
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "views": views},
              open(VIEWS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"조회수 수집: hiring03 글 {len(views)}개 (총 {sum(views.values()):,}회)")

    jobs = {str(j["recrutPblntSn"]): j for j in load(JOBS_FILE, {"result": []})["result"]}
    mapping = load(MAPPING_FILE, {})
    state = load(STATE_FILE, {})
    tried = load(TRIED_FILE, {})

    cands, skipped = [], {"보강완료": 0, "마감임박": 0, "마감/본문없음": 0, "최근실패": 0}
    for sn, v in views.items():
        if v < MIN_VIEWS:
            continue
        if sn in state:
            skipped["보강완료"] += 1; continue
        if sn.startswith("MN-"):                    # [2026-10-08] 수동 공고 글은 보강 안 함
            continue
        if sn not in jobs or sn not in mapping:
            skipped["마감/본문없음"] += 1; continue
        if days_left(jobs[sn].get("pbancEndYmd"), today) < MIN_DAYS_LEFT:
            skipped["마감임박"] += 1; continue
        t = tried.get(sn)
        if t and (today - datetime.strptime(t, "%Y-%m-%d").date()).days < RETRY_DAYS:
            skipped["최근실패"] += 1; continue
        cands.append((v, sn))

    cands.sort(reverse=True)
    pick = [sn for _, sn in cands[:PER_RUN]]
    print(f"{MIN_VIEWS}회 이상 보강 후보 {len(cands)}개 / 제외 {skipped}")
    for v, sn in cands[:PER_RUN]:
        print(f"  → {sn} {jobs[sn]['instNm']} ({v}회, D-{days_left(jobs[sn]['pbancEndYmd'], today)})")
    if len(cands) > PER_RUN:
        print(f"  (나머지 {len(cands) - PER_RUN}개는 다음 회차)")

    # 시도 기록 — 보강에 성공하면 enhanced_posts.json 에 들어가서 다음부터 자동 제외됨
    if pick and not DRY:
        for sn in pick:
            tried[sn] = today.isoformat()
        json.dump(tried, open(TRIED_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"ids={','.join(pick)}\n")


if __name__ == "__main__":
    main()
