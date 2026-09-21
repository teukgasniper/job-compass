"""잡알리오 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
1순위: 공공데이터포털 직접 연결 / 2순위: 구글 Apps Script 중계
키·주소·암호는 GitHub Secrets에서만 읽습니다. 코드에 적지 마세요."""
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

slim = [{k: x.get(k) for k in KEEP} for x in items if x.get("ongoingYn") == "Y"]
if len(slim) < 50:
    sys.exit(f"수집 건수가 너무 적음({len(slim)}건) → 기존 데이터 유지")

kst = datetime.now(timezone(timedelta(hours=9)))
out = {"generated_at": kst.strftime("%Y-%m-%d %H:%M"), "count": len(slim), "result": slim}
with open("jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"완료: {len(slim)}건 저장 ({out['generated_at']} KST)")
