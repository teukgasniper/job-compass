"""잡알리오 + 나라일터 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
잡알리오: 1순위 공공데이터포털 직접 연결 / 2순위 구글 Apps Script 중계
나라일터: 인사혁신처 공공취업정보 조회 서비스 (중앙부처·지자체·교육청 포함)
키·주소·암호는 GitHub Secrets에서만 읽습니다. 코드에 적지 마세요.

[2026-09-24 수정] 알바급 제외 — 정규직·무기계약직·채용형인턴 포함 공고만 수집
                  임원급 제외 — 비상임이사·사장공모 등 일반 취준생 대상 아닌 공고 차단
                  나라일터 API 통합 — 잡알리오에 없는 정부부처·지자체 공고 추가 수집
                  중복 소거 + 특수직·아르바이트급 제외 + 합격자 발표 제외
                  500건씩 + 90초 타임아웃 + 3회 재시도
[2026-09-23 수정] 의사직(전문의·전임의·레지던트 등) 공고 수집 제외
"""
import json, os, sys, time, socket, urllib.request, urllib.parse, re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

KEY = os.environ.get("ALIO_API_KEY", "").strip()
RELAY_URL = os.environ.get("RELAY_URL", "").strip()
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "").strip()
GOJOBS_KEY = os.environ.get("GOJOBS_API_KEY", "").strip()

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
# 의사직 제외 필터 (잡알리오 + 나라일터 공통)
# ─────────────────────────────────────────────────────────────
DOCTOR_KEYWORDS = [
    "전문의", "전임의", "레지던트", "전공의", "수련의",
    "공중보건의", "공보의", "의사직", "진료의사", "촉탁의",
    "임상강사", "봉직의", "임상교수", "진료과장", "의무직",
    "임상스텝", "임상스태프", "펠로우",
]
SAFE_KEYWORDS = [
    "간호", "임상병리", "방사선", "물리치료", "작업치료",
    "치과위생", "응급구조", "약사", "영양사", "의무기록",
    "보건직", "의사소통",
]

# ─────────────────────────────────────────────────────────────
# 임원급 제외 필터 (잡알리오 + 나라일터 공통)
# ─────────────────────────────────────────────────────────────
EXECUTIVE_KEYWORDS = [
    "비상임이사", "상임이사", "이사장 공모", "사장 공모", "감사 공모",
    "임원 공모", "임원(", "기관장 공모", "원장 공모", "이사 모집",
    "비상임감사", "상임감사", "사장 모집", "이사 공모",
]

# ─────────────────────────────────────────────────────────────
# 나라일터 전용 제외 필터
# ─────────────────────────────────────────────────────────────

# 기관명에 포함되면 제외 (특수직 기관 + 개별 학교/우체국)
GOJOBS_INST_EXCLUDE = [
    # 군 관련
    "국방부", "공군", "육군", "해군", "해병대", "국군", "사령부", "군단",
    # 경찰
    "경찰청", "경찰서", "기동단", "경찰학교",
    # 소방
    "소방청", "소방서", "119구조",
    # 검찰·법원
    "검찰청", "지방법원", "고등법원", "가정법원", "대법원",
    # 교정시설
    "교도소", "구치소", "교정청",
    # 개별 학교 (교육청 본부는 유지)
    "초등학교", "중학교", "고등학교", "유치원",
    # 개별 우체국 (우정사업본부 본부는 유지)
    "우체국",
    # 소년원·보호시설
    "소년원", "분류심사원", "보호관찰소",
]

# 공고 제목에 포함되면 제외 (아르바이트급 + 특수직 + 임원급 + 비채용 공고)
GOJOBS_TITLE_EXCLUDE = [
    # 아르바이트급·단순노무
    "조리원", "조리사", "급식보조", "청소원", "환경미화", "당직",
    "대체인력", "대체직원", "육아휴직 대체",
    "방과후", "돌봄", "교육실무", "일용직",
    # 특수직
    "변호사", "검사", "법무관",
    # 임원급
    "비상임이사", "상임이사", "이사장 공모", "사장 공모", "감사 공모",
    "임원 공모", "기관장 공모", "원장 공모", "이사 모집", "비상임감사",
    "상임감사", "사장 모집", "이사 공모",
    # 비채용 공고 (합격자 발표·취소·연기 등)
    "합격자", "불합격", "취소", "연기", "정정",
]


