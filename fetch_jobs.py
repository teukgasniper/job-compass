"""잡알리오 + 클린아이 + 나라일터 채용공고 수집 → jobs.json (4시간마다 GitHub Actions에서 실행)
잡알리오: 1순위 공공데이터포털 직접 연결 / 2순위 구글 Apps Script 중계
클린아이: 지방공기업·출자출연기관 (시도별 순회 수집)
나라일터: 인사혁신처 공공취업정보 조회 서비스 (중앙부처·지자체·교육청 포함)
키·주소·암호는 GitHub Secrets에서만 읽습니다. 코드에 적지 마세요.

[2026-09-28 수정] 클린아이 API 통합 — 지방공기업·출자출연기관 채용공고 수집
                  3자 중복 소거 (잡알리오 → 클린아이 → 나라일터)
                  원문 URL 자동 추출 (ACCUSATION·JOB_SEEK_ETC에서 외부 URL 파싱)
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
CLEANEYE_KEY = os.environ.get("CLEANEYE_API_KEY", "").strip()

if not KEY and not RELAY_URL:
    sys.exit("ALIO_API_KEY 또는 RELAY_URL 이 필요합니다.")

BASES = ["http://apis.data.go.kr/1051000/recruitment/list",
         "https://apis.data.go.kr/1051000/recruitment/list"]
KEEP = ["recrutPblntSn","instNm","recrutPbancTtl","hireTypeNmLst","workRgnNmLst","recrutSeNm",
        "recrutNope","pbancBgngYmd","pbancEndYmd","srcUrl","acbgCondNmLst","replmprYn",
        "ongoingYn","ncsCdNmLst"]
# 클린아이 전용 추가 필드
KEEP_CLEANEYE = KEEP + ["recruitCnt","yearIncome","judgeMethod","localYn","localName",
                         "address","entGb","entKind","careerType"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json"}

# ─────────────────────────────────────────────────────────────
# 의사직 제외 필터 (잡알리오 + 클린아이 + 나라일터 공통)
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
# 임원급 제외 필터 (잡알리오 + 클린아이 + 나라일터 공통)
# ─────────────────────────────────────────────────────────────
EXECUTIVE_KEYWORDS = [
    "비상임이사", "상임이사", "이사장 공모", "사장 공모", "감사 공모",
    "임원 공모", "임원(", "기관장 공모", "원장 공모", "이사 모집",
    "비상임감사", "상임감사", "사장 모집", "이사 공모",
    "노동이사",  # 클린아이에서 발견
]

# ─────────────────────────────────────────────────────────────
# 나라일터 전용 제외 필터
# ─────────────────────────────────────────────────────────────
GOJOBS_INST_EXCLUDE = [
    "국방부", "공군", "육군", "해군", "해병대", "국군", "사령부", "군단",
    "경찰청", "경찰서", "기동단", "경찰학교",
    "소방청", "소방서", "119구조",
    "검찰청", "지방법원", "고등법원", "가정법원", "대법원",
    "교도소", "구치소", "교정청",
    "초등학교", "중학교", "고등학교", "유치원",
    "우체국",
    "소년원", "분류심사원", "보호관찰소",
]

GOJOBS_TITLE_EXCLUDE = [
    "한시인력", "기간제",
    "조리원", "조리사", "급식보조", "청소원", "환경미화", "당직",
    "대체인력", "대체직원", "육아휴직 대체",
    "방과후", "돌봄", "교육실무", "일용직",
    "변호사", "검사", "법무관",
    "비상임이사", "상임이사", "이사장 공모", "사장 공모", "감사 공모",
    "임원 공모", "기관장 공모", "원장 공모", "이사 모집", "비상임감사",
    "상임감사", "사장 모집", "이사 공모",
    "임기제", "전입", "체험형", "시간강사", "도급",
    "합격자", "불합격", "취소", "연기", "정정",
]

# ─────────────────────────────────────────────────────────────
# 클린아이 전용 설정
# ─────────────────────────────────────────────────────────────
CLEANEYE_ENDPOINT = "https://apis.data.go.kr/B551982/openApiEmployInfo/openXmlEmployInfo"

# 시도코드 — 테스트로 007001(서울) 확인됨, 나머지는 순차 테스트 후 보정
SIDO_CODES = [
    "007001", "007002", "007003", "007004", "007005", "007006", "007007", "007008",
    "007009", "007010", "007011", "007012", "007013", "007014", "007015", "007016", "007017",
]

# 클린아이 제목 제외 (나라일터 공유 + 추가)
CLEANEYE_TITLE_EXCLUDE = GOJOBS_TITLE_EXCLUDE + [
    "주차관리", "시설경비", "단기",
]

# 클린아이 고용형태 중 통과 허용 목록
CLEANEYE_QUALITY_TYPES = ["일반정규직", "상용정규직", "정규직", "무기계약직"]
# 인턴은 제목에서 "체험형" 제외 후 통과


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
    title = _as_text(x.get("recrutPbancTtl") or x.get("title"))
    return any(k in title for k in EXECUTIVE_KEYWORDS)


def is_gojobs_excluded(x):
    inst = x.get("insttname") or x.get("instNm") or ""
    title = x.get("title") or x.get("recrutPbancTtl") or ""
    if any(k in inst for k in GOJOBS_INST_EXCLUDE):
        return True
    if any(k in title for k in GOJOBS_TITLE_EXCLUDE):
        return True
    return False


def is_quality_post(x):
    if x.get("_source") == "gojobs":
        return True
    if x.get("_source") == "cleaneye":
        return True  # 클린아이는 collect 단계에서 이미 필터됨
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
    doctor_posts = [x for x in ongoing if is_doctor_post(x)]
    clean = [x for x in ongoing if not is_doctor_post(x)]
    if doctor_posts:
        print(f"[잡알리오] 의사직 공고 {len(doctor_posts)}건 제외")
        for x in doctor_posts[:5]:
            print(f"  - {x.get('instNm')} | {x.get('recrutPbancTtl')}")
    exec_posts = [x for x in clean if is_executive_post(x)]
    clean = [x for x in clean if not is_executive_post(x)]
    if exec_posts:
        print(f"[잡알리오] 임원급 공고 {len(exec_posts)}건 제외")
        for x in exec_posts[:5]:
            print(f"  - {x.get('instNm')} | {x.get('recrutPbancTtl')}")
    print(f"[잡알리오] 수집 완료: {len(clean)}건 (의사직 {len(doctor_posts)}건, 임원급 {len(exec_posts)}건 제외)")
    return clean


# ─────────────────────────────────────────────────────────────
# 2. 클린아이 수집 (지방공기업·출자출연기관)
# ─────────────────────────────────────────────────────────────
def extract_original_url(item):
    """ACCUSATION·JOB_SEEK_ETC·EXHIBIT에서 외부 원문 URL 추출. 없으면 클린아이 상세 페이지."""
    candidates = []
    for field in ("ACCUSATION", "JOB_SEEK_ETC", "EXHIBIT"):
        text = item.get(field, "")
        if text and text != "-":
            urls = re.findall(r'https?://[^\s,\)\]>}]+', text)
            candidates.extend(urls)

    for url in candidates:
        if "cleaneye.go.kr" not in url:
            return url.rstrip(")>]}")

    return item.get("URL", "")


def cleaneye_to_alio_format(item):
    """클린아이 XML item → 잡알리오 호환 포맷"""
    employ_num = 0
    try:
        employ_num = int(item.get("EMPLOY_NUM", 0))
    except (ValueError, TypeError):
        pass

    job_type = item.get("JOB_TYPE", "")
    hire_map = {"일반정규직": "정규직", "상용정규직": "정규직", "기간제": "기간제",
                "인턴": "인턴", "전문계약직": "계약직", "일반계약직": "계약직", "비상임": "비상임"}
    hire_type = hire_map.get(job_type, job_type)

    career_map = {"신입": "신입", "경력": "경력", "신입+경력": "신입/경력"}
    career_type = career_map.get(item.get("EMPLOY_GB", ""), item.get("EMPLOY_GB", ""))

    licenses = [item.get(f"ENT_LICENSE{i}", "") for i in range(1, 5)]
    licenses = [l for l in licenses if l and l != "-"]

    src_url = extract_original_url(item)

    return {
        "recrutPblntSn": f"CE-{item.get('NO', '')}",
        "instNm": item.get("ENT_NAME", ""),
        "recrutPbancTtl": item.get("ENT_TITLE", ""),
        "hireTypeNmLst": hire_type,
        "workRgnNmLst": item.get("SIDO_CD", ""),
        "recrutSeNm": career_type,
        "recrutNope": employ_num if employ_num > 0 else 0,
        "pbancBgngYmd": (item.get("PUB_DATE", "") or "").replace("-", ""),
        "pbancEndYmd": (item.get("PUB_END_DATE", "") or "").replace("-", ""),
        "srcUrl": src_url,
        "acbgCondNmLst": "",
        "replmprYn": "Y" if item.get("RE_MAN_YN") == "Y" else "N",
        "ongoingYn": "Y",
        "ncsCdNmLst": item.get("ENT_RECRUIT", ""),
        # 클린아이 고유 필드
        "recruitCnt": employ_num if employ_num > 0 else "",
        "yearIncome": item.get("YEARINCOME", ""),
        "judgeMethod": item.get("JUDGE_METHOD", ""),
        "localYn": item.get("LOCAL_YN", "N"),
        "localName": item.get("LOCAL_NAME", ""),
        "address": item.get("ADDRESS", ""),
        "entGb": item.get("ENT_GB", ""),
        "entKind": item.get("ENT_KIND", ""),
        "careerType": career_type,
        "_source": "cleaneye",
    }


def collect_cleaneye():
    if not CLEANEYE_KEY:
        print("[클린아이] CLEANEYE_API_KEY 없음 → 건너뜀")
        return []

    all_items = []
    n_excluded = {"status": 0, "title": 0, "doctor": 0, "executive": 0, "quality": 0, "substitute": 0}

    for sido_cd in SIDO_CODES:
        try:
            q = urllib.parse.urlencode({"serviceKey": CLEANEYE_KEY, "sidoCd": sido_cd, "type": "xml"}, safe="%")
            xml_data = get_xml(f"{CLEANEYE_ENDPOINT}?{q}", 30)
            root = ET.fromstring(xml_data)

            result_code = root.findtext(".//resultCode", "")
            if result_code != "0":
                result_msg = root.findtext(".//resultMsg", "")
                print(f"[클린아이] {sido_cd} 오류: {result_code} - {result_msg}")
                continue

            items = root.findall(".//item")
            passed = 0

            for item_el in items:
                item = {child.tag: (child.text or "") for child in item_el}
                title = item.get("ENT_TITLE", "")
                job_type = item.get("JOB_TYPE", "")
                position = item.get("POSITION", "")
                licenses_text = " ".join([item.get(f"ENT_LICENSE{i}", "") for i in range(1, 5)])

                # 필터 1: 모집중만
                if item.get("STATUS") != "모집중":
                    n_excluded["status"] += 1
                    continue
                # 필터 2: 제목 키워드 제외
                if any(kw in title for kw in CLEANEYE_TITLE_EXCLUDE):
                    n_excluded["title"] += 1
                    continue
                # 필터 3: 의사직 제외
                if any(kw in title for kw in DOCTOR_KEYWORDS) or any(kw in licenses_text for kw in DOCTOR_KEYWORDS):
                    if not any(s in title for s in SAFE_KEYWORDS):
                        n_excluded["doctor"] += 1
                        continue
                # 필터 4: 임원급 제외
                if any(kw in title for kw in EXECUTIVE_KEYWORDS) or any(kw in position for kw in EXECUTIVE_KEYWORDS):
                    n_excluded["executive"] += 1
                    continue
                # 필터 5: 고용형태 품질 (정규직·무기계약직 + 인턴)
                type_ok = any(qt in job_type for qt in CLEANEYE_QUALITY_TYPES) or job_type == "인턴"
                if not type_ok:
                    n_excluded["quality"] += 1
                    continue
                # 필터 6: 대체인력 제외
                if item.get("RE_MAN_YN") == "Y":
                    n_excluded["substitute"] += 1
                    continue

                converted = cleaneye_to_alio_format(item)
                all_items.append(converted)
                passed += 1

            print(f"[클린아이] {sido_cd}: {len(items)}건 → {passed}건 통과")
            time.sleep(0.5)

        except Exception as e:
            print(f"[클린아이] {sido_cd} 실패: {e}")
            continue

    print(f"[클린아이] 수집 완료: {len(all_items)}건")
    print(f"  제외 — 마감: {n_excluded['status']} / 제목: {n_excluded['title']} / "
          f"의사직: {n_excluded['doctor']} / 임원급: {n_excluded['executive']} / "
          f"고용형태: {n_excluded['quality']} / 대체인력: {n_excluded['substitute']}")
    return all_items


# ─────────────────────────────────────────────────────────────
# 3. 나라일터 수집
# ─────────────────────────────────────────────────────────────
GOJOBS_BASE = "https://apis.data.go.kr/1760000/PblJobService/getList"


def fetch_gojobs_page(page, per_page):
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

    ongoing = []
    for x in items:
        enddate = x.get("enddate", "")
        if len(enddate) >= 8 and enddate >= today_str:
            ongoing.append(x)

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
# 4. 중복 소거 (잡알리오 1순위 → 클린아이 2순위 → 나라일터 3순위)
# ─────────────────────────────────────────────────────────────
def normalize_inst(name):
    name = re.sub(r'\(주\)|\(재\)|\(사\)|\(학\)', '', name)
    name = re.sub(r'[㈜㈔\s]', '', name)
    name = re.sub(r'^재단법인', '', name)
    name = re.sub(r'^주식회사', '', name)
    return name.strip()

def normalize_title(title):
    title = re.sub(r'[\s\-·~]', '', title)
    return title[:30]

def dedup_key(inst, title):
    return f"{normalize_inst(inst)}|{normalize_title(title)}"


def merge_and_dedup(alio_items, cleaneye_items, gojobs_items):
    seen = set()
    merged = []

    # 1순위: 잡알리오
    for x in alio_items:
        key = dedup_key(x.get("instNm", ""), x.get("recrutPbancTtl", ""))
        if key not in seen:
            seen.add(key)
            item = {k: x.get(k) for k in KEEP}
            item["_source"] = "alio"
            merged.append(item)

    # 2순위: 클린아이
    ce_added, ce_skipped = 0, 0
    for x in cleaneye_items:
        key = dedup_key(x.get("instNm", ""), x.get("recrutPbancTtl", ""))
        if key not in seen:
            seen.add(key)
            merged.append(x)  # 이미 잡알리오 포맷 + 추가 필드 포함
            ce_added += 1
        else:
            ce_skipped += 1

    # 3순위: 나라일터
    gj_added, gj_skipped = 0, 0
    for gj in gojobs_items:
        converted = gojobs_to_alio_format(gj)
        key = dedup_key(converted["instNm"], converted["recrutPbancTtl"])
        if key not in seen:
            seen.add(key)
            merged.append(converted)
            gj_added += 1
        else:
            gj_skipped += 1

    print(f"[병합] 잡알리오 {len(alio_items)}건 + 클린아이 {ce_added}건(중복 {ce_skipped}) + 나라일터 {gj_added}건(중복 {gj_skipped})")
    print(f"[병합] 최종 합계: {len(merged)}건")
    return merged


# ─────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────
print("=" * 50)
print("채용공고 수집 시작")
print("=" * 50)

alio_items = collect_alio()
cleaneye_items = collect_cleaneye()
gojobs_items = collect_gojobs()
merged = merge_and_dedup(alio_items, cleaneye_items, gojobs_items)

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
