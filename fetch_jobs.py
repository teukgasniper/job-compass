"""잡알리오 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
API 키는 GitHub Secrets의 ALIO_API_KEY 에서만 읽습니다. 코드에 키를 적지 마세요."""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

KEY = os.environ.get("ALIO_API_KEY", "").strip()
if not KEY:
    sys.exit("ALIO_API_KEY 가 설정되지 않았습니다.")

BASE = "https://apis.data.go.kr/1051000/recruitment/list"
KEEP = ["recrutPblntSn","instNm","recrutPbancTtl","hireTypeNmLst","workRgnNmLst","recrutSeNm",
        "recrutNope","pbancBgngYmd","pbancEndYmd","srcUrl","acbgCondNmLst","replmprYn",
        "ongoingYn","ncsCdNmLst"]

def fetch(page):
    q = urllib.parse.urlencode({"serviceKey": KEY, "numOfRows": 1000, "pageNo": page,
                                "resultType": "json", "ongoingYn": "Y"}, safe="%")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}?{q}", timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"page {page} 시도 {attempt+1} 실패: {e}")
            time.sleep(5)
    raise RuntimeError(f"page {page} 수집 실패")

items, page = [], 1
while True:
    data = fetch(page)
    batch = data.get("result") or []
    items += batch
    total = int(data.get("totalCount") or 0)
    if len(batch) < 1000 or len(items) >= total or page >= 5:
        break
    page += 1

# 진행 중인 공고만, 필요한 칸만
slim = [{k: x.get(k) for k in KEEP} for x in items if x.get("ongoingYn") == "Y"]

# 안전장치: 비정상적으로 적게 오면 기존 파일을 덮어쓰지 않음
if len(slim) < 50:
    sys.exit(f"수집 건수가 너무 적음({len(slim)}건) → 기존 jobs.json 유지")

kst = datetime.now(timezone(timedelta(hours=9)))
out = {"generated_at": kst.strftime("%Y-%m-%d %H:%M"), "count": len(slim), "result": slim}
with open("jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"완료: {len(slim)}건 저장 ({out['generated_at']} KST)")