def _as_text(value):
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value or "")


def is_doctor_post(x):
    text = " ".join([
        _as_text(x.get("recrutPbancTtl")),
        _as_text(x.get("ncsCdNmLst")),
    ])
    if any(k in text for k in DOCTOR_KEYWORDS):
        return True
    if "의사" in text and not any(s in text for s in SAFE_KEYWORDS):
        return True
    return False


def is_executive_post(x):
    """임원급 공고 제외 — 일반 취준생 대상 아님"""
    title = _as_text(x.get("recrutPbancTtl") or x.get("title"))
    return any(k in title for k in EXECUTIVE_KEYWORDS)


def is_gojobs_excluded(x):
    """나라일터 전용 제외: 특수직 기관 + 아르바이트급 + 비채용 공고"""
    inst = x.get("insttname") or x.get("instNm") or ""
    title = x.get("title") or x.get("recrutPbancTtl") or ""
    if any(k in inst for k in GOJOBS_INST_EXCLUDE):
        return True
    if any(k in title for k in GOJOBS_TITLE_EXCLUDE):
        return True
    return False


# ─────────────────────────────────────────────────────────────
# 알바급 제외 필터 — 정규직·무기계약직·채용형인턴 아닌 공고 차단
# ─────────────────────────────────────────────────────────────
def is_quality_post(x):
    if x.get("_source") == "gojobs":
        return True
    ht = x.get("hireTypeNmLst") or ""
    types = [h.strip() for h in ht.split(",")]
    return any(t in ("정규직", "무기계약직") or "채용형" in t for t in types)


def get_json(url, timeout):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_xml(url, timeout):
    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def direct_open():
    for port in (80, 443):
        try:
            socket.create_connection(("apis.data.go.kr", port), timeout=8).close()
            print(f"[진단] 직접 연결 가능 (포트 {port})")
            return True
        except Exception as e:
            print(f"[진단] 직접 연결 불가 (포트 {port}): {e}")
    return False


USE_DIRECT = bool(KEY) and direct_open()


# ─────────────────────────────────────────────────────────────
# 1. 잡알리오 수집
# ─────────────────────────────────────────────────────────────
def fetch_alio(page):
    if USE_DIRECT:
        q = urllib.parse.urlencode({"serviceKey": KEY, "numOfRows": 1000, "pageNo": page,
                                    "resultType": "json", "ongoingYn": "Y"}, safe="%")
        for base in BASES:
            try:
                data = get_json(f"{base}?{q}", 25)
                print(f"[잡알리오] page {page} 직접 수집 성공")
                return data
            except Exception as e:
                print(f"[잡알리오] page {page} 직접({base.split(':')[0]}) 실패: {e}")
    if RELAY_URL:
        q = urllib.parse.urlencode({"token": RELAY_TOKEN, "page": page})
        for attempt in range(3):
            try:
                data = get_json(f"{RELAY_URL}?{q}", 90)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                print(f"[잡알리오] page {page} 구글 중계 수집 성공")
                return data
            except Exception as e:
                print(f"[잡알리오] page {page} 구글 중계 시도 {attempt+1} 실패: {e}")
                time.sleep(5)
    raise RuntimeError(f"[잡알리오] page {page} 수집 실패 (직접·중계 모두 실패)")


