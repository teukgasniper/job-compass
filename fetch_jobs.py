"""잡알리오 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
1순위: 공공데이터포털 직접 연결 / 2순위: 구글 Apps Script 중계
키·주소·암호는 GitHub Secrets에서만 읽습니다. 코드에 적지 마세요.

[2026-09-23 수정] 의사직(전문의·전임의·레지던트 등) 공고 수집 제외
 - 간호사·임상병리사·약사·방사선사 등 다른 보건의료 면허직은 정상 수집됩니다.
"""
import json, os, sys, time, socket, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

KEY = os.environ.get("ALIO_API_KEY", "").strip()
RELAY_URL = os.environ.get("RELAY_URL", "").strip()
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "").strip()
if not KEY and not RELAY_URL:
    sys.exit("ALIO_API_KEY 또는 RELAY_URL 이 필요합니다.")

BASES = ["http://apis.data.go.kr/1051000/recruitment/list",
         "https://apis.data.go.kr/1051000/recruitment/list"]
KEEP = ["recrutPblntSn","instNm","recrutPbancTtl","hireTypeNmLst","workRgnNmLst","recrutSeNm",
        "recrutNope","pbancBgngYmd","pbancEndYmd","srcUrl","acbgCondNmLst","replmprYn",
        "ongoingYn","ncsCdNmLst"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json"}

# ─────────────────────────────────────────────────────────────
# 의사직 제외 필터
# ─────────────────────────────────────────────────────────────
# 확실한 의사직 표현 (이 중 하나라도 있으면 제외)
DOCTOR_KEYWORDS = [
    "전문의", "전임의", "레지던트", "전공의", "수련의",
    "공중보건의", "공보의", "의사직", "진료의사", "촉탁의",
    "임상강사", "봉직의", "임상교수", "진료과장", "의무직",
    "임상스텝", "임상스태프", "펠로우",
]

# 의사직이 아닌데 '의사'라는 글자가 섞일 수 있는 직종 (오탐 방지용 예외)
SAFE_KEYWORDS = [
    "간호", "임상병리", "방사선", "물리치료", "작업치료",
    "치과위생", "응급구조", "약사", "영양사", "의무기록",
    "보건직", "의사소통",
]


def _as_text(value):
    """리스트/문자열/None 을 모두 안전하게 문자열로 변환"""
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value or "")


def is_doctor_post(x):
    """의사직 공고면 True (→ 수집 제외)"""
    text = " ".join([
        _as_text(x.get("recrutPbancTtl")),   # 공고명
        _as_text(x.get("ncsCdNmLst")),       # NCS 직무분야
    ])

    # 1) 확실한 의사직 키워드가 있으면 제외
    if any(k in text for k in DOCTOR_KEYWORDS):
        return True

    # 2) '의사' 라는 단어가 있는 경우 → 안전 직종 키워드가 없을 때만 제외
    if "의사" in text and not any(s in text for s in SAFE_KEYWORDS):
        return True

    return False


def get_json(url, timeout):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def direct_open():
    """공공데이터포털에 직접 연결 가능한지 빠르게 확인 (막혀 있으면 시간 낭비 없이 중계로)"""
    for port in (80, 443):
        try:
            socket.create_connection(("apis.data.go.kr", port), timeout=8).close()
            print(f"[진단] 직접 연결 가능 (포트 {port})")
            return True
        except Exception as e:
            print(f"[진단] 직접 연결 불가 (포트 {port}): {e}")
    return False


USE_DIRECT = bool(KEY) and direct_open()


def fetch(page):
    if USE_DIRECT:
        q = urllib.parse.urlencode({"serviceKey": KEY, "numOfRows": 1000, "pageNo": page,
                                    "resultType": "json", "ongoingYn": "Y"}, safe="%")
        for base in BASES:
            try:
                data = get_json(f"{base}?{q}", 25)
                print(f"page {page} 직접 수집 성공")
                return data
            except Exception as e:
                print(f"page {page} 직접({base.split(':')[0]}) 실패: {e}")
    if RELAY_URL:
        q = urllib.parse.urlencode({"token": RELAY_TOKEN, "page": page})
        for attempt in range(3):
            try:
                data = get_json(f"{RELAY_URL}?{q}", 90)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                print(f"page {page} 구글 중계 수집 성공")
                return data
            except Exception as e:
                print(f"page {page} 구글 중계 시도 {attempt+1} 실패: {e}")
                time.sleep(5)
    raise RuntimeError(f"page {page} 수집 실패 (직접·중계 모두 실패)")


items, page = [], 1
while True:
    data = fetch(page)
    batch = data.get("result") or []
    items += batch
    total = int(data.get("totalCount") or 0)
    if len(batch) < 1000 or len(items) >= total or page >= 5:
        break
    page += 1

# 진행 중 공고만 남기고, 의사직 공고는 제외
ongoing = [x for x in items if x.get("ongoingYn") == "Y"]
doctor_posts = [x for x in ongoing if is_doctor_post(x)]
slim = [{k: x.get(k) for k in KEEP} for x in ongoing if not is_doctor_post(x)]

if doctor_posts:
    print(f"[필터] 의사직 공고 {len(doctor_posts)}건 제외")
    for x in doctor_posts[:10]:
        print(f"  - {x.get('instNm')} | {x.get('recrutPbancTtl')}")
    if len(doctor_posts) > 10:
        print(f"  ... 외 {len(doctor_posts) - 10}건")

if len(slim) < 50:
    sys.exit(f"수집 건수가 너무 적음({len(slim)}건) → 기존 데이터 유지")

kst = datetime.now(timezone(timedelta(hours=9)))
out = {"generated_at": kst.strftime("%Y-%m-%d %H:%M"), "count": len(slim), "result": slim}
with open("jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"완료: {len(slim)}건 저장 ({out['generated_at']} KST)")
