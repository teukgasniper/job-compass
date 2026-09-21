"""잡알리오 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
API 키는 GitHub Secrets의 ALIO_API_KEY 에서만 읽습니다. 코드에 키를 적지 마세요."""
import json, os, sys, time, socket, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

KEY = os.environ.get("ALIO_API_KEY", "").strip()
if not KEY:
    sys.exit("ALIO_API_KEY 가 설정되지 않았습니다.")

# 해외 서버에서 https가 막히는 경우가 있어 여러 경로를 차례로 시도
BASES = [
    "http://apis.data.go.kr/1051000/recruitment/list",
    "https://apis.data.go.kr/1051000/recruitment/list",
]
KEEP = ["recrutPblntSn","instNm","recrutPbancTtl","hireTypeNmLst","workRgnNmLst","recrutSeNm",
        "recrutNope","pbancBgngYmd","pbancEndYmd","srcUrl","acbgCondNmLst","replmprYn",
        "ongoingYn","ncsCdNmLst"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json"}

def diagnose():
    """접속 진단: 어느 경로가 열려있는지 로그에 남김"""
    for host, port in [("apis.data.go.kr", 80), ("apis.data.go.kr", 443)]:
        try:
            t = time.time()
            socket.create_connection((host, port), timeout=10).close()
            print(f"[진단] {host}:{port} 연결 OK ({time.time()-t:.1f}초)")
        except Exception as e:
            print(f"[진단] {host}:{port} 연결 실패: {e}")

working_base = None
def fetch(page):
    global working_base
    q = urllib.parse.urlencode({"serviceKey": KEY, "numOfRows": 1000, "pageNo": page,
                                "resultType": "json", "ongoingYn": "Y"}, safe="%")
    bases = [working_base] if working_base else BASES
    for base in bases:
        for attempt in range(2):
            try:
                req = urllib.request.Request(f"{base}?{q}", headers=HEADERS)
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.loads(r.read().decode("utf-8"))
                working_base = base
                print(f"page {page} 수집 성공 ({base.split(':')[0]})")
                return data
            except Exception as e:
                print(f"page {page} {base.split(':')[0]} 시도 {attempt+1} 실패: {e}")
                time.sleep(3)
    raise RuntimeError(f"page {page} 수집 실패 (모든 경로 실패)")

diagnose()
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
    sys.exit(f"수집 건수가 너무 적음({len(slim)}건) → 기존 jobs.json 유지")

kst = datetime.now(timezone(timedelta(hours=9)))
out = {"generated_at": kst.strftime("%Y-%m-%d %H:%M"), "count": len(slim), "result": slim}
with open("jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"완료: {len(slim)}건 저장 ({out['generated_at']} KST)")