def collect_alio():
    items, page = [], 1
    while True:
        data = fetch_alio(page)
        batch = data.get("result") or []
        items += batch
        total = int(data.get("totalCount") or 0)
        if len(batch) < 1000 or len(items) >= total or page >= 5:
            break
        page += 1
    ongoing = [x for x in items if x.get("ongoingYn") == "Y"]
    # 의사직 제외
    doctor_posts = [x for x in ongoing if is_doctor_post(x)]
    clean = [x for x in ongoing if not is_doctor_post(x)]
    if doctor_posts:
        print(f"[잡알리오] 의사직 공고 {len(doctor_posts)}건 제외")
        for x in doctor_posts[:5]:
            print(f"  - {x.get('instNm')} | {x.get('recrutPbancTtl')}")
    # 임원급 제외
    exec_posts = [x for x in clean if is_executive_post(x)]
    clean = [x for x in clean if not is_executive_post(x)]
    if exec_posts:
        print(f"[잡알리오] 임원급 공고 {len(exec_posts)}건 제외")
        for x in exec_posts[:5]:
            print(f"  - {x.get('instNm')} | {x.get('recrutPbancTtl')}")
    print(f"[잡알리오] 수집 완료: {len(clean)}건 (의사직 {len(doctor_posts)}건, 임원급 {len(exec_posts)}건 제외)")
    return clean


# ─────────────────────────────────────────────────────────────
# 2. 나라일터 수집
# ─────────────────────────────────────────────────────────────
GOJOBS_BASE = "https://apis.data.go.kr/1760000/PblJobService/getList"


def fetch_gojobs_page(page, per_page):
    """나라일터 1페이지 수집 (3회 재시도, 90초 타임아웃)"""
    q = urllib.parse.urlencode({"serviceKey": GOJOBS_KEY, "numOfRows": per_page, "pageNo": page}, safe="%")
    for attempt in range(3):
        try:
            xml_data = get_xml(f"{GOJOBS_BASE}?{q}", 90)
            root = ET.fromstring(xml_data)
            err = root.findtext(".//errMsg")
            if err:
                print(f"[나라일터] page {page} API 에러: {err}")
                return []
            items = []
            for item in root.findall(".//item"):
                fields = {child.tag: child.text for child in item}
                items.append(fields)
            return items
        except Exception as e:
            print(f"[나라일터] page {page} 시도 {attempt+1}/3 실패: {e}")
            if attempt < 2:
                time.sleep(3)
    print(f"[나라일터] page {page} 3회 모두 실패 → 건너뜀")
    return []


def collect_gojobs():
    if not GOJOBS_KEY:
        print("[나라일터] GOJOBS_API_KEY 없음 → 건너뜀")
        return []

    today_str = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")

    # 1) 전체 건수 확인
    try:
        q = urllib.parse.urlencode({"serviceKey": GOJOBS_KEY, "numOfRows": 1, "pageNo": 1}, safe="%")
        xml_data = get_xml(f"{GOJOBS_BASE}?{q}", 30)
        root = ET.fromstring(xml_data)
        err = root.findtext(".//errMsg")
        if err:
            print(f"[나라일터] API 에러: {err}")
            return []
        total = int(root.findtext(".//totalCount") or 0)
        print(f"[나라일터] 전체 건수: {total:,}")
    except Exception as e:
        print(f"[나라일터] 전체 건수 확인 실패: {e}")
        return []

    # 2) 최근 데이터 수집
    per_page = 500
    last_page = (total + per_page - 1) // per_page
    start_page = max(1, last_page - 19)

    items = []
    success_count = 0
    for page in range(start_page, last_page + 1):
        batch = fetch_gojobs_page(page, per_page)
        if batch:
            items.extend(batch)
            success_count += 1
            print(f"[나라일터] page {page}/{last_page} 수집 ({len(batch)}건)")
        time.sleep(1)

    print(f"[나라일터] 수집 완료: {len(items)}건 ({success_count}/{last_page - start_page + 1} 페이지 성공)")

    # 3) 마감일 기준 진행 중 공고만 필터
    ongoing = []
    for x in items:
        enddate = x.get("enddate", "")
        if len(enddate) >= 8 and enddate >= today_str:
            ongoing.append(x)

    # 4) 의사직 제외
    after_doctor = []
    n_doctor = 0
    for x in ongoing:
        title = x.get("title", "")
        if any(k in title for k in DOCTOR_KEYWORDS):
            n_doctor += 1
            continue
        if "의사" in title and not any(s in title for s in SAFE_KEYWORDS):
            n_doctor += 1
            continue
        after_doctor.append(x)

    # 5) 특수직·아르바이트급·임원급·비채용 공고 제외
    clean = []
    n_special = 0
    for x in after_doctor:
        if is_gojobs_excluded(x):
            n_special += 1
            continue
        clean.append(x)

    print(f"[나라일터] 진행 중: {len(ongoing)}건 → 의사직 {n_doctor}건 제외 → 특수직·아르바이트·임원급 {n_special}건 제외 → 최종: {len(clean)}건")
    return clean


def gojobs_to_alio_format(gj):
    """나라일터 필드 → 잡알리오 필드 형식으로 변환"""
    enddate = gj.get("enddate", "")
    bgn = gj.get("regdate", "")
    return {
        "recrutPblntSn": f"GJ-{gj.get('idx', '')}",
        "instNm": gj.get("insttname", ""),
        "recrutPbancTtl": gj.get("title", ""),
        "hireTypeNmLst": "",
        "workRgnNmLst": "",
        "recrutSeNm": "",
        "recrutNope": 0,
        "pbancBgngYmd": bgn,
        "pbancEndYmd": enddate,
        "srcUrl": f"https://www.gojobs.go.kr/apmView.do?empmnsn={gj.get('idx', '')}",
        "acbgCondNmLst": "",
        "replmprYn": "N",
        "ongoingYn": "Y",
        "ncsCdNmLst": "",
        "_source": "gojobs",
    }


# ─────────────────────────────────────────────────────────────
# 3. 중복 소거 (같은 기관 + 같은 공고명 = 중복 → 잡알리오 우선)
# ─────────────────────────────────────────────────────────────
def normalize_inst(name):
    name = re.sub(r'\(주\)|\(재\)|\(사\)|\(학\)', '', name)
    name = re.sub(r'[㈜㈔\s]', '', name)
    return name.strip()

def normalize_title(title):
    title = re.sub(r'[\s\-·~]', '', title)
    return title[:30]

def dedup_key(inst, title):
    return f"{normalize_inst(inst)}|{normalize_title(title)}"


def merge_and_dedup(alio_items, gojobs_items):
    seen = set()
    merged = []

    for x in alio_items:
        key = dedup_key(x.get("instNm", ""), x.get("recrutPbancTtl", ""))
        if key not in seen:
            seen.add(key)
            item = {k: x.get(k) for k in KEEP}
            item["_source"] = "alio"
            merged.append(item)

    added = 0
    skipped = 0
    for gj in gojobs_items:
        converted = gojobs_to_alio_format(gj)
        key = dedup_key(converted["instNm"], converted["recrutPbancTtl"])
        if key not in seen:
            seen.add(key)
            merged.append(converted)
            added += 1
        else:
            skipped += 1

    print(f"[병합] 잡알리오 {len(alio_items)}건 + 나라일터 {added}건 추가 ({skipped}건 중복 제거)")
    print(f"[병합] 최종 합계: {len(merged)}건")
    return merged


# ─────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────
print("=" * 50)
print("채용공고 수집 시작")
print("=" * 50)

alio_items = collect_alio()
gojobs_items = collect_gojobs()
merged = merge_and_dedup(alio_items, gojobs_items)

# ★ 알바급 제외 — 정규직·무기계약직·채용형인턴 포함 공고만 유지
before = len(merged)
merged = [x for x in merged if is_quality_post(x)]
print(f"[품질필터] {before}건 → {len(merged)}건 (알바급 {before - len(merged)}건 제외)")

if len(merged) < 50:
    sys.exit(f"수집 건수가 너무 적음({len(merged)}건) → 기존 데이터 유지")

kst = datetime.now(timezone(timedelta(hours=9)))
out = {"generated_at": kst.strftime("%Y-%m-%d %H:%M"), "count": len(merged), "result": merged}
with open("jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"\n완료: {len(merged)}건 저장 ({out['generated_at']} KST)")
