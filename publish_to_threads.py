# -*- coding: utf-8 -*-
"""
쓰레드 자동발행 (지침서 v3.5 규격)
흐름: jobs.json + job_posts.json → 본문 글 있는 공고 필터·스코어링 → 중복 소거
      → hiring03 본문에서 팩트 보강 → Claude(Sonnet) 후킹글 생성·검증
      → Threads 발행 → 첫 댓글(선택) → 사용 기록 저장

환경변수
  ACCOUNT          계정 식별자 (예: jami) — 기록 파일 이름에 사용
  CLAUDE_API_KEY   Anthropic API 키
  THREADS_TOKEN    Threads 장기 토큰
  THREADS_USER_ID  Threads 사용자 ID
  DRY_RUN          'true'면 글만 생성해서 로그에 출력 (발행·기록 X)
  COMMENT_LINK     profile(기본, 링크 없는 고정 문구) | none(댓글 없음) | hiring | post
  COMMENT_TEXT     profile 모드 댓글 문구 (기본 "👆 프로필 링크 확인!")
  CLAUDE_MODEL     기본 claude-sonnet-5
  JITTER_MAX_MIN   발행 전 랜덤 대기 최대 분 (예약 실행 시 자연스럽게)
  USE_LOGO         기본 on — 글 하단에 기관 로고 카드(logos/기관명.png) 첨부, off면 글만
  MIN_GAP_MIN      기본 60 — 마지막 발행(수동 포함) 후 이 시간(분)이 안 지났으면 발행하지 않고 건너뜀
                   (예약 실행은 워크플로우에서 110 — 매시간 깨우고 2시간 간격 유지)

[2026-09-29 수정] v3.4 후킹 스타일 적용 — 유형별 비중(인물 30%/비인물 70%) + 제외 패턴 8종 + 센스 있는 오해 원칙
[2026-10-02 수정] v3.5 — 웃길 거면 확실하게, 아니면 담백하게 / 제외 패턴 15종 / 후보 4개 생성 → AI 채점 → 1개 발행
                  훅 줄당 26자 / 빈 값·1명 공고 제외 / 초봉 섞임 방지 / 최근 10개 훅·클로저 반복 금지
                  민간 대기업·중견기업(공채속보) 공고 포함 / 로고 실패 시 기관명 텍스트 카드
[2026-10-05 수정] 석사·박사 전용 공고 제외 / 학력은 최소 요건 '이상'으로 표기 / 중견기업을 대기업으로 쓰지 않게
[2026-10-03 수정] Claude API 일시 오류(429·5xx·529·타임아웃) 재시도 4회
                  3회 모두 채점 0점·규격 탈락이면 억지 발행하지 않고 건너뜀 (다음 회차 재시도)
                  로고 재시도 날짜 한국 시간 기준
[2026-10-06 수정] 민간 후킹 테스트 결과 반영 (기존 규칙·베스트는 유지, 제외만 추가)
                  제외 패턴 16~22 추가 — 학력 하한 지목 / 장벽 소재(전형 단계·인적성·코딩테스트·어학·학점)
                  / 부정 종결 훅 / 전문 용어·약어 / 비현실적 오해 / 근거 없는 포기 방지 / 꼬인 문장
                  민간 공고 학력은 본문 '지원 자격 상세' 기준 (공채속보 학력 값 오류 대응, 확인 안 되면 건너뜀)
                  특가 '포기 방지'는 학력무관 같은 열린 조건이 있는 공고에서만 / '대기업'은 누구나 아는 그룹사만
                  코드 검사에 학력 하한·장벽·전문 용어 정규식 추가 (훅+클로저) / 실패 사례를 프롬프트에 예시로
[2026-10-12 수정] 클린아이(지방공기업) 편입 — 발행 직전 공고문을 Sonnet으로 읽어 학력 확인(edu_lookup.py), 못 찾으면 학력 없이 발행, 학력 언급 금지·지역제한 명시 /
                  공공 차례에 공공 신규가 없으면 공공 재발행(민간으로 안 샘) / 민간은 누구나 아는 대기업만 /
                  조회수(views.json) 가산으로 핫한 공고 우선 / 진료전담교수 등 의사직 제외 추가
[2026-10-17 수정] 수동 공고 마감 임박(D-1~3) ⚠️ 글은 전체 계정 통틀어 1번만 — 어느 계정이든 한 번 올리면 끝,
  그 기간엔 다른 계정이 같은 공고를 다시 올리지 않음 (일반 공고 마감 임박 규칙은 그대로)
[2026-10-17 수정] 계약직·기간제·임시직·비정규직은 쓰레드에서 아예 언급 안 함 (본문으로 먼저 들어오게 하는 게 목표 — 본문엔 그대로 있음)
  정규직·무기계약직·정규직 전환형은 장점이라 그대로 후킹에 씀. 섞인 공고(정규직전환형,기간제 등)는 장점 쪽만 넘김
[2026-10-17 수정] 모집 인원 5명 이하(수동 공고는 인원 데이터가 없어도 포함)는 인원 언급 금지 — 소수 채용은 오히려 매력이
  떨어짐(성신여대 1명 공고 조회수 낮음). 인원 대신 브랜드·하는 일·근무지·근무조건·연봉·전형 일정으로 후킹
[2026-10-17 수정] 수동 공고는 계정끼리 하루씩 엇갈려 발행 — 다른 계정이 오늘(KST) 올린 수동 공고는 오늘 안 올림
  (같은 공고가 하루에 3계정에 다 뜨면 신비감이 떨어져 조회수가 낮아짐). 일반 공고 순위는 그대로
[2026-10-12 수정] 멀티 계정 — threads_state/의 다른 계정 기록을 같이 읽어 같은 공고(같은 기관+같은 공고)는 다른 계정에서 안 올림
                  (같은 기관 다른 공고는 가능) / 새 공고 소진 시 ① 다른 계정에서 터진 글(조회수가 그 계정 평균 이상)을
                  가져와 다른 유형으로 각색 ② 그래도 없으면 내 계정 글만 재발행 / 내 글 조회수를 6시간마다 기록(views)
[2026-10-20 수정] 새 공고는 계정마다 한 번씩 다 올림 — '새 공고' 기준을 "아무 계정도 안 올린"에서 "내 계정이 안 올린"으로
                  (같은 공고는 같은 날 한 계정만 → 계정끼리 날짜만 다르게), 다른 계정 글의 훅·유형과 겹치지 않게 작성
[2026-10-20 수정] 계정 확장 대비 — 각색 후보: 전체 계정 통틀어 조회수 높은 순 → 조회수 없는 다른 계정 공고도 점수순
                  (터진 글이 바닥나도 멈추지 않음) / 같은 날 같은 공고는 한 계정만 — 수동 공고에서 일반 공고까지 확대
[2026-10-07 수정] 공공 8 : 민간 2 비율 — 최근 10건 중 민간이 2건 미만일 때만 민간에서 뽑음 (민간 연속 금지)
                  (민간 +45 고정 가산 때문에 민간이 90% 가까이 뽑히던 문제)
                  같은 그룹(한화·효성·신세계·LS·SK 등) 최근 6건 안에 있으면 건너뜀 — 계열사 연달아 발행 방지
[2026-10-15 수정] 발행 순위 변경 (공공 8 : 민간 2 비율은 그대로, 각 차례 안에서 아래 순서)
                  1순위 신규 — 접수 시작 3일 이내 + 어느 계정에도 안 올린 공고 (본문 있는 것 먼저, 점수순)
                  2순위 마감 임박 — 마감 D-1~D-2 공고 (안 올린 공고 + 내가 올렸던 공고의 마감 알림 1회, 본문 있는 공고 먼저)
                        → 훅 맨 앞 ⚠️ + 마감 임박 강조로만 작성 (후보 4개 전부), 코드 검사로 강제
                        → 1순위가 계속 있어도 최근 URGENT_EVERY건(기본 3) 안에 마감 임박 글이 없으면 2순위 먼저
                  3순위 나머지 안 올린 공고 / 4순위 우리 다른 계정에서 터진 글 각색 / 5순위 내 글 재발행
[2026-10-16 수정] 수동 공고(MN-) 최우선 — 각 자동 계정에 수동 공고가 최소 1번씩은 올라가게 (다른 계정이 올렸어도 내 계정엔 올림)
                  · 0순위 ① 수동 공고 마감 임박(D-1~D-2) 알림 ⚠️ (계정마다 1번) ② 내 계정에 아직 안 올린 수동 공고
                  · 수동 공고끼리 연달아 올리지 않음 (직전 글이 수동 공고면 이번 회차는 다른 공고) / 공공 8 : 민간 2 비율보다 우선
                  · 수동 공고는 고용형태(계약직·임시직 포함)·신입 필터를 건너뜀 — 직접 고른 공고라서
                  · 최근에 넣은 수동 공고(접수 시작일 최신순)부터 / manual_jobs.json 항목에 "threads": false 를 넣으면 쓰레드 제외
                  민간(공채속보·수동 공고) 훅·클로저·리스트에 학력·어학(토익 등) 조건 금지 — 진입장벽으로 보여 유입이 안 됨
                  (공공기관·공무직은 학력무관 등이 오히려 무기라 그대로 둠)
[2026-10-15 수정] 클린아이 공고는 학력 확인 때 실제 모집 직무·주력 고용형태도 같이 확인 (edu_lookup.py)
                  → 인원 가장 많은 직무가 요양보호·미화·경비·조리 등이거나 주력 분야가 계약직·시간제면 제외
                  (제목에 직무가 없고 고용형태가 '정규직'으로만 들어오는 공고 대응 — 인천광역시사회서비스원 요양보호사 계약직 사례)
"""
import os, re, io, json, time, base64, random, subprocess, datetime as dt
from urllib.parse import urljoin, urlparse, quote
import requests
from edu_lookup import apply_edu, lookup_edu   # [2026-10-12] 클린아이 학력 확인 (공고문 → Sonnet)
from edu_lookup import blocked_reason, cached_block   # [2026-10-15] 클린아이 실제 직무·고용형태 확인 → 현장직·계약직 주력 공고 제외

JOBS_URL = "https://teukgasniper.github.io/job-compass/jobs.json"
POSTS_URL = "https://teukgasniper.github.io/job-compass/job_posts.json"
VIEWS_URL = "https://teukgasniper.github.io/job-compass/views.json"   # [2026-10-12] 핫한 공고 우선용
HIRING_URL = "https://hiring.ddolbestory.com/"
THREADS_API = "https://graph.threads.net/v1.0"

ACCOUNT = os.environ.get("ACCOUNT", "jami").strip().lower()
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
COMMENT_LINK = os.environ.get("COMMENT_LINK", "").strip().lower() or "profile"
COMMENT_TEXT = os.environ.get("COMMENT_TEXT", "").strip() or "👆 프로필 링크 확인!"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5"
FALLBACK_MODEL = "claude-sonnet-4-6"
JITTER_MAX_MIN = int(os.environ.get("JITTER_MAX_MIN", "0") or 0)
MIN_GAP_MIN = int(os.environ.get("MIN_GAP_MIN", "60") or 60)   # 계정 발행 최소 간격(분) — 수동·자동 겹침 방지
NEW_DAYS = int(os.environ.get("NEW_DAYS", "3") or 3)            # [2026-10-15] 접수 시작 N일 이내 = 1순위 신규
MANUAL_URGENT_DAYS = 3   # [2026-10-17] 수동 공고 마감 임박 = D-1 ~ D-3, 전체 계정 통틀어 ⚠️ 글 1번
URGENT_DAYS = int(os.environ.get("URGENT_DAYS", "2") or 2)      # [2026-10-15] 마감 D-1 ~ D-N = 2순위 마감 임박
URGENT_EVERY = int(os.environ.get("URGENT_EVERY", "3") or 3)    # [2026-10-15] 최근 N건 안에 마감 임박 글이 없으면 1순위보다 먼저
# [2026-10-19] 긴급형(⚠️) 쏠림 방지 — 최근 URGENT_WINDOW건 안에 긴급형이 URGENT_MAX개 이상이면 이번엔 긴급형 금지
#              (10/17~19 세 계정 글의 절반 이상이 ⚠️ 마감 글 → 같은 톤 반복으로 조회수 급락)
URGENT_WINDOW = int(os.environ.get("URGENT_WINDOW", "3") or 3)
URGENT_MAX = int(os.environ.get("URGENT_MAX", "1") or 1)
# [2026-10-19] 재발행 제한 — 같은 계정에서 같은 공고는 최소 REPOST_MIN_DAYS일 간격, 총 REPOST_MAX번까지 (마감 알림 포함)
#              (sniper가 동천안우체국 공고 2개를 3일 사이 4번 올린 사례)
REPOST_MIN_DAYS = int(os.environ.get("REPOST_MIN_DAYS", "3") or 3)
REPOST_MAX = int(os.environ.get("REPOST_MAX", "2") or 2)

USE_LOGO = os.environ.get("USE_LOGO", "on").strip().lower() != "off"
REPO = os.environ.get("GITHUB_REPOSITORY", "teukgasniper/job-compass")
LOGO_DIR = "logos"
MISSING_PATH = "logos_missing.txt"
LOGO_RETRY_DAYS = 14

STATE_DIR = "threads_state"
STATE_PATH = os.path.join(STATE_DIR, f"{ACCOUNT}.json")
KST = dt.timezone(dt.timedelta(hours=9))

# ─────────────────────────── 필터·스코어링 (지침서 4장) ───────────────────────────
GOOD_HIRE = ("정규직", "무기계약직", "청년인턴(채용형)")
NEWBIE_OK = ("신입",)
DOCTOR_WORDS = ("전임의", "레지던트", "전공의", "수련의", "의사직", "전문의", "임상강사", "일반의",
                "진료전담", "전담의", "진료교수")   # [2026-10-12] 진료전담교수 등 추가
BRANDS = (
    "한국전력", "한전", "한국토지주택공사", "한국수자원공사", "한국철도공사", "코레일",
    "한국가스공사", "한국도로공사", "국민건강보험공단", "국민연금공단", "근로복지공단",
    "한국조폐공사", "인천국제공항공사", "한국공항공사", "한국수력원자력", "한국남동발전",
    "한국남부발전", "한국동서발전", "한국서부발전", "한국중부발전", "한국지역난방공사",
    "한국농어촌공사", "한국마사회", "한국관광공사", "대한무역투자진흥공사", "KOTRA",
    "한국산업은행", "한국수출입은행", "IBK기업은행", "중소벤처기업진흥공단", "한국주택금융공사",
    "주택도시보증공사", "한국자산관리공사", "건강보험심사평가원", "한국에너지공단",
    "한국장애인고용공단", "한국산업인력공단", "국가철도공단", "한국부동산원", "한국전기안전공사",
    "한국가스안전공사", "서울교통공사", "한국원자력환경공단", "한전KDN", "한전KPS", "한국석유공사",
)


def norm_inst(name: str) -> str:
    return re.sub(r"^\((주|재|사|유|합)\)\s*|\s*\((주|재|사)\)$", "", (name or "")).strip()


def norm_key(s: str) -> str:
    return re.sub(r"[\s\(\)\[\]·,.\-_'\"]", "", s or "")


def dday(end_ymd: str, today: dt.date) -> int:
    try:
        end = dt.datetime.strptime(end_ymd, "%Y%m%d").date()
    except Exception:
        return -999
    return (end - today).days


EMPTY_VALS = ("", "공고 참조", "공고참조", "기타", "-", "0")
HOOK_LINE_MAX = 26          # 훅 한 줄 최대 글자 수 (이모지 제외) — 화면상 2줄 안에 끝내기


def is_private(job: dict) -> bool:
    """고용24 공채속보 = 민간 대기업·중견기업 공고"""
    return job.get("_source") == "work24"


def is_cleaneye(job: dict) -> bool:
    """[2026-10-12] 클린아이 = 지방공기업·출자출연기관 (학력 항목이 원래 없는 출처)"""
    return job.get("_source") == "cleaneye"


def is_gojobs(job: dict) -> bool:
    """[2026-10-14] 나라일터 = 중앙부처·지자체 (고용형태·학력·인원·신입 구분이 전부 빈 값으로 들어오는 출처)"""
    return job.get("_source") == "gojobs"


# [2026-10-14] 나라일터는 제목으로만 판단 — '공무직'(무기계약 근로자)이 들어간 공고만 통과, 기간제·대체·시간제 등은 제외
GOJOBS_OK_RE = re.compile(r"공무직|상시계약집배원|상시집배원|무기계약")
GOJOBS_BAD_RE = re.compile(r"기간제|대체|육아휴직|한시|단시간|시간제|시간선택|(?<!무기)계약직|임기제|인턴|장애인\s*구분|결과|면접\s*안내")
_GOJOBS_UNIT_RE = re.compile(r"(팀|과|실|담당관|대변인|정책관|연구부|사업부|지원단|관리국)$")


def gojobs_inst(name: str) -> str:
    """'과학기술정보통신부 우정사업본부 충청지방우정청 진천우체국' → '진천우체국' (리스트 1번·카드 검색용 짧은 이름)
    맨 끝이 부서명(○○팀·○○과 등)이면 그 앞 기관명을 씀"""
    parts = (name or "").split()
    for t in reversed(parts):
        if not _GOJOBS_UNIT_RE.search(t):
            return t
    return parts[0] if parts else (name or "")


SALARY_MIN = 3000   # [2026-10-12] 연봉 3천만원 미만은 쓰레드에 안 씀 (외부 유입 후킹이 안 됨, 본문에는 그대로 표시)


def salary_manwon(text) -> int:
    """'3200만원 이상', '3,200만원', '1억 200만원' → 만원 단위 숫자 (못 읽으면 0)"""
    t = str(text or "").replace(",", "").replace(" ", "")
    m = re.search(r"(?:(\d+)억)?(\d+)?만", t)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)
    m = re.search(r"(\d+)억", t)
    return int(m.group(1)) * 10000 if m else 0


def low_salary_in(text: str) -> bool:
    """글에 3천만원 미만 연봉이 들어갔는지 (연봉·급여·보수 바로 뒤 금액 기준)"""
    for m in re.finditer(r"(연봉|급여|보수|임금)[^\n\d]{0,12}((?:\d[\d,]*\s*억\s*)?\d[\d,]*\s*만)", text or ""):
        v = salary_manwon(m.group(2))
        if 0 < v < SALARY_MIN:
            return True
    return False


def cleaneye_kind(job: dict) -> str:
    """[2026-10-12] 클린아이 기관 성격 한 줄 — 리스트에 넣어 공공기관임을 보여줌 (예: '경상북도 출연 공공기관')"""
    rgn = re.split(r"[ ,]", (job.get("workRgnNmLst") or "").strip())[0]
    gb, kind = job.get("entGb") or "", job.get("entKind") or ""
    if gb in ("지방공사", "지방공단"):
        what = "지방공기업"
    elif "의료" in kind or "의료원" in (job.get("instNm") or ""):
        what = "공공병원"
    elif "출자" in gb:
        what = "출자 공공기관"
    else:
        what = "출연 공공기관"
    return f"{rgn} {what}".strip()


def edu_unknown(job: dict, post_text: str = "") -> bool:
    """학력을 확인할 수 없는 클린아이 공고 — 리스트·훅에서 학력 언급 금지"""
    return is_cleaneye(job) and not has_value(job.get("acbgCondNmLst")) and not private_edu_ok(post_text)


def edu_hidden(job: dict, post_text: str = "") -> bool:
    """[2026-10-19] 쓰레드에 학력을 쓰지 않는 공고 — 학력 확인 불가(클린아이) 또는 공공인데 '학력무관'이 아닌 공고
    (학사·대졸 이상 같은 조건은 진입장벽으로 읽혀 유입이 끊김 → 학력 대신 다른 장점으로 어필. 학력무관만 무기로 씀)"""
    if edu_unknown(job, post_text):
        return True
    if is_private(job) or is_gojobs(job):         # 민간은 학력 데이터를 원래 안 넘김, 나라일터는 따로 금지
        return False
    v = job.get("acbgCondNmLst") or ""
    if v == "면허·자격 필수":                      # 클린아이 면허 필수 공고는 따로 안내 (자격 내용을 리스트에 씀)
        return False
    return has_value(v) and "무관" not in v


def has_value(v) -> bool:
    return str(v if v is not None else "").strip() not in EMPTY_VALS


# [2026-10-12] 취준생 대상이 아닌 공고 (임원·개방형·경력경쟁·교수·박사급·시험 안내 공지 등)
NOT_NEWBIE_RE = re.compile(
    r"개방형|선임이사|상임이사|비상임|이사\s*및\s*감사|감사\s*공개모집|감사관|임원|본부장|사장\s*(공모|모집)|대표\s*\(|"
    r"원장\s*(공모|모집|선발|\()|관장|보건소장|경력경쟁|전임교원|교수|연구위원|박사후|박사급|"
    r"위촉연구원|추천선발|단원\s*모집|필기시험\s*일시|시험\s*장소|일정\s*변경|합격자")
# 계약직·경력직은 제목에 정규직·채용형·신입이 같이 있으면 통과 (예: "경력직 및 채용형인턴", "정규직 조리사, 계약직…")
SOFT_NOT_NEWBIE_RE = re.compile(r"(?<!무기)계약직|경력직(?!원)")


def not_newbie(title: str) -> bool:
    if NOT_NEWBIE_RE.search(title):
        return True
    if "제한경쟁" in title and not re.search(r"공개|상시|신입|채용형", title) \
            and not MIXED_TRACK_RE.search(title):   # "공개, 제한경쟁"·일반 전형 혼합 공고는 통과 [2026-10-19]
        return True
    return bool(SOFT_NOT_NEWBIE_RE.search(title)) and not re.search(r"정규직|채용형|신입", title)


# [2026-10-14] 20~30대 취준생이 거의 안 가는 현장 단순직 (제목 기준)
YOUTH_MISS_RE = re.compile(r"미화|청소(?!년)|환경관리원|경비|방호원|조리원|조리실무|취사|급식|주차|간병|요양보호")   # 청소년·조리사(요리사)는 제외 안 함


# [2026-10-19] 박사 이상·연구책임자급 공고 — 지원 대상이 너무 좁아 쓰레드 글감에서 제외 (제목 기준)
PHD_ONLY_RE = re.compile(r"박사후|박사급|박사\s*(이상|학위)|석사후|석사급|석사\s*(이상|학위)|연구위원|Research\s*Fellow|연구책임자|책임연구원|선임연구원|전임교원|교수(?!학습|요원)")
# 석·박사급 직책과 함께 학사 이하도 지원 가능한 직책(일반 연구원·인턴·사업수행직 등)을 같이 뽑는 공고는 통과 (예: '선임연구원 및 연구원')
PHD_MIXED_RE = re.compile(r"(및|,|·|/)\s*(연구원|연구인턴|인턴|인턴연구원|학사|사업수행|행정|원급)")


# [2026-10-19] 보훈·장애인 전형이 '일부'로 섞인 혼합 공고 — 제한 전형 전용 공고가 아니므로 제외하지 않음
MIXED_TRACK_RE = re.compile(r"(보훈|장애)[^,)\]]{0,15}포함|일반\s*(경쟁|정규|직|전형|채용|및|·|,|과)|일반정규")


def eligible(job: dict, today: dt.date) -> bool:
    if job.get("ongoingYn") != "Y":
        return False
    if is_manual_id(job.get("recrutPblntSn")):    # [2026-10-16] 수동 공고는 직접 고른 공고 → 고용형태·신입·제목 필터 없이 마감만 확인
        return job.get("always") or dday(job.get("pbancEndYmd", ""), today) >= 1
    title = job.get("recrutPbancTtl") or ""
    if is_gojobs(job):
        # [2026-10-14] 나라일터는 고용형태·학력·인원·신입 구분이 전부 빈 값 → 아래 데이터 칸 검사 대신 제목으로 판단
        #              '공무직'이 들어간 공고만 무기계약직으로 보고 통과 (인원·학력은 글에서 아예 안 씀)
        if not GOJOBS_OK_RE.search(title) or GOJOBS_BAD_RE.search(title):
            return False
    else:
        # 빈 값 공고 제외 (리스트에 '공고 참조'가 들어가는 걸 원천 차단)
        if not has_value(job.get("hireTypeNmLst")):
            return False
        # [2026-10-06] 공채속보(민간)는 학력 값이 비거나 마지막 값(석사·박사)만 들어오는 수집 오류가 있음
        #              → 민간은 여기서 거르지 않고 본문 '지원 자격 상세'로 다시 확인 (main → private_edu_ok)
        # [2026-10-12] 클린아이는 학력 항목이 원래 없음 → 학력 없이 발행 (리스트·훅에서 학력 언급 금지)
        if not is_private(job) and not is_cleaneye(job) and not has_value(job.get("acbgCondNmLst")):
            return False
        if not is_private(job):                       # 민간 공고는 인원 데이터가 원래 없음 → 예외
            if int(job.get("recrutNope") or 0) <= 1:  # 인원 빈 값·1명짜리 제외
                return False
        hire = job.get("hireTypeNmLst") or ""
        if not any(h in hire for h in GOOD_HIRE):
            return False
        se = job.get("recrutSeNm") or ""
        if not (any(n in se for n in NEWBIE_OK) or "무관" in se):
            return False
    if any(w in title for w in DOCTOR_WORDS):
        return False
    if not_newbie(title):
        return False
    # [2026-10-05] 학력이 석사·박사뿐인 공고는 일반 취준생 대상이 아니라 제외
    edu = [e.strip() for e in (job.get("acbgCondNmLst") or "").split(",") if e.strip()]
    if not is_private(job) and edu and all(e in ("석사", "박사") for e in edu):   # [2026-10-19 재확인] 석·박사 이상 공고는 제외, 학사까지 OK
        return False
    if PHD_ONLY_RE.search(title) and not PHD_MIXED_RE.search(title):   # [2026-10-19] 박사 이상·연구책임자급만 뽑는 공고 제외 (일반 연구직은 통과)
        return False
    # [2026-10-02] 지원 대상이 제한된 공고(보훈·장애인 전형)는 일반 취준생 수요가 적어 제외
    # '보훈병원·보훈요양원·한국보훈복지의료공단' 같은 기관 이름은 제한 공고가 아니므로 제외 대상에서 뺌
    # [2026-10-19] 단, 일반 전형이 섞인 혼합 공고('실무직(보훈제한경쟁 포함)', '일반정규직' 등)는 통과 — 한국수산자원공단 79명 사례
    if re.search(r"보훈(?!병원|요양원|복지|지청|교육|재활|휴양)|국가유공자|취업지원\s*대상|장애인\s*(전형|전용|제한|직원\s*채용|채용)|장애인만", title) \
            and not MIXED_TRACK_RE.search(title):
        return False
    # [2026-10-14] 요양보호사(요양보호직)는 자격증 필수 + 실제 지원층이 40~60대라 20~30대 취준생 대상이 아님 → 제외
    #              ('보훈요양원' 같은 기관 이름은 '요양보호'가 아니라서 걸리지 않음)
    if "요양보호" in title:
        return False
    # [2026-10-14] 미화·청소·경비·조리 등 현장 단순직은 실제 지원층이 중장년이라 20~30대 취준생 대상이 아님 → 제외
    #              (알바·단시간은 원래 고용형태 필터와 나라일터 제외 규칙에서 빠짐)
    if YOUTH_MISS_RE.search(title):
        return False
    # [2026-10-15] 클린아이: 공고문 확인 결과 현장직·계약직 주력으로 저장된 공고는 후보에서 바로 뺌 (저장값만 봄, 호출 없음)
    if is_cleaneye(job) and cached_block(job.get("recrutPblntSn")):
        return False
    if dday(job.get("pbancEndYmd", ""), today) < 1:
        return False
    return True


def score(job: dict, today: dt.date) -> float:
    s = min(int(job.get("recrutNope") or 0), 100)
    inst = norm_inst(job.get("instNm"))
    if any(b in inst for b in BRANDS):
        s += 20
    if is_private(job):                           # 민간: 인원 점수가 없으니 이름값으로 보정
        s += 45 if job.get("bizType") == "대기업" else 15
    d = dday(job.get("pbancEndYmd", ""), today)
    if job.get("always"):                         # [2026-10-08] 상시채용(수동 공고)은 마감 임박 가산 없음
        pass
    elif 1 <= d <= 10:
        s += 15
    elif 11 <= d <= 15:
        s += 5
    try:
        if (today - dt.datetime.strptime(job.get("pbancBgngYmd", ""), "%Y%m%d").date()).days <= 3:
            s += 10
    except Exception:
        pass
    return s


# ─────────────────────────── 사용 기록 (중복 소거) ───────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"account": ACCOUNT, "posts": []}


def save_state(state: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    state["posts"] = state["posts"][-500:]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


VIEWS_REFRESH_HOURS = 6
BORROW_MIN_DLEFT = 2          # 다른 계정 글을 가져올 때 마감까지 최소 남은 일수


def load_other_states() -> dict:
    """[2026-10-12] 다른 자동발행 계정 기록 {계정: posts} — 계정 간 중복 소거·터진 글 각색용"""
    out = {}
    if not os.path.isdir(STATE_DIR):
        return out
    for fn in sorted(os.listdir(STATE_DIR)):
        if not fn.endswith(".json") or fn == f"{ACCOUNT}.json":
            continue
        try:
            with open(os.path.join(STATE_DIR, fn), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("posts"), list) and d.get("account"):
            out[d["account"]] = d["posts"]
    return out


def refresh_my_views(state: dict) -> bool:
    """[2026-10-12] 최근 3주 내 내 글의 조회수를 기록 — 다른 계정이 '터진 글'을 고를 때 씀.
    threads_manage_insights 권한이 없는 토큰이면 조용히 건너뜀. 기록이 바뀌면 True"""
    uid, token = os.environ.get("THREADS_USER_ID"), os.environ.get("THREADS_TOKEN")
    if not uid or not token:
        return False
    now = dt.datetime.now(KST)
    last = state.get("views_refreshed_at")
    if last:
        try:
            if now - dt.datetime.strptime(last, "%Y-%m-%d %H:%M").replace(tzinfo=KST) < dt.timedelta(hours=VIEWS_REFRESH_HOURS):
                return False
        except Exception:
            pass
    cutoff = (now - dt.timedelta(days=21)).strftime("%Y-%m-%d %H:%M")
    targets = [p for p in state["posts"] if p.get("thread_id") and (p.get("at") or "") >= cutoff][-60:]
    n = 0
    for p in targets:
        try:
            r = requests.get(f"{THREADS_API}/{p['thread_id']}/insights",
                             params={"metric": "views", "access_token": token}, timeout=20)
            if not r.ok:
                if "permission" in r.text.lower() or r.status_code in (400, 403):
                    print(f"[참고] 조회수 권한 없음(threads_manage_insights) → 조회수 기록 건너뜀: {r.text[:150]}")
                    break
                continue
            data = r.json().get("data", [])
            v = data[0].get("values", [{}])[0].get("value") if data else None
            if v is None and data:
                v = (data[0].get("total_value") or {}).get("value")
            if v is not None:
                p["views"] = int(v)
                n += 1
        except Exception as e:
            print(f"[warn] 조회수 조회 실패: {e}")
            break
    state["views_refreshed_at"] = now.strftime("%Y-%m-%d %H:%M")
    print(f"내 글 조회수 기록: {n}/{len(targets)}건")
    return True


def borrow_candidates(others: dict, pool: list, mine_ids: set, mine_keys: set, today) -> list:
    """다른 계정이 올린 공고를 각색 후보로 — 내가 안 올린 공고 + 마감 2일 이상 + 카드(pool)에 살아 있는 공고.
    [2026-10-20] 계정 확장 대비: ① 조회수 기록이 있는 글을 전체 계정 통틀어 조회수 높은 순 (터진 글 먼저)
                 ② 조회수 기록이 없는 나머지 공고도 전부 점수순으로 이어서 — 계정이 늘어도 멈추지 않게
                 (이전: 계정별 '그 계정 평균 조회수 이상'만 → 계정마다 기준이 달라 들쭉날쭉, 터진 글이 바닥나면 각색 중단)
    공고마다 원글 1개 — 조회수가 가장 높은 글, 조회수가 없으면 가장 최근 글.
    반환: [(job, 원글 post, 계정)]"""
    by_id = {str(j["recrutPblntSn"]): j for j in pool}
    best = {}                                      # 공고 id → (job, 원글, 계정)
    for acct, posts in others.items():
        for p in posts:
            sid = str(p.get("id"))
            j = by_id.get(sid)
            if not j or sid in mine_ids or job_key(j) in mine_keys:
                continue
            if not j.get("always") and dday(j.get("pbancEndYmd", ""), today) < BORROW_MIN_DLEFT:
                continue
            cur = best.get(sid)
            key = ((p.get("views") or 0), p.get("at") or "")
            if cur is None or key > ((cur[1].get("views") or 0), cur[1].get("at") or ""):
                best[sid] = (j, p, acct)
    hot = [b for b in best.values() if (b[1].get("views") or 0) > 0]
    rest = [b for b in best.values() if not (b[1].get("views") or 0) > 0]
    hot.sort(key=lambda x: -(x[1].get("views") or 0))
    rest.sort(key=lambda x: -hot_score(x[0], today))
    return hot + rest


def job_key(j: dict) -> str:
    return norm_key(norm_inst(j.get("instNm"))) + "|" + norm_key(j.get("recrutPbancTtl"))


# [2026-10-07] 그룹 단위 중복 방지 — 계열사가 연달아 나가지 않게 (앞글자 일치)
GROUPS = {
    "한화": ["한화"], "효성": ["에이치에스효성", "효성"], "신세계": ["신세계", "이마트", "스타벅스"],
    "LS": ["엘에스", "LS"], "SK": ["에스케이", "SK"], "현대차": ["현대", "기아"], "삼성": ["삼성"],
    "LG": ["엘지", "LG"], "CJ": ["씨제이", "CJ"], "롯데": ["롯데"], "GS": ["지에스", "GS"],
    "두산": ["두산"], "포스코": ["포스코"], "HD": ["에이치디", "HD"], "KT": ["케이티", "KT"],
    "농협": ["농협", "엔에이치", "NH"], "호반": ["호반"], "DB": ["디비", "DB"], "하나": ["하나"],
    "신한": ["신한"], "KB": ["케이비", "KB"], "코오롱": ["코오롱"], "대한전선": ["대한전선"],
    "토스": ["토스", "비바리퍼블리카"],
    # [2026-10-14] 나라일터 — 같은 부처 소속(우체국 여러 곳 등)이 연달아 나가지 않게
    "우정": ["과학기술정보통신부우정사업본부"], "법무부": ["법무부"], "기상청": ["기상청"],
}
NOT_GROUP = ("엔에이치엔", "엘에스이")          # 이름만 비슷한 비계열사
PRIVATE_RATIO = float(os.environ.get("PRIVATE_RATIO", "0.2") or 0.2)   # 민간 비중 (기본 공공 8 : 민간 2)


# [2026-10-14] 나라일터 기관은 기록에 짧은 이름('진천우체국')으로 남아서 앞글자 일치가 안 됨 → 끝글자로도 묶음
GOV_SUFFIX = (("G:우정", ("우체국", "우편집중국", "우정청")),
              ("G:법무부", ("교도소", "구치소", "소년원", "보호관찰소", "교정청", "출입국외국인사무소", "출입국외국인청")),
              ("G:기상청", ("기상청", "기상지청", "기상위성센터")))


def group_key(name: str) -> str:
    n = norm_key(norm_inst(name))
    for g, suffixes in GOV_SUFFIX:
        if n.endswith(suffixes):
            return g
    if not n.startswith(NOT_GROUP):
        for g, prefixes in GROUPS.items():
            if any(n.startswith(px) for px in prefixes):
                return "G:" + g
    return n


def is_manual_id(pid) -> bool:
    """[2026-10-16] 수동 공고(manual_jobs.json, MN-)"""
    return str(pid).startswith("MN-")


def is_private_id(pid) -> bool:
    return str(pid).startswith(("WK-", "MN-"))      # 공채속보 + 수동 공고(토스 등) [2026-10-08]


def want_private_now(history) -> bool:
    """[2026-10-07] 최근 10건 중 민간이 목표 비율보다 적고, 직전 글이 민간이 아니면 이번엔 민간"""
    recent = history[-10:]
    if recent and is_private_id(recent[-1]["id"]):
        return False
    priv = sum(1 for p in recent if is_private_id(p["id"]))
    return priv < round(10 * PRIVATE_RATIO)


# [2026-10-12] 민간은 '누구나 아는 대기업'만 — 그룹(GROUPS 키) 또는 이름 포함
FAMOUS_GROUPS = {"삼성", "현대차", "SK", "LG", "롯데", "한화", "CJ", "포스코", "GS", "신세계",
                 "KT", "HD", "두산", "농협", "하나", "신한", "KB", "토스"}
FAMOUS_NAMES = ("네이버", "카카오", "쿠팡", "대한항공", "아시아나항공", "우리은행", "우리금융", "우리카드",
                "아모레퍼시픽", "오뚜기", "농심", "오리온", "하이브", "우아한형제들", "배달의민족", "당근",
                "엔씨소프트", "넥슨", "넷마블", "크래프톤", "셀트리온", "미래에셋", "한국투자증권", "키움증권",
                "에쓰오일", "S-OIL", "스타벅스", "무신사", "야놀자", "컬리", "빙그레", "매일유업", "풀무원",
                "동원", "교보", "메리츠", "한진", "효성", "삼양", "대한전선", "코웨이", "하이트진로", "SPC",
                "파리크라상", "이랜드", "현대백화점", "에이치디현대", "기아")

NOT_FAMOUS = ("굿네이버스",)                  # 이름에 대기업 단어가 들어간 다른 곳

_VIEWS = None


def views_of(job) -> int:
    """hiring03 본문 조회수 (views.json) — 실패하면 0"""
    global _VIEWS
    if _VIEWS is None:
        try:
            _VIEWS = requests.get(VIEWS_URL, timeout=20).json().get("views", {})
        except Exception as e:
            print(f"[참고] views.json 읽기 실패 → 조회수 가산 없이 진행 ({e})")
            _VIEWS = {}
    return int(_VIEWS.get(str(job.get("recrutPblntSn")), 0) or 0)


def hot_score(job, today) -> float:
    """[2026-10-12] 핫한 공고 우선: 기본 점수 + 조회수 가산 (20회당 1점, 최대 +60 — 카드 추천순과 같은 상한)"""
    return score(job, today) + min(views_of(job) / 20, 60)


def is_famous(job: dict) -> bool:
    if str(job.get("recrutPblntSn", "")).startswith("MN-"):     # 수동 공고 = 직접 고른 핫한 공고
        return True
    g = group_key(job.get("instNm"))
    if g.startswith("G:") and g[2:] in FAMOUS_GROUPS:
        return True
    name = norm_inst(job.get("instNm"))
    if name.startswith(NOT_FAMOUS):
        return False
    return name.startswith(FAMOUS_NAMES)          # 앞부분 일치 ('하이브리드…' 같은 오탐 방지)


def is_urgent_post(p: dict) -> bool:
    """[2026-10-19] 기록상 긴급형(⚠️ 마감) 글인지 — 2순위 마감 글 또는 긴급 유형 또는 ⚠️ 훅"""
    return bool(p.get("urgent")) or p.get("combo_cat") == "urgent" or (p.get("hook") or "").startswith("⚠")


def urgent_blocked(history) -> bool:
    """[2026-10-19] 최근 URGENT_WINDOW건 안에 긴급형이 URGENT_MAX개 이상이면 True → 이번 회차는 긴급형 금지"""
    recent = history[-URGENT_WINDOW:] if URGENT_WINDOW > 0 else []
    return sum(1 for p in recent if is_urgent_post(p)) >= URGENT_MAX


def repost_ok(sid: str, history, today) -> bool:
    """[2026-10-19] 내 계정에서 이 공고를 다시 올려도 되는지 — 총 REPOST_MAX번 미만 + 마지막 발행 후 REPOST_MIN_DAYS일 이상"""
    mine = [p for p in history if str(p.get("id")) == str(sid)]
    if not mine:
        return True
    if len(mine) >= REPOST_MAX:
        return False
    try:
        last = max(dt.datetime.strptime((p.get("at") or "")[:10], "%Y-%m-%d").date() for p in mine)
    except ValueError:
        return False
    return (today - last).days >= REPOST_MIN_DAYS


def pick_job(jobs, posts, state, today, exclude=None, others=None):
    """반환: (job, tier, 후보 수, borrow) — borrow는 다른 계정 원글 정보 (tier 4일 때만)
    tier: 1 신규 / 2 마감 임박 / 3 나머지 새 공고 / 4 다른 계정 터진 글 각색 / 5 내 글 재발행 [2026-10-15]"""
    history = state["posts"]
    others = others or {}
    my_ids = {str(p["id"]) for p in history}
    my_keys = {norm_key(norm_inst(p["instNm"])) + "|" + norm_key(p["title"]) for p in history}
    # [2026-10-12] 다른 계정이 올린 공고(같은 기관+같은 공고)도 '사용됨' — 같은 기관 다른 공고는 그대로 후보
    other_posts = [p for ps in others.values() for p in ps]
    used_ids = my_ids | {str(p["id"]) for p in other_posts}
    used_keys = my_keys | {norm_key(norm_inst(p.get("instNm"))) + "|" + norm_key(p.get("title")) for p in other_posts}
    recent_insts = {group_key(p["instNm"]) for p in history[-6:]}   # [2026-10-07] 그룹 단위
    recent_ids = {str(p["id"]) for p in history[-12:]}
    recent_ids_list = [str(p["id"]) for p in history[-12:]]
    exclude = exclude or set()
    live = [j for j in jobs if eligible(j, today) and str(j["recrutPblntSn"]) not in exclude]

    want_priv = want_private_now(history)
    n_priv = sum(1 for p in history[-10:] if is_private_id(p["id"]))
    pool = []
    def is_new(j):
        # [2026-10-20] 새 공고는 계정마다 한 번씩 다 올림 — '내 계정이 안 올린 공고'면 새 공고 (다른 계정이 올렸어도 OK)
        #              같은 날 다른 계정이 올린 공고는 아래 others_today에서 이미 빠짐 → 계정끼리 날짜만 다르게
        return str(j["recrutPblntSn"]) not in my_ids and job_key(j) not in my_keys

    def never_posted(j):                           # 아무 계정도 안 올린 공고 (로그·동점 정렬용)
        return str(j["recrutPblntSn"]) not in used_ids and job_key(j) not in used_keys

    if want_priv:
        pool = [j for j in live if is_private(j) and is_famous(j)]
        if not any(is_new(j) for j in pool):            # 대기업 재발행보다 공공 신규가 우선
            print("민간 차례지만 새 대기업 공고가 없어 공공으로")
            want_priv = False
    if not want_priv:
        # [2026-10-12] 공공 차례에 공공 신규가 없으면 민간으로 새지 않고 공공 인기순 재발행
        #              (이전엔 side()가 민간으로 넘겨서 민간이 연속 9건 나감)
        pool = [j for j in live if not is_private(j)] or [j for j in live if is_private(j) and is_famous(j)]
    print(f"이번 회차: {'민간(대기업)' if want_priv else '공공'} 차례 (최근 10건 중 민간 {n_priv}건, "
          f"목표 {int(PRIVATE_RATIO*100)}%) / 후보 {len(pool)}개")
    if not pool:
        return None, 0, 0, None

    # [2026-10-15] 순위: ① 신규(접수 시작 NEW_DAYS일 이내) ② 마감 임박(D-1~D-URGENT_DAYS) ③ 나머지 새 공고
    #              ④ 우리 다른 계정에서 터진 글 각색 ⑤ 내 글 재발행
    def opened_days(j):
        try:
            return (today - dt.datetime.strptime(j.get("pbancBgngYmd", ""), "%Y%m%d").date()).days
        except Exception:
            return 999

    def is_urgent(j):
        return not j.get("always") and 1 <= dday(j.get("pbancEndYmd", ""), today) <= URGENT_DAYS

    def posts_first(cands):
        """같은 순위 안에서 본문 있는 공고 → 본문 없는 공고, 나라일터(인원·학력 없음)는 맨 뒤 [2026-10-14]"""
        for c in ([j for j in cands if str(j["recrutPblntSn"]) in posts and not is_gojobs(j)],
                  [j for j in cands if not is_gojobs(j)],
                  cands):
            if c:
                return c
        return cands

    def choose(cands):
        cands = posts_first(cands)
        fresh = [j for j in cands if group_key(j["instNm"]) not in recent_insts] or cands
        fresh.sort(key=lambda j: hot_score(j, today), reverse=True)
        top = fresh[:5]
        return random.choices(top, weights=[max(hot_score(j, today), 1) for j in top], k=1)[0]

    # [2026-10-16] 0순위 수동 공고 — 공공/민간 차례·다른 계정 발행 여부와 상관없이 각 계정에 최소 1번
    #              (직전 글이 수동 공고면 이번 회차는 건너뛰어 수동 공고만 연달아 나가지 않게)
    manual_live = [j for j in live if is_manual_id(j["recrutPblntSn"]) and j.get("threads") is not False]   # "threads": false = 쓰레드 제외
    pool = [j for j in pool if j.get("threads") is not False]   # [2026-10-17] 토스 등 쓰레드 제외 공고는 일반 순위로도 안 나가게
    last_manual = bool(history) and is_manual_id(history[-1]["id"])
    # [2026-10-17] 같은 수동 공고는 같은 날 한 계정만 — 다른 계정이 오늘 올린 수동 공고는 오늘 건너뜀 (내일 이 계정 차례)
    # [2026-10-20] 일반 공고까지 확대 — 다른 계정이 오늘(KST) 올린 공고는 각색·마감 알림·재발행 모두 오늘은 안 올림
    today_s = today.isoformat()
    others_today = {str(p["id"]) for p in other_posts if (p.get("at") or "")[:10] == today_s}
    m_count = {}                                   # 수동 공고별로 지금까지 올린 계정 수 (적게 올라간 공고부터)
    for acc_posts in list(others.values()) + [history]:
        for sid in {str(p["id"]) for p in acc_posts if is_manual_id(p.get("id"))}:
            m_count[sid] = m_count.get(sid, 0) + 1
    if others_today:
        held = [j for j in manual_live if str(j["recrutPblntSn"]) in others_today]
        if held:
            print(f"수동 공고: 다른 계정이 오늘 올린 {len(held)}개는 내일로 미룸 — " + ", ".join(str(j["recrutPblntSn"]) for j in held))
        manual_live = [j for j in manual_live if str(j["recrutPblntSn"]) not in others_today]
        n_before = len(pool)
        pool = [j for j in pool if str(j["recrutPblntSn"]) not in others_today]   # 마감 알림·각색·재발행으로도 안 나가게
        if n_before > len(pool):
            print(f"다른 계정이 오늘 올린 공고 {n_before - len(pool)}개는 오늘 후보에서 제외")
    # [2026-10-17] 수동 공고 마감 임박(D-1~3)은 전체 계정 통틀어 ⚠️ 글 1번 — 이미 누가 올렸으면 그 공고는 끝
    def m_is_urgent(j):
        return not j.get("always") and 1 <= dday(j.get("pbancEndYmd", ""), today) <= MANUAL_URGENT_DAYS
    all_urgent_done = {str(p["id"]) for p in list(history) + other_posts if p.get("urgent") and is_manual_id(p.get("id"))}
    m_closed = [j for j in manual_live if m_is_urgent(j) and str(j["recrutPblntSn"]) in all_urgent_done]
    if m_closed:
        print(f"수동 공고: 마감 임박 글이 이미 나간 {len(m_closed)}개는 더 안 올림 — " + ", ".join(str(j["recrutPblntSn"]) for j in m_closed))
    manual_live = [j for j in manual_live if j not in m_closed]
    pool = [j for j in pool if not (is_manual_id(j["recrutPblntSn"]) and m_is_urgent(j))]   # 마감 임박 수동 공고는 아래 0순위에서만
    if manual_live and not last_manual:
        m_urgent = [j for j in manual_live if m_is_urgent(j)]
        m_new = [j for j in manual_live if str(j["recrutPblntSn"]) not in my_ids and job_key(j) not in my_keys]
        print(f"수동 공고: 진행 중 {len(manual_live)} / 내 계정 미발행 {len(m_new)} / 마감 임박 알림 대기 {len(m_urgent)}")
        if m_urgent:
            return choose(m_urgent), 2, len(m_urgent), None      # 마감 임박 → ⚠️ 마감 글 (tier 2 처리 그대로)
        if m_new:                                  # 최근에 넣은 수동 공고부터 (접수 시작일 최신순 → 본문 있는 것 → 점수)
            m_new.sort(key=lambda j: (-m_count.get(str(j["recrutPblntSn"]), 0), j.get("pbancBgngYmd") or "",
                                      str(j["recrutPblntSn"]) in posts, hot_score(j, today)), reverse=True)
            fresh_m = [j for j in m_new if group_key(j["instNm"]) not in recent_insts] or m_new
            return fresh_m[0], 0, len(m_new), None
    elif manual_live:
        print("수동 공고: 직전 글이 수동 공고라 이번 회차는 다른 공고")

    new = [j for j in pool if is_new(j)]
    print(f"내 계정 안 올린 공고 {len(new)}개 (아무도 안 올린 {sum(1 for j in new if never_posted(j))} · "
          f"다른 계정만 올린 {sum(1 for j in new if not never_posted(j))})")
    tier1 = [j for j in new if opened_days(j) <= NEW_DAYS and not is_urgent(j)]
    # 마감 임박: 안 올린 공고 + 내가 올렸던 공고(마감 알림으로 아직 안 올린 것만). 다른 계정이 올린 공고는 제외(중복 방지)
    urgent_done = {str(p["id"]) for p in history if p.get("urgent")}
    urgent_new = [j for j in new if is_urgent(j)]
    urgent_mine = [j for j in pool if is_urgent(j) and not is_new(j)
                   and (str(j["recrutPblntSn"]) in my_ids or job_key(j) in my_keys)
                   and str(j["recrutPblntSn"]) not in urgent_done and str(j["recrutPblntSn"]) not in recent_ids
                   and repost_ok(j["recrutPblntSn"], history, today)]   # [2026-10-19] 재발행 간격·횟수 제한
    # 안 올린 공고가 나라일터(인원·학력 없음)뿐이면 내가 올렸던 본문 있는 공고의 마감 알림이 더 나음 → 합쳐서 posts_first로 고름
    tier2 = urgent_new + urgent_mine
    tier3 = [j for j in new if j not in tier1 and not is_urgent(j)]

    recent_n = history[-max(URGENT_EVERY - 1, 0):] if URGENT_EVERY > 1 else []
    urgent_due = not any(p.get("urgent") for p in recent_n)
    u_block = urgent_blocked(history)              # [2026-10-19] 최근 긴급형이 많으면 마감 글은 맨 마지막 수단으로
    print(f"순위별 후보: 신규 {len(tier1)} / 마감 임박 {len(tier2)} (안 올린 {len(urgent_new)}·알림 {len(urgent_mine)}) "
          f"/ 나머지 {len(tier3)}" + (" — 마감 임박 차례" if tier2 and tier1 and urgent_due and not u_block else "")
          + (f" — 최근 {URGENT_WINDOW}건에 긴급형 {URGENT_MAX}개 이상이라 마감 글은 뒤로" if u_block and tier2 else ""))

    if tier2 and not u_block and (urgent_due or not tier1):
        return choose(tier2), 2, len(tier2), None
    if tier1:
        return choose(tier1), 1, len(tier1), None
    if tier3:
        return choose(tier3), 3, len(tier3), None

    # [2026-10-12] 새 공고 소진 → ④ 우리 다른 계정 글을 가져와 각색 (조회수 높은 순 → 나머지 점수순) [2026-10-20]
    borrows = borrow_candidates(others, pool, my_ids, my_keys, today)
    if borrows:
        fresh_b = [b for b in borrows if group_key(b[0]["instNm"]) not in recent_insts] or borrows
        j, src, acct = fresh_b[0]
        return j, 4, len(borrows), {"account": acct, "hook": src.get("hook") or "", "closer": src.get("closer") or "",
                                    "cat": src.get("combo_cat"), "views": src.get("views"),
                                    "thread_id": src.get("thread_id")}

    # ⑤ 그래도 없으면 내 계정이 올렸던 공고만 재발행 (다른 계정 공고를 그대로 가져오면 중복)
    #    [2026-10-19] 같은 공고는 REPOST_MIN_DAYS일 간격·총 REPOST_MAX번까지만 — 사골 방지
    mine_all = [j for j in pool if str(j["recrutPblntSn"]) in my_ids or job_key(j) in my_keys]
    mine = [j for j in mine_all if repost_ok(j["recrutPblntSn"], history, today)]
    if len(mine) < len(mine_all):
        print(f"재발행 제한: {len(mine_all) - len(mine)}개 공고는 최근에 올렸거나 이미 {REPOST_MAX}번 올려서 제외")
    if not mine:
        if tier2:                                  # [2026-10-19] 긴급형 제한 중이어도 올릴 게 마감 글뿐이면 발행
            print("다른 후보가 없어 마감 임박 글로 발행")
            return choose(tier2), 2, len(tier2), None
        return None, 0, 0, None
    repeat = [j for j in mine if str(j["recrutPblntSn"]) not in recent_ids] or mine

    def times(j):
        return sum(1 for p in history if str(p["id"]) == str(j["recrutPblntSn"]))

    def last_at(j):
        ts = [p["at"] for p in history if str(p["id"]) == str(j["recrutPblntSn"])]
        return max(ts) if ts else ""

    repeat.sort(key=lambda j: (                    # [2026-10-12] 인기순 재발행 — 2번 이상 올린 공고만 뒤로
        times(j) >= 2,
        str(j["recrutPblntSn"]) not in posts,
        -hot_score(j, today),
        last_at(j),
    ))
    fresh = [j for j in repeat if group_key(j["instNm"]) not in recent_insts] or repeat
    return fresh[0], 5, len(repeat), None


# ─────────────────────────── 본문 글에서 팩트 보강 ───────────────────────────
def fetch_post_text(post: dict) -> str:
    html = ""
    try:
        feed = f"https://hiring03.ddolbestory.com/feeds/posts/default/{post['postId']}?alt=json"
        r = requests.get(feed, timeout=20)
        if r.ok:
            html = r.json()["entry"]["content"]["$t"]
    except Exception:
        pass
    if not html:
        try:
            r = requests.get(post["url"], timeout=20)
            if r.ok:
                html = r.text
        except Exception:
            return ""
    html = re.sub(r"(?is)<(script|style|ins|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)</?(span|b|strong|em|a)\b[^>]*>", "", html)   # 강조 태그는 줄바꿈 없이 (문장 쪼개짐 방지)
    text = re.sub(r"(?s)<[^>]+>", "\n", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z#0-9]+;", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return clean_post_text(text)[:4000]


def clean_post_text(text: str) -> str:
    """같은 기관 다른 공고 연봉(신입 초봉)·다른 기관 공고가 섞이지 않게 정리"""
    # '함께 보면 좋은 공고' 본문 섹션부터 끝까지 제거 (목차에도 같은 문구가 있어 마지막 것 기준)
    k = text.rfind("함께 보면 좋은 공고")
    if k > len(text) // 3:
        text = text[:k]
    # 연봉 표: "신입 초봉 / 직원 평균 연봉 / 약 A / 약 B" → "직원 평균 연봉: 약 B"
    text = re.sub(r"신입 초봉\n직원 평균 연봉\n[^\n]*\n([^\n]*)", r"직원 평균 연봉: \1", text)
    # 인트로: "신입 초봉 약 4,300만원, " 제거
    text = re.sub(r"신입 초봉 약 [\d,]+만원,?\s*", "", text)
    text = "\n".join(l for l in text.split("\n") if "초봉" not in l)
    # [2026-10-06] 공채속보 학력 값 오류(석사·박사만 표기) 문구 제거 — 학력은 '지원 자격 상세' 원문 문장으로만 판단
    text = re.sub(r"공고 데이터 기준(으로)? 학력 조건은 「[^」]*」(이에요|예요)?[,.]?\s*", "", text)
    # [2026-10-12] 학력 미확인 공고 안내 문구(일반론)가 학력 언급을 유도하지 않게 제거
    text = re.sub(r"학력 조건은 원문 공고의 응시 자격 칸에 나와 있어요\.[^\n]*", "", text)
    text = re.sub(r"학력 조건은 「(석사|박사)」(이에요|예요)?\.?", "", text)
    text = re.sub(r"지원 자격:\s*(석사|박사)\s*·\s*", "지원 자격: ", text)
    text = re.sub(r"✅\s*(석사|박사)", "", text)
    text = "\n".join(l for l in text.split("\n") if not re.fullmatch(r"\s*(석사|박사)\s*", l))
    return text


def edu_section(post_text: str) -> str:
    """본문 발췌에서 기업이 직접 쓴 '지원 자격 상세' 부분만"""
    k = post_text.find("지원 자격 상세")
    return post_text[k:k + 700] if k >= 0 else ""


def private_edu_ok(post_text: str) -> bool:
    """[2026-10-06] 민간 공고: 일반 취준생이 지원 가능한 학력(학력무관·고졸·학사 등)이 원문에 있는지"""
    sec = edu_section(post_text or "")
    if not sec:
        return False
    return bool(re.search(r"학력\s*(및\s*경력\s*)?(무관|제한\s*없)|고졸|고등학교|학사|대졸|전문학사|초대졸|4년제|2~3년제|대학(교)?\s*(졸업|재학)", sec))


OPEN_FACT_RE = r"학력\s*(및\s*경력\s*)?무관|학력·?나이·?경력\s*제한|자소서\s*(평가\s*)?(없|폐지)|나이\s*제한\s*(없|폐지)|누구나\s*지원"


def has_open_fact(job: dict, post_text: str) -> bool:
    """[2026-10-06] '포기 방지'형을 쓸 근거 — 모두에게 열린 조건(학력무관·자소서 없음 등)이 있는지"""
    if is_gojobs(job):                            # [2026-10-14] 나라일터는 학력 확인 불가 → 열린 조건 근거로 쓰지 않음
        return False
    return "무관" in (job.get("acbgCondNmLst") or "") or bool(re.search(OPEN_FACT_RE, post_text or ""))


# ─────────────────────────── 후킹 유형 (지침서 v3.5 + 2026-10-06) ───────────────────────────
# 카테고리: person(인물형 15%) / monologue(1인칭독백 35%) / fact(팩트충격 20%) / urgent(긴급 15%) / sniper(특가스나이퍼 15%)
# [v3.5] 노잼 대부분이 인물형에서 나와 인물 30%→15%, 1인칭 독백 20%→35%
#        점심시간 동료 장면·vs 비교 조합 삭제
# [2026-10-06] 특가 '포기 방지'와 '바보 손실' 분리 — 포기 방지는 열린 조건(need_open)이 있는 공고에서만
COMBOS = [
    # 인물 대화형 15% — 진짜 있을 법한 오해 + 진짜 피식할 때만. 안 나오면 담백한 1인칭으로 대체
    {"cat": "person", "person": "부모님", "structure": "오해→부정반응→역전", "emoji": "📍",
     "desc": "기관 업무를 일상 한 마디로 재정의 → 부모님의 진짜 오해(사기치지 말라고) → 공고 보여줬더니 전환. "
             "오해는 요즘 기준으로 현실적이어야 함('차에 컴퓨터가 왜 있냐' 같은 비현실 반응 금지). 피식 포인트가 없으면 쓰지 말 것"},
    {"cat": "person", "person": "여자친구", "structure": "오해→부정반응→역전", "emoji": "📍",
     "desc": "기관 업무 한 마디 재정의 → 여자친구 진짜 오해(사기꾼이냐고 차일 뻔함) → 공고 보여줬더니 전환. "
             "오해는 요즘 기준으로 현실적이어야 함. 피식 포인트가 없으면 쓰지 말 것"},
    # 1인칭 독백형 35% — 상황극 없이 감정 하나. 도로공사 베스트(31만 조회) 계열
    {"cat": "monologue", "person": "본인", "structure": "포기→의외의 역전", "emoji": "📍",
     "desc": "어차피 안 되겠지 싶어서 그냥 넣어봤는데 / 조건 다시 보니까 나도 되는 자리였음 — 첫 줄 포기, 둘째 줄 역전. "
             "역전까지 반드시 훅 2줄 안에서 끝낸다(실패 상태로 끝나는 훅 금지). 역전 근거는 모두에게 열린 조건(학력무관 등)이나 "
             "브랜드·연봉 같은 매력이어야 하고, '전문학사도 됨'처럼 특정 학력 허용을 근거로 쓰지 않는다"},
    {"cat": "monologue", "person": "본인", "structure": "조용히 넣었다", "emoji": "📍",
     "desc": "아무한테도 말 안 하고 조용히 넣었다 — N명이면 해볼 만하다고 봤음. 감정 하나로 담백하게 ('합격하면 그때 말하려고'는 고정 클로저라 금지). "
             "최근 글에 같은 문장 틀이 있으면 표현을 바꿀 것"},
    {"cat": "monologue", "person": "본인", "structure": "다짐·선언", "emoji": "📍",
     "desc": "이번엔 진짜 넣는다 / ○○ 포기하고 이거 하나만 파기로 했음 — 취준생 누구나 하는 결심"},
    {"cat": "monologue", "person": "본인", "structure": "늦게 안 손해", "emoji": "📍",
     "desc": "이 공고 마감 직전에 알았으면 진짜 억울할 뻔 / 작년에 이거 몰라서 못 넣었음"},
    # 팩트 충격형 20% — 숫자를 포장하지 말고 그대로 세게
    {"cat": "fact", "person": "—", "structure": "숫자·규모 충격", "emoji": "📍",
     "desc": "역대 최대 N명인데 학력무관 / 평균연봉 N만 회사가 신입을 N명 뽑음 — 'N개 중 1개' 같은 숫자 포장 금지. "
             "민간이면 평균연봉·브랜드로"},
    {"cat": "fact", "person": "—", "structure": "조건 나열", "emoji": "📍",
     "desc": "정규직 + 학력무관 + N명 — 이 조합이 한 공고에 다 있음. 넣을 이유만 나열하고 학력 하한·어학·전형 단계는 나열 금지. "
             "최근 글에 같은 둘째 줄이 있으면 둘째 줄을 새로 쓸 것"},
    # 긴급형 15%
    {"cat": "urgent", "person": "—", "structure": "경고", "emoji": "⚠️",
     "desc": "N명 학력무관인데 안 넣는 게 사기임 / 취준생 심장 약하면 스크롤 멈춰 — 훅에 이 공고의 알맹이(고용형태·학력무관·인원·연봉·하는 일·근무지 중 1개 이상)를 반드시 넣을 것"},
    {"cat": "urgent", "person": "—", "structure": "시한폭탄 / 막차", "emoji": "⚠️",
     "desc": "D-N이라 이번 주 안에 넣어야 됨 — 마감만 말하는 훅 금지('접수 마감이 코앞', '이번 주 막차' 같은 빈 훅 X). "
             "훅에 이 공고의 알맹이(고용형태·학력무관·인원·연봉·하는 일·근무지·기관 성격 중 1개 이상)를 마감과 함께 넣을 것"},
    # 특가스나이퍼형 15% — 비교(vs) 금지, 읽는 사람 상황을 바로 저격
    {"cat": "sniper", "person": "—", "structure": "포기 방지", "emoji": "📍", "need_open": True,
     "desc": "스펙 없어서 공기업 접은 사람 다시 펴 — 포기를 뒤집을 열린 조건(학력무관·자소서 없음 등)을 리스트에 반드시 넣을 것. "
             "근거 없이 '다시 봐'만 하면 안 됨. 조건을 겹겹이 단 꼬인 문장 금지"},
    {"cat": "sniper", "person": "—", "structure": "바보 손실", "emoji": "📍",
     "desc": "이거 안 넣는 게 손해가 아니라 바보임 — 근거는 강한 팩트(대규모 인원·학력무관·평균연봉·브랜드). "
             "최근 글에 같은 문장 틀이 있으면 표현을 바꿀 것"},
    {"cat": "sniper", "person": "—", "structure": "상황 저격", "emoji": "📍",
     "desc": "지방 사는 취준생인데 이거 모르면 손해 / 스펙 없는 신입이면 이건 꼭 봐 — A vs B 비교 금지. "
             "특정 학력 집단(전문대생 등)을 지목하지 말 것"},
]

# 유형별 가중치 (비중 반영) — sniper는 조합이 3개라 10으로 맞춤 (전체 비중 유지)
CAT_WEIGHTS = {"person": 15, "monologue": 35, "fact": 20, "urgent": 15, "sniper": 10}


def pick_combo(state, d_left: int, open_fact: bool = True):
    recent = state["posts"][-10:]
    recent_idxs = {p.get("combo_idx") for p in recent if p.get("combo_idx") is not None}
    recent_cats = [p.get("combo_cat") for p in recent[-2:] if p.get("combo_cat")]

    # 최근 2건 중 인물형이 하나라도 있으면 비인물형 강제 (인물 상황극 연속 금지)
    force_nonperson = "person" in recent_cats
    no_urgent = urgent_blocked(state["posts"])    # [2026-10-19] 최근 긴급형이 많으면 긴급 유형 제외

    pool = []
    for i, c in enumerate(COMBOS):
        if i in recent_idxs:
            continue
        if force_nonperson and c["cat"] == "person":
            continue
        if no_urgent and c["cat"] == "urgent":
            continue
        if d_left > 7 and c["structure"] in ("시한폭탄 / 막차",):
            continue
        if c.get("need_open") and not open_fact:    # [2026-10-06] 근거 없는 포기 방지 금지
            continue
        pool.append(i)

    if not pool:
        pool = [i for i in range(len(COMBOS)) if open_fact or not COMBOS[i].get("need_open")]
        if force_nonperson:
            pool = [i for i in pool if COMBOS[i]["cat"] != "person"] or pool
        if no_urgent:
            pool = [i for i in pool if COMBOS[i]["cat"] != "urgent"] or pool

    # 가중 랜덤 — 유형별 비중 반영
    weights = [CAT_WEIGHTS.get(COMBOS[i]["cat"], 10) for i in pool]
    idx = random.choices(pool, weights=weights, k=1)[0]
    return idx, COMBOS[idx]


# ─────────────────────────── Claude 프롬프트 (v3.4) ───────────────────────────
SYSTEM_PROMPT = """너는 한국 채용정보 쓰레드 계정의 후킹글 작가다. 아래 규격을 100% 지킨다.

[최상위 원칙 — v3.5]
- 웃길 거면 확실하게, 아니면 담백하게. 모든 글이 웃길 필요는 없다.
  웃기는 컨셉을 쓸 거면 "실제로 있을 법한 장면 + 읽고 진짜 피식하는 포인트"가 둘 다 있어야 한다.
  어설프게 웃기려다 실패한 글이 최악이다. 확신이 없으면 담백한 1인칭 감정 한 줄로 간다.
- 공감 우선. 읽는 사람이 "내 얘기다" 느껴야 한다. 공고문 절차 디테일로 훅을 만들지 않는다.
- 과장은 OK, 거짓은 NO. 훅·클로저는 과장 가능. 리스트 5개는 [공고 데이터]/[본문 발췌]에 있는 팩트만.
- 훅은 화면상 2줄 안에 끝낸다: 최대 2줄, 한 줄 26자 이내(이모지 제외). 질질 끌지 않는다.
- 클로저도 매번 다르게. 최근 글과 장면·인물·문장 구조가 겹치면 안 된다.
- 훅은 '넣을 이유'만 말한다. 장벽(전형 단계·스펙·학력 하한)을 드러내는 순간 스크롤이 넘어간다.
- 모두에게 열린 말로 쓴다. 조건도 언어도 — 특정 학력 집단을 지목하지 않고, 업계를 모르는 사람도 한 번에 알아듣게.

[포맷]
- 훅: 최대 2줄, 줄당 26자 이내. 맨 앞에 지정된 이모지(📍 또는 ⚠️) 1개. 기관명·줄임말 절대 넣지 않음.
- 리스트: 정확히 5개. 1번은 반드시 '기관(기업) 정식명칭' 작은따옴표 + 핵심 팩트 1개(인원·고용형태 정도).
  필수 팩트: 고용형태, 학력조건, 마감일. 지역 제한(거주·연고자 한정)이 있으면 반드시 명시. 각 항목 짧게 한 줄.
  한 항목에 팩트 1개. 같은 팩트를 두 항목에 반복 금지 — 학력은 한 항목에만, 날짜(마감일·접수기간)는 5번 한 곳에만.
  5개가 모두 서로 다른 정보여야 함 (1번에 여러 팩트를 몰아넣고 아래에서 다시 쓰지 말 것).
- 클로저: 1줄. 과장 OK. 인물형이면 훅과 스토리 연결.
- 반말 구어체. 링크·해시태그 금지. 훅 앞 이모지 외 이모지 금지.

[제외 패턴 23종 — 절대 사용 금지]
1. 질문유도형 ("~인지 알아?")
2. 일상 스토리형 ("전화/신고했더니 공기업이었음")
3. 생활 연결형 ("~할 때 신고하는 곳 → 그 기관이 사람 뽑음", "알고 보니 이 공단이")
4. 비교형 ("A vs B", "서울 월세 80 vs 지방 연봉") — 상황 저격에서도 비교 금지
5. 어린 시절 연결형 ("기차 좋아하던 7살의 나")
6. 오해 없는 질문형 반응 ("LH냐?" → "좋은 데네")
7. 기관 업무 프로세스 설명형 ("신고하면→조사해서→퇴출시키는 곳")
8. 정보 전달형 동료 멘트 ("~하는 공공기관 있대")
9. 잔소리·말장난 농담형 (아빠 "전기세 아끼라는 잔소리 하는 직업이 어딨냐고 웃음")
10. "그거 하려고 대학 보냈냐" 무시 → 연봉 듣고 태도 바뀜 (보일러 기사, 사자 밥, 두꺼비집 출장직)
11. 점심시간 동료 장면 (점심에 동료가 지원서 제출 누르는 거 봄) — 도입부로 금지
12. 설명문 재정의 ("에너지 아끼는 거 관리하는 데", "땅 주인 가려주는 데", "병원 나무 다듬고 보일러 고치는 데")
13. 절차 디테일형 (등기우편 접수, 수입인지 5천원)
14. 데이터 빈칸 소재형 ("학력 조건 칸이 '공고 참조'라고만 써있음", "조건란에 아무것도 없음")
15. 숫자 포장형 정보 ("우리나라 전기 10개 중 1개 만드는 공기업이")
16. 학력 하한 지목형 ("전문학사도 지원 가능이었음", "4년제 아니어도", "대졸 공채는 못 넣는 줄 알았는데")
    — 특정 학력을 지목하면 대상자는 불편하고 나머지는 남 얘기. 학력은 '학력무관'처럼 모두에게 열릴 때만 훅 소재
17. 장벽 소재형 — 전형 단계 수("전형이 무려 6단계"), 면접 횟수, 인적성·코딩테스트·AI면접, 어학 점수(토익·오픽 — 높든 낮든),
    학점을 훅·클로저 소재로 쓰지 않는다
18. 부정 종결 훅 ("이력서 칸마다 조건 안 맞아서 / 못 넣은 공고만 쌓여있었음") — 훅이 실패·포기 상태로 끝나면 안 된다.
    포기→역전은 역전까지 2줄 안에 보여준다
19. 전문 용어·약어·내부자 소재 ("코테", "과테", "스택", "백준 300문제", "MD", "PJT") — 업계를 모르는 사람도 한 번에 알아듣는 말만
20. 비현실적 오해 ("차에 컴퓨터가 왜 있냐") — 요즘 기준으로 말이 안 되는 반응은 웃기지 않고 어색하다
21. 근거 없는 포기 방지 ("~포기했으면 다시 봐"인데 리스트에 포기를 뒤집을 팩트가 없음)
22. 꼬인 문장 ("옷 좋아하는 거 말고 내세울 게 없어서 / 패션 회사 포기했으면 다시 봐") — 조건이 겹겹이라 한 번에 안 읽힘
23. 생활 민원 오해형 인물 대화 [2026-10-19] — 전화번호·동네 민원·생활 부탁 수준의 뻔한 오해 + 걱정·부탁·칭찬 같은 밋밋한 반응
    ("1366 들어간다" → "119랑 헷갈려서 불 끄러 가냐고 함", "구 공단 들어간다" → "주민센터에서 등본 떼주는 거냐고 함",
     "병원비 심사하는 데 간다" → "다니는 병원 비싸다고 거기부터 보라고 함") — 누구나 예상하는 오해라 피식 포인트가 없음

[인물 대화형 — 쓸 거면 이 수준만]
기관 업무를 일상 한 마디로 재정의했을 때 생기는 "진짜 오해 + 리얼한 부정 반응 → 역전".
OK: "나 돈 찍는 데 취직한다" → "사기치지 말라고" (조폐공사) / "우리 울산 갈까?" → "미쳤냐고" (에너지공단)
NG: 밋밋한 질문("어딘데?") → 밋밋한 긍정("좋은 데네"), 억지 말장난, 무시하다 연봉 듣고 태도 바뀜,
    번호·주민센터·병원비 같은 생활 민원 오해 → 걱정·부탁·칭찬 반응(23번). 확실히 웃기지 않으면 인물형 대신 1인칭으로.

[검증된 베스트]
(담백 — 1인칭 감정 하나, 조회 31만)
📍어차피 안 되겠지 싶어서 그냥 넣어봤는데
서류 붙고 조건 다시 보니까 나도 되는 자리였음
1. '한국도로공사' 안전순찰원 43명 채용
(…리스트 생략)
포기하려던 자리가 정년 보장 무기계약직이었던 거임

(웃김 — 진짜 오해, 조회 50만)
📍엄마한테 "나 돈 찍는 데 취직한다" 했더니
사기치지 말라고 하길래 공고 보여줬음
1. '한국조폐공사' 57명 정규직 채용
2. 화폐·여권·신분증 만드는 공기업
3. 학력 안 봄 - 누구나 지원 가능
4. 대전·서울·경산·부여 배치
5. 10/2 마감 - 아직 열흘 남음
공고 보더니 본인도 넣겠다고 함

(경고 — 팩트가 셀 때 한 줄, 조회 39만)
⚠️취준생 심장 약하면 스크롤 멈춰
1. '한국토지주택공사' 235명 정규직
2. 서류에서 자소서 평가 아예 없앰
3. 학력·나이·경력 제한 전부 없음
4. 고졸 전형 24명 별도 운영
5. 접수 9월 29일 마감
자소서 없는 235명 공채는 다음에 없음

[실패 사례 — 이렇게 쓰면 안 됨]
(조회 186) 📍대졸 공채는 못 넣는 줄 알았는데 / 전문학사도 지원 가능이었음 → 학력 하한 지목 (16)
(망함) 📍서류만 통과하면 끝인 줄 알았는데 / 전형이 무려 6단계였음 → 장벽을 훅으로 드러냄 (17)
(조회 810) 📍이력서 칸마다 조건 안 맞아서 / 못 넣은 공고만 쌓여있었음 → 실패 상태로 끝남 (18)
   같은 기관 '어차피 안 되겠지 싶어서 그냥 넣어봤는데 / 서류 붙고 조건 다시 보니까 나도 되는 자리였음'은 31만
(어색) 📍대기업 공채는 토익 만점자만 / 붙는 줄 알고 그냥 포기했었음 → 어학 점수 소재 + 체감상 대기업 아닌 곳을 '대기업'이라 부름

[팩트 규칙]
- 고용형태가 여러 개면 데이터 그대로 반영.
- 연봉은 [공고 데이터]/[본문 발췌]에 있는 '직원 평균 연봉'·'공고 제시 연봉'만. 신입 초봉은 쓰지 않는다.
  평균 연봉은 전 직원 평균이지 신입 초봉이 아님. 다른 공고·다른 기관 연봉을 끌어오지 않는다.
- 빈 값('공고 참조', '기타')은 리스트에 쓰지 않는다. 다른 팩트로 채운다.
- 학력조건은 '지원 가능한 최소 학력'이다. 값이 여러 개면 가장 낮은 것 기준으로 "고졸 이상", "대졸 이상"처럼 쓴다.
- 업무협력직·업무직·공무직·영선·조경 등은 경비·시설·청소 직무일 수 있다 → 사무직처럼 쓰지 않는다.
- "필기 없음", "자소서 없음" 같은 표현은 데이터에 있을 때만.
- 민간 기업 공고([공고 데이터]에 '기업구분'이 있음)는 공기업이 아니다: '공기업', '정년 보장', '블라인드' 표현 금지.
  '대기업'이라는 말은 기업구분이 '민간 대기업'일 때만 쓴다. 중견기업을 대기업처럼 쓰지 않는다.
  인원 대신 모집분야·전형 단계·근무지·평균연봉(있을 때)으로 리스트를 채운다.
  단, 전형 단계는 리스트에만 둘 수 있고 훅·클로저 소재로는 쓰지 않는다.
  [2026-10-16] 학력(학사·대졸·4년제·졸업예정)과 어학(토익·오픽·토스·HSK·JLPT) 조건은 훅·리스트·클로저 어디에도 쓰지 않는다 (진입장벽).
  '대기업'은 누구나 이름을 아는 그룹사(삼성·현대·SK·LG·롯데·신세계·한화·LS·CJ 등) 계열일 때만 훅에 쓴다.
  그 외에는 '증권사', '패션 회사'처럼 업종으로 부른다. 그룹 계열이면 리스트 2번쯤에 'OO그룹 계열사'를 적어준다.
  민간 공고 훅의 무기: 브랜드 인지도, 평균 연봉, 하는 일(쉬운 말로), 열린 직무, 입사 시기·근무지.
- 민간 공고는 학력·어학 조건을 글에 쓰지 않는다 (위 규칙). 공공기관·공무직의 '학력무관'은 그대로 무기로 쓴다.

[고정 클로저 금지]
"세 번 확인했는데 진짜임", "모르는 사람이 많을수록 경쟁률은 낮음", "넘기려다 공고 열어본 사람이 붙는 거임",
"말하고 싶으면 일단 넣어야 됨", "합격하면 그때 말하려고", "동료는 이미 넣었고 나만 안 넣었음"

[출력]
설명 없이 JSON 객체 하나만 출력. 코드블록 금지.
후보 4개를 서로 다른 방향으로 쓴다: 2개는 지정된 유형대로, 2개는 담백한 훅(웃기려 하지 않는 1인칭 감정·팩트·경고 중 지정 유형과 다른 것).
{"candidates": [
  {"type": "funny 또는 plain", "cat": "person|monologue|fact|urgent|sniper", "emoji": "📍 또는 ⚠️",
   "hook": "훅(줄바꿈은 \\\\n, 최대 2줄)", "items": ["1번", "2번", "3번", "4번", "5번"], "closer": "클로저 1줄"}
]}
items 각 원소에는 번호("1.")를 붙이지 말 것. type은 웃기려고 쓴 훅이면 funny, 아니면 plain.
"""

JUDGE_PROMPT = """너는 한국 쓰레드(Threads) 채용 계정의 편집장이다. 후킹글 후보를 냉정하게 채점한다.

채점 기준 (각 0~10):
- relate: 취준생이 "내 얘기다" 느끼나
- curious: 리스트를 끝까지 읽고 싶어지나
- fresh: [최근 발행 훅·클로저]와 장면·인물·문장 구조가 안 겹치나
- funny: type이 funny일 때만 — 실제로 있을 법한 장면인가 + 읽고 진짜 피식하나. 억지 상황극·말장난·무시하다 태도 바뀜·설명 같은 재정의는 0~3점

규칙:
- type이 funny인데 funny가 7점 미만이면 total에서 15점을 뺀다 (어설프게 웃긴 글은 담백한 글보다 나쁘다).
- 제외 패턴은 **훅과 클로저에만** 적용한다. 훅·클로저에 점심시간 동료, vs 비교, 데이터 빈칸, 숫자 포장("10개 중 1개"류),
  절차 디테일(등기우편·수입인지처럼 접수 절차를 소재로 삼음), 대학 보냈냐 무시형이 보이면 total 0.
- [2026-10-06] 훅·클로저가 아래에 해당해도 total 0:
  학력 하한 지목(전문학사·4년제 아니어도), 장벽 소재(전형 단계 수·면접 횟수·인적성·코딩테스트·어학 점수·학점),
  실패·포기 상태로 끝나는 훅(2줄 안에 반전 없음), 전문 용어·약어(코테·스택·MD 등), 요즘 기준 비현실적인 오해,
  리스트에 근거 없는 '다시 봐', 한 번에 안 읽히는 꼬인 문장, 체감상 대기업이 아닌 곳을 '대기업'이라 부름.
- relate는 '업계를 모르는 취준생도 한 번에 알아듣고 자기 얘기로 느끼나' 기준. 특정 집단만 대상으로 좁히면 감점.
- 리스트 5개는 팩트 칸이다. 리스트에 전형 단계·연봉·인원·마감일 같은 숫자와 절차 정보가 있는 건 정상이며 감점하지 않는다.
- total = relate + curious + fresh (+ funny, funny 타입만) 에서 규칙 적용.

설명 없이 JSON만: {"scores": [{"i": 0, "relate": 0, "curious": 0, "fresh": 0, "funny": null, "total": 0, "why": "한 줄"}], "best": 0}
"""


SMALL_HEAD_MAX = 5     # [2026-10-17] 이 인원 이하면 글에 인원을 쓰지 않음


def few_heads(job) -> bool:
    """[2026-10-17] 소수 채용(5명 이하) — 인원이 후킹 포인트가 안 되니 글에서 인원 언급 금지.
    수동 공고(MN-)는 인원 칸이 비어 있어도 대학·병원 소수 채용이 대부분이라 포함"""
    try:
        n = int(job.get("recrutNope") or 0)
    except Exception:
        n = 0
    return 0 < n <= SMALL_HEAD_MAX or (n == 0 and is_manual_id(job.get("recrutPblntSn")))


HIRE_NEG_RE = re.compile(r"계약직|기간제|비정규|임시직|체험형")


def hire_parts(job):
    """[2026-10-17] 고용형태를 장점(정규직·무기계약직·정규직 전환형·채용형 인턴)과 단점(계약직·기간제·임시직·비정규직·체험형)으로 나눔
    반환: (장점 목록, 단점 있음 여부)"""
    parts = [p.strip() for p in re.split(r"[,/·]", job.get("hireTypeNmLst") or "") if p.strip()]
    pos = [p for p in parts if not HIRE_NEG_RE.search(p) or p.startswith("무기계약")]
    neg = any(HIRE_NEG_RE.search(p) and not p.startswith("무기계약") for p in parts)
    return pos, neg


def contract_only(job) -> bool:
    """[2026-10-17] 장점 고용형태 없이 계약직·임시직 등만 있는 공고"""
    pos, neg = hire_parts(job)
    return neg and not pos


def tenure_job(job) -> bool:
    """[2026-10-19] 공공 무기계약직·공무직 공고 — 정년까지 근무가 핵심 무기라 리스트·훅에서 강조"""
    if is_private(job):
        return False
    if is_gojobs(job):
        return True
    return any("무기계약" in p or "공무직" in p for p in hire_parts(job)[0])


# [2026-10-19] 정년 강조 각도 — 매번 2개를 무작위로 골라 넘김 (같은 정년 문장이 반복되지 않게)
TENURE_ANGLES = [
    "조건 조합 — '정년까지'를 조건 한 칸으로 끼워 넣기 (예: 무기계약 + 정년까지 + 학력무관 + 지역). 둘째 줄은 매번 새로 쓸 것",
    "1인칭 감정 — 공고를 다시 읽다가 정년까지 다닐 수 있는 자리라는 걸 알아챈 순간의 감정 하나",
    "숫자로 체감 — 지금 나이에서 정년까지 남은 햇수처럼 '오래 다닐 수 있음'을 숫자로 (예: 스물다섯이면 35년). 기관 규모 숫자 포장은 금지",
    "상황 저격 — 이직·재취업 걱정 그만하고 오래 다닐 데 찾는 사람을 저격 (비교형 금지)",
    "긴급 — 마감이 코앞인데 정년까지 다닐 자리라는 걸 한 훅 안에 같이",
    "담백한 다짐 — 이번엔 오래 다닐 곳 하나만 노리겠다는 선언",
]
TENURE_COPY_RE = re.compile(r"정년\s*보장\s*무기계약직이었던")   # [2026-10-19] 베스트 원문 그대로 복붙만 차단 ('포기하려던 ~' 틀은 최근 반복일 때만 REPEAT_FRAMES로)


# 무기계약(직)은 장점이라 허용 — 그 외 계약·기간제·임시·비정규·계약 기간 표현은 쓰레드 금지
CONTRACT_WORD_RE = re.compile(r"(?<!무기)계약직|(?<!무기)계약\s*기간|(?<!무기)계약\s*만료|\d+\s*(개월|년)\s*계약|기간제|비정규|임시직|체험형"
                              r"|\d+\s*(개월|년)\s*(만|동안)?\s*버티")   # [2026-10-19] '1년만 버티면 정규직 전환' 류


FEW_HEADS_RE = re.compile(r"\d+\s*명|(한|두|세|네|다섯)\s*명|소수|단\s*\d|딱\s*\d|한\s*자리|1인\s*채용|인원")


def edu_for_prompt(job):
    """[2026-10-06] 민간 공고 학력 값은 수집 오류(빈 값·석사/박사만)가 있어 본문 기준으로 쓰게 안내"""
    v = job.get("acbgCondNmLst") or ""
    edu = [e.strip() for e in v.split(",") if e.strip()]
    if is_private(job) and (not edu or all(e in ("석사", "박사") for e in edu)):
        return "본문 발췌 '지원 자격 상세' 문장 기준으로 작성 (데이터 값 오류 가능)"
    return v


def build_user_prompt(job, inst, d_left, combo, post_text, recent_hooks, urgent=False):
    end = dt.datetime.strptime(job["pbancEndYmd"], "%Y%m%d")
    data = {
        ("기업 정식명칭(리스트 1번에 '따옴표'로)" if is_private(job) else "기관 정식명칭(리스트 1번에 '따옴표'로)"): inst,
        "공고명": job.get("recrutPbancTtl"),
        "고용형태": job.get("hireTypeNmLst"),
        "신입/경력": job.get("recrutSeNm"),
        "모집인원": job.get("recrutNope"),
        # [2026-10-12] 클린아이 공고문 근거는 학력조건 한 칸에 합침 (두 칸이면 리스트에 학력이 두 번 들어감)
        "학력조건": edu_for_prompt(job) + (f" ({job['_edu_text']})" if job.get("_edu_text") else ""),
        "근무지역": job.get("workRgnNmLst"),
        ("모집분야" if is_private(job) else "직무분야(NCS)"): job.get("ncsCdNmLst"),
        "마감일": f"{end.month}월 {end.day}일",
        "D-day": f"D-{d_left}",
    }
    if job.get("always"):                         # [2026-10-08] 상시채용 — 정리용 날짜를 마감일로 쓰지 않게
        data.pop("D-day")
        data["마감일"] = (job.get("endLabel") or "상시채용") + " (정해진 마감일 없음 — 날짜·D-day·마감 임박 표현 금지, 리스트 5번은 이 표기 그대로)"
    for k_src, k_out in (("yearIncome", "공고 제시 연봉(클린아이)"), ("judgeMethod", "전형방법(클린아이)")):
        if job.get(k_src):
            data[k_out] = job[k_src]
    low_pay = 0 < salary_manwon(job.get("yearIncome")) < SALARY_MIN
    hire_pos, hire_neg = hire_parts(job)
    if hire_neg:                                  # [2026-10-17] 계약직·기간제 등은 넘기지 않음 (장점만)
        if hire_pos:
            data["고용형태"] = ", ".join(hire_pos)
        else:
            data.pop("고용형태", None)
    tenure = tenure_job(job)
    if tenure:                                    # [2026-10-19] 무기계약·공무직 — 정년까지 근무를 팩트로 넘김
        data["고용 안정(리스트에 반드시 명시)"] = "무기계약 — 정해진 근무 기간 없이 정년까지 근무"
    few = few_heads(job)
    if few:                                       # [2026-10-17] 5명 이하 — 인원은 넘기지 않음
        data.pop("모집인원", None)
    head = "" if few else "인원·"
    if low_pay:                                   # [2026-10-12] 3천만원 미만 제시 연봉은 넘기지 않음
        data.pop("공고 제시 연봉(클린아이)", None)
    if (job.get("recrutSeNm") or "").strip() == "경력":   # [2026-10-20] 경력 공고 — '경력' 값은 넘기지 않음 (진입장벽)
        data.pop("신입/경력", None)
    if is_private(job):
        data["기업구분"] = f"민간 {job.get('bizType') or '기업'} (공기업 아님)"
        if is_manual_id(job.get("recrutPblntSn")) and not job.get("bizType"):   # [2026-10-16] 수동 공고(대학·대학병원 등)
            data["기업구분"] = "민간 (사립대학·대학병원·기업 등 — 공기업 아님, '대기업'이라 부르지 말 것)"
        data.pop("학력조건", None)                 # [2026-10-16] 민간은 학력을 글에 안 씀
    if job.get("localYn") == "Y":                 # [2026-10-12] 클린아이 지역제한 — 리스트에 반드시 명시
        data["지역제한(리스트에 반드시 명시)"] = (job.get("localName") if has_value(job.get("localName")) else "있음 (거주·연고자 한정)")
    if is_cleaneye(job) and job.get("entGb"):
        data["기관구분"] = job["entGb"]
        data["기관 성격(리스트에 반드시 한 번 명시)"] = cleaneye_kind(job)
    if is_gojobs(job):                            # [2026-10-14] 나라일터 — 빈 칸 대신 확인된 것만
        data["고용형태"] = "공무직 (무기계약 근로자 — 공무원 아님)"
        data["소속(전체 기관명)"] = job.get("instNm")
    # 빈 값('공고 참조', 0, '기타')은 아예 넘기지 않음 — 리스트·훅 소재로 쓰지 못하게
    data = {k: v for k, v in data.items() if has_value(v)}

    lines = [
        "[이번 글의 유형]",
        f"- 카테고리: {combo['cat']}",
        f"- 인물: {combo['person']}",
        f"- 구조: {combo['structure']}",
        f"- 훅 맨 앞 이모지: {combo['emoji']}",
        f"- 가이드: {combo['desc']}",
    ]

    # 인물형일 때만 인물 관련 지시
    if combo["cat"] == "person":
        lines.append("- 기관 업무를 일상 한 마디로 재정의해서 인물의 대화 속에 녹일 것 (센스 있는 오해 원칙)")
        lines.append("- 반응은 반드시 '진짜 오해 + 리얼한 부정 반응' — '좋은 데네' 같은 밋밋한 긍정 금지")
    else:
        lines.append("- 인물(부모님·여자친구·동료) 등장 금지 — 이 유형은 비인물형임")
        lines.append("- '했더니', '보여줬음', '하길래' 같은 대화체 구조 사용 금지")

    # [2026-10-06] 민간 공고·열린 조건 여부에 따른 추가 지시
    if is_private(job):
        lines.append("- 민간 기업 공고: 훅 무기는 브랜드·평균연봉·하는 일(쉬운 말)·열린 직무·입사 시기·근무지·복지. "
                     "전형 단계는 훅·클로저에 쓰지 말 것")
        lines.append("- [2026-10-16] 민간 공고는 학력(학사·대졸·4년제·졸업예정 등)과 어학(토익·오픽·토스·HSK·JLPT 등) 조건을 "
                     "훅·리스트·클로저 어디에도 쓰지 말 것 — 진입장벽으로 보여서 유입이 떨어짐. 리스트는 직무·근무지·연봉·전형·마감일로 채울 것")
        lines.append("- '대기업'은 누구나 아는 그룹사 계열일 때만. 아니면 업종(증권사·패션 회사 등)으로 부를 것")
    if is_cleaneye(job):
        lines.append("- 클린아이 공고: '기관구분'에 맞게 부를 것 (지방공사·지방공단 = 지방공기업 / 출자·출연기관·재단·의료원은 '공기업'이라 부르지 말 것)")
        lines.append(f"- 이름만 봐선 회사처럼 보일 수 있으니 리스트 2번에 '{cleaneye_kind(job)}'라고 꼭 적을 것 (공공기관이라는 게 이 글의 핵심 무기)")
    if is_gojobs(job):
        lines.append("- 나라일터(중앙부처·지자체) 공무직 공고: 데이터에 인원·학력·신입 여부가 없음 → 훅·리스트·클로저에 "
                     "인원(○명·대규모·여러 명), 학력·블라인드·'누구나 지원', 신입 언급 금지")
        lines.append("- '공무원'이라고 쓰지 말 것 — 공무직은 공무원이 아니라 정부기관 소속 무기계약 근로자. 리스트에 '공무직'을 꼭 한 번 쓸 것")
        lines.append("- 리스트는 '기관명' 공무직 채용 / 소속(○○부 산하 등) / 직무(공고명 괄호 속 직무를 쉬운 말로) / 근무 기관·지역 / 마감일로 채울 것")
        lines.append("- 직무가 집배·경비·시설·미화·운전·조리 같은 현장직이면 사무직처럼 쓰지 말 것")
    if is_cleaneye(job) and job.get("acbgCondNmLst") == "면허·자격 필수":
        lines.append("- 학력 대신 면허·자격이 필수인 공고 → 리스트에 '학력조건' 괄호 안 내용을 그대로 쓰고, '누구나 지원' 류 금지")
    if edu_unknown(job, post_text):
        lines.append("- 이 공고는 학력 정보가 없음 → 훅·리스트·클로저에 학력·블라인드·'누구나 지원' 언급 금지. "
                     "리스트는 " + head + "고용형태·" + ("" if low_pay else "공고 제시 연봉·") + "근무지(지역제한)·마감일로 채울 것")
    elif edu_hidden(job, post_text):              # [2026-10-19] 학사(대졸) 이상 등 학력 조건이 있는 공공 공고 → 학력은 쓰지 않음
        data.pop("학력조건", None)
        lines.append("- [2026-10-19] 이 공고는 학력 조건(대졸·학사 이상 등)이 있음 → 진입장벽으로 읽히니 훅·리스트·클로저 어디에도 "
                     "학력·학위·졸업·블라인드·'누구나 지원' 언급 금지 (공공 공고의 '학력조건 필수 팩트' 규칙보다 이게 우선). "
                     "대신 " + head + "고용형태(정년)·" + ("" if low_pay else "연봉·") + "근무지·하는 일(쉬운 말)·기관 브랜드·전형 일정으로 어필할 것")
    if low_pay or low_salary_in(post_text):
        lines.append("- 연봉 언급 금지 (3천만원 미만이라 매력 포인트가 아님) — 훅·리스트·클로저 모두. 연봉 대신 " + head + "고용형태·근무지·전형으로 채울 것")
    if few:
        lines.append("- [2026-10-17] 모집 인원이 5명 이하인 소수 채용 → 인원(○명·한 명·소수·딱 ○자리·'인원' 단어 등)을 훅·리스트·클로저 "
                     "어디에도 쓰지 말 것 (본문 발췌에 인원이 있어도). 대신 기관 브랜드·하는 일(쉬운 말)·근무지·근무조건·"
                     + ("" if low_pay else "연봉·") + "고용형태·입사 시기·전형 일정 같은 끌리는 포인트로 채울 것")
    # [2026-10-20] 경력 요건(○년 이상·경력자만)은 진입장벽 — 모든 공고 공통
    lines.append("- [2026-10-20] 경력 요건(경력 ○년 이상·경력자만·실무 경험 필수 등)은 훅·리스트·클로저 어디에도 쓰지 말 것 "
                 "(본문 발췌에 있어도). 대신 기관 브랜드·하는 일(쉬운 말)·근무지·근무조건·전형 일정으로 채울 것. "
                 "훅은 특정 직군(디자이너·개발자 등)만 알아듣는 고민 말고, 일반 취준생도 '오 이런 자리도 있네' 하는 소재로")
    if not has_open_fact(job, post_text):
        lines.append("- 이 공고엔 학력무관 같은 '모두에게 열린 조건'이 없음 → '포기했으면 다시 봐', '스펙 없어도 됨' 류 금지")
    if hire_neg:                                  # [2026-10-17] 계약직은 쓰레드에서 언급 안 함 — 본문으로 먼저 들어오게
        lines.append("- [2026-10-17] 계약직·기간제·임시직·비정규직·계약 기간(○개월·1년 계약 등)은 훅·리스트·클로저 어디에도 쓰지 말 것 "
                     "(본문 발췌에 있어도). 상세 조건은 본문에서 보게 하는 게 목표")
        if not hire_pos:
            lines.append("- 이 공고는 정규직·무기계약직이 아님 → '정규직'·'무기계약'·'정년'·'평생 직장'·'안정적' 표현도 금지. "
                         "리스트는 고용형태 칸 없이 기관 브랜드·하는 일(쉬운 말)·근무지·근무조건·전형 일정·마감일로 채울 것")
        else:
            lines.append(f"- 고용형태는 장점인 '{', '.join(hire_pos)}'만 쓸 것")
    if tenure:                                    # [2026-10-19] 정년 강조 — 단, 문장은 매번 다르게
        angles = random.sample(TENURE_ANGLES, 2)
        lines.append("- [2026-10-19] 무기계약·공무직 공고 → '정년까지 근무'가 이 글의 핵심 무기. "
                     "리스트 5개 중 한 항목에 반드시 '정년'을 넣을 것 (가능하면 2번, 예: '무기계약직 - 정년까지 근무'. "
                     "나라일터처럼 리스트 순서가 정해진 공고는 '공무직 채용' 항목 뒤에 붙여도 됨)")
        lines.append("- 후보 4개 중 최소 1개는 훅에 정년(정년까지·60세까지·오래 다닐 자리 등)을 무기로 쓸 것. 이번 글의 정년 각도 후보: "
                     + " / ".join(angles))
        lines.append("- 정년 문장은 매번 새로 쓸 것: '포기하려던 자리가 정년 보장 무기계약직이었던 거임' 같은 예시 문장·문장 틀을 그대로 가져오지 말고, "
                     "최근 발행한 훅·클로저에 나온 정년 표현과 단어 배치·구조가 겹치지 않게. 4개 후보끼리도 정년 표현을 서로 다르게")
    if urgent:                                    # [2026-10-15] 2순위 마감 임박 — 후보 4개 전부 ⚠️ + 마감 강조
        when = {1: "내일 마감", 2: "모레 마감"}.get(d_left, f"D-{d_left}")
        lines.append(f"- [마감 임박 글] 이 공고는 {when}(D-{d_left}, {end.month}월 {end.day}일)임. 후보 4개 전부 훅 맨 앞 이모지는 ⚠️ "
                     "(지정 유형·담백형 구분 없이 전부). 훅에 마감이 코앞이라는 걸 반드시 드러낼 것 "
                     "(예: '내일 마감', 'D-1', '모레면 닫힘', '이번 주 막차' — 실제 날짜와 맞게). "
                     "리스트 5번은 마감일(시각을 알면 시각까지)로. 클로저도 마감 임박 톤 (예: 오늘 안 넣으면 끝)")

    lines += [
        "",
        "[공고 데이터]",
        json.dumps(data, ensure_ascii=False, indent=1),
        "",
        "[본문 발췌 — 팩트 보강용, 여기 있는 내용만 추가 팩트로 사용 가능]",
        post_text or "(없음)",
    ]
    if recent_hooks:
        lines += ["", "[최근 발행한 훅 / 클로저 — 장면·인물·도입 상황·문장 구조가 겹치면 안 됨]"] + [f"- {h}" for h in recent_hooks]
    if not is_private(job):                       # [2026-10-19] 데이터는 여러 전형의 학력을 합쳐서 줌 → 본문으로 한 번 더 확인
        lines += ["", "[학력 확인] 본문 발췌를 보고, 이 글에 쓸 장점 고용형태(정규직·무기계약·공무직 등) 분야의 지원 자격이 "
                  "석사·박사 이상뿐이면 후보를 쓰지 말고 {\"skip\": \"석·박사 이상 전용\"} 만 출력해. 확실하지 않으면 그냥 후보 4개를 써."]
    lines += ["", "위 규격대로 후보 4개를 JSON으로 출력해."]
    return "\n".join(lines)


def call_claude(system, user, model, max_tokens=16000):
    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.environ["CLAUDE_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=180,
            )
        except requests.exceptions.RequestException as e:   # 타임아웃·연결 끊김
            last_err = e
            print(f"[warn] Claude 연결 오류 ({attempt+1}/4): {e}")
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404 and model != FALLBACK_MODEL:
            print(f"[warn] 모델 {model} 없음 → {FALLBACK_MODEL}로 재시도")
            return call_claude(system, user, FALLBACK_MODEL, max_tokens)
        if r.status_code in (429, 500, 502, 503, 504, 529):   # 일시 오류·과부하
            last_err = f"HTTP {r.status_code}"
            print(f"[warn] Claude 일시 오류 {r.status_code} ({attempt+1}/4) — 잠시 후 재시도")
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError(f"Claude API 재시도 4회 실패: {last_err}")
    res = r.json()
    kinds = [b.get("type") for b in res.get("content", [])]
    if res.get("stop_reason") == "max_tokens":
        print(f"[warn] 응답이 길이 제한({max_tokens})에서 잘림 — 블록: {kinds}")
    if "text" not in kinds:
        print(f"[warn] 글 본문 없이 끝난 응답 — 블록: {kinds}, 사용 토큰: {res.get('usage')}")
    return "".join(b.get("text", "") for b in res["content"] if b.get("type") == "text")


BANNED_HOOK = [
    (r"점심", "점심시간 장면"), (r"지원서\s*제출", "동료 지원서 장면"), (r"(?i)\bvs\b", "비교형(vs)"),
    (r"대학\s*보냈", "'대학 보냈냐' 무시형"), (r"공고\s*참조|조건\s*칸|조건란|칸이\s*비|아무것도\s*없", "데이터 빈칸 소재"),
    (r"\d+\s*개\s*중\s*\d+\s*개", "숫자 포장형"), (r"등기|수입인지|우체국", "절차 디테일"),
    (r"잔소리", "잔소리 농담형"), (r"인지\s*알아\?", "질문유도형"),
    # [2026-10-19] 생활 민원 오해형 인물 대화 (1366→119, 구 공단→주민센터 등본, 심평원→병원비 부탁)
    (r"주민센터|동사무소|등본|(?<![\d,])11[29](?![\d,])|불\s*끄러|병원비.{0,12}(깎|보라|봐\s*달|알아봐)|병원\s*비싸", "생활 민원 오해형"),
    # [2026-10-06] 민간 후킹 테스트에서 나온 제외 패턴 (훅·클로저 둘 다 검사)
    (r"전문학사|전문대|2~3년제|4년제\s*아니|대졸\s*공채는", "학력 하한 지목"),
    (r"\d+\s*단계|인적성|코테|코딩\s*테스트|과제\s*테스트|AI\s*(면접|역량)|토익|오픽|어학\s*(성적|점수)|학점", "장벽 소재"),
    (r"(?<![A-Za-z])MD(?![A-Za-z])|스택|백준|PJT|과테", "전문 용어·약어"),
]
CLOSER_CHECKED = ("데이터 빈칸 소재", "비교형(vs)", "학력 하한 지목", "장벽 소재", "전문 용어·약어", "생활 민원 오해형")
BANNED_CLOSERS = ["세 번 확인했는데 진짜임", "모르는 사람이 많을수록 경쟁률은 낮음",
                  "넘기려다 공고 열어본 사람이 붙는 거임", "말하고 싶으면 일단 넣어야 됨",
                  "합격하면 그때 말하려고", "동료는 이미 넣었고 나만 안 넣었음"]


# [2026-10-20] 경력 요건은 공공·민간 상관없이 진입장벽 → 훅·리스트·클로저 어디에도 안 씀 (한양대병원 UX디자이너 "경력 2년 이상 필요" 사례)
CAREER_BARRIER_RE = re.compile(r"경력\s*\d+\s*(년|개월)|\d+\s*(년|개월)\s*(이상\s*)?(의\s*)?(실무\s*)?경력|경력\s*(자\s*)?(만|필수|요건|있어야|이상)|경력자\s*(만|우대|대상)|경력직\s*(만|전용)")
PRIVATE_BARRIER_RE = re.compile(r"학력|학사|석사|대졸|고졸|초대졸|전문학사|[0-9]년제|졸업\s*예정|졸업자|학점|토익|토스|오픽|TOEIC|OPIc|TOEFL|텝스|TEPS|HSK|JLPT|어학", re.I)
# [2026-10-19] 긴급형 훅의 알맹이 — 마감만 말하는 빈 훅('접수 마감이 코앞', '이번 주 막차')은 탈락
URGENT_SUBSTANCE_RE = re.compile(
    r"\d+\s*(명|만|천|억)|정규직|무기\s*계약|공무직|채용형|전환|학력|정년|연봉|초봉|평균|신입|공채|"
    r"서울|부산|대구|인천|대전|광주|울산|세종|제주|경기|강원|충북|충남|전북|전남|경북|경남|수도권|지방|"
    r"공기업|공공기관|공단|공사|재단|정부|청사|법무부|우체국|병원|대학|은행|박물관|연구|발전소|"
    r"상담|배달|우편|관리|사무|행정|전산|개발|디자인|품질|시설|안전|간호|직무|분야")
# [2026-10-19] 반복 금지 문장 틀 (지침서 v3.6) — 틀 자체는 잘 터지는 것도 많아서 쓰는 건 허용,
#              최근 글(이 계정 최근 10개 + 같은 공고 글 + 각색 원글)에 같은 틀이 이미 있을 때만 탈락
REPEAT_FRAMES = [
    ("바보 손실", re.compile(r"손해가\s*아니라\s*바보")),
    ("조건 조합 둘째 줄", re.compile(r"이\s*조합이\s*(공고\s*)?(하나|한\s*공고)에")),
    ("조용히 넣음", re.compile(r"조용히\s*(이\s*공고만\s*)?넣")),
    ("붙으면 그때 말", re.compile(r"붙으면\s*그때\s*말")),
    ("주말에 미루면", re.compile(r"주말에\s*미루")),
    ("그냥 넘기지 마", re.compile(r"그냥\s*넘기지\s*마")),
    ("몰라서 억울", re.compile(r"몰라서\s*(못\s*넣은\s*게\s*)?(아직도\s*)?억울")),
    ("포기하려던 ~였던 거임", re.compile(r"포기하려던.{0,25}(였|었)던\s*거")),
]


def frames_in(texts) -> set:
    """[2026-10-19] 글 목록에 쓰인 반복 금지 문장 틀 이름"""
    return {name for name, rx in REPEAT_FRAMES for t in texts if rx.search(t or "")}
URGENT_HOOK_RE = re.compile(r"마감|D-?\s*\d|디데이|내일|모레|오늘|막차|닫힘|닫혀|끝남|끝나|이번\s*주|며칠|이틀|하루")


def validate_candidate(d: dict, inst: str = "", no_edu: bool = False, public_kind: bool = False, gongmu: bool = False,
                       urgent: bool = False, private: bool = False, contract: bool = False, few: bool = False,
                       hide_contract: bool = False, tenure: bool = False, recent_frames: set = None):
    """후보 1개 규격 검사 → (결과, 오류)"""
    hook = (d.get("hook") or "").replace("\\n", "\n").strip()
    if urgent and hook:                           # [2026-10-15] 마감 임박 글은 ⚠️ 강제 (📍로 왔으면 바꿔 끼움)
        hook = "⚠️" + re.sub(r"^(📍|⚠️|⚠)\s*", "", hook)
    if hook and not (hook.startswith("📍") or hook.startswith("⚠")):
        emo = (d.get("emoji") or "").strip()
        hook = (emo if emo in ("📍", "⚠️", "⚠") else "📍") + hook   # 이모지를 따로 준 경우 훅 앞에 붙임
    items = [re.sub(r"^\s*\d+[\.\)]\s*", "", str(x)).strip() for x in (d.get("items") or [])]
    closer = (d.get("closer") or "").strip()

    hook_lines = [l.strip() for l in hook.split("\n") if l.strip()]
    if not hook_lines or len(hook_lines) > 2:
        return None, "훅 줄 수 오류"
    if not (hook.startswith("📍") or hook.startswith("⚠")):
        return None, "훅 이모지 없음"
    for i, l in enumerate(hook_lines):
        body_l = re.sub(r"^(📍|⚠️|⚠)", "", l).strip() if i == 0 else l
        if len(body_l) > HOOK_LINE_MAX:
            return None, f"훅 {i+1}줄이 {len(body_l)}자 (최대 {HOOK_LINE_MAX}자)"
    if urgent and not URGENT_HOOK_RE.search(hook):   # [2026-10-15] 마감 임박 글은 훅에서 마감을 강조해야 통과
        return None, "마감 임박 글인데 훅에 마감 강조 없음"
    if hook.startswith("⚠") and not URGENT_SUBSTANCE_RE.search(re.sub(r"^(⚠️|⚠)", "", hook)):   # [2026-10-19]
        return None, "긴급형 훅에 알맹이 없음 (마감만 말함)"
    dup = frames_in([hook + "\n" + closer]) & (recent_frames or set())   # [2026-10-19] 최근 글과 같은 문장 틀
    if dup:
        return None, f"최근 글과 같은 문장 틀 ({', '.join(sorted(dup))})"
    if inst:
        full = norm_key(inst)
        short = re.sub(r"^(한국|국가|국립|재단법인|대한)", "", full)
        hook_k = norm_key(hook)
        for v in {full, short}:
            if len(v) >= 3 and v in hook_k:
                return None, f"훅에 기관명('{v}') 들어감"
    if re.search(r"(그곳|그 곳|하는 곳|하던 곳|던 그|알고 보니|알고보니|이 공단이|이 기관이|이 공사가|이 재단이|거기였음|곳이었음|거였음)", hook):
        return None, "생활 연결형"
    for pat, name in BANNED_HOOK:
        if name == "절차 디테일" and re.search(r"우체국|우편", inst or ""):
            pat = r"등기|수입인지"            # [2026-10-14] 우체국 공무직 공고는 '우체국'이 소재 자체라 허용
        if re.search(pat, hook) or (name in CLOSER_CHECKED and re.search(pat, closer)):
            return None, f"제외 패턴: {name}"
    if d.get("cat") != "person" and re.search(r"(했더니|하길래|보여줬|보여드렸|말했더니)", hook):
        return None, "비인물형인데 인물 대화체"
    if any(norm_key(bc) == norm_key(closer) for bc in BANNED_CLOSERS):
        return None, "고정 클로저"
    if len(items) != 5 or any(not x for x in items):
        return None, "리스트 5개 아님"
    if not re.match(r"^'[^']+'", items[0]):
        return None, "1번에 '기관명' 없음"
    if any(re.search(r"공고\s*참조|^기타$|초봉", x) for x in items):
        return None, "리스트에 빈 값·초봉"
    # [2026-10-12] 같은 팩트 반복 금지 — 학력은 한 항목, 같은 날짜는 한 항목에만
    if sum(1 for x in items if re.search(r"학력|학벌", x)) >= 2:
        return None, "리스트에 학력 반복"
    dates = [set(re.findall(r"(\d{1,2})월\s*(\d{1,2})일", x)) | set(re.findall(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])", x)) for x in items]
    if any(dates[i] & dates[j] for i in range(5) for j in range(i + 1, 5)):
        return None, "리스트에 같은 날짜 반복"
    if not closer or "\n" in closer:
        return None, "클로저 오류"
    body = "\n".join(hook_lines) + "\n\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(items)) + "\n\n" + closer
    if re.search(r"https?://|#\S", body):
        return None, "링크/해시태그"
    if public_kind and not any(re.search(r"공공|공기업|출연|출자", x) for x in items):
        return None, "공공기관 표시 없음"   # [2026-10-12] 클린아이: 회사처럼 보이지 않게
    if low_salary_in(body):
        return None, "3천만원 미만 연봉 언급"   # [2026-10-12] 외부 유입 후킹이 안 됨
    if no_edu and re.search(r"학력|학벌|고졸|대졸|학사|블라인드|누구나\s*지원", body):
        return None, "학력 정보 없는 공고에 학력 언급"   # [2026-10-12] 클린아이
    if gongmu:                                    # [2026-10-14] 나라일터 공무직
        if re.search(r"\d+\s*명|대규모|여러\s*명|신입", body):
            return None, "나라일터 공고에 인원·신입 언급"
        if "공무원" in body:
            return None, "공무직을 공무원으로 씀"
        if not any("공무직" in x for x in items):
            return None, "리스트에 공무직 표시 없음"
    if private and PRIVATE_BARRIER_RE.search(body):   # [2026-10-16] 민간: 학력·어학 조건은 진입장벽 → 글 전체 금지
        return None, "민간 공고에 학력·어학 조건"
    if CAREER_BARRIER_RE.search(body):           # [2026-10-20] 경력 요건 언급 금지 (진입장벽)
        return None, "경력 요건 언급"
    if few and FEW_HEADS_RE.search(body):        # [2026-10-17] 5명 이하 공고에 인원 언급
        return None, "소수 채용 공고에 인원 언급"
    if hide_contract and CONTRACT_WORD_RE.search(body):   # [2026-10-17] 계약직은 쓰레드에서 언급 안 함
        return None, "계약직·기간제 언급"
    if contract and re.search(r"정규직(?!\s*전환)|무기\s*계약|정년|평생\s*직장", body):   # [2026-10-16] 수동 계약직·임시직
        return None, "계약직 공고를 정규직처럼 씀"
    if tenure and not any("정년" in x for x in items):   # [2026-10-19] 무기계약·공무직은 리스트에 정년 필수
        return None, "무기계약 공고인데 리스트에 정년 없음"
    if TENURE_COPY_RE.search("\n".join(hook_lines) + "\n" + closer):   # [2026-10-19] 베스트 예시 문장 복붙 금지
        return None, "정년 예시 문장 그대로 사용"
    if len(body) > 490:
        return None, f"길이 초과 ({len(body)}자)"
    return {"hook": "\n".join(hook_lines), "items": items, "closer": closer, "text": body,
            "type": d.get("type") or "plain", "cat": d.get("cat") or ""}, None


def parse_candidates(raw: str):
    clean = re.sub(r"```(json)?", "", raw).strip()
    m = re.search(r"\{.*\}", clean, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            return d.get("candidates") or ([d] if d.get("hook") else [])
        except Exception:
            pass
    # 응답이 중간에 잘렸어도 완성된 후보 객체는 하나씩 살린다
    out = []
    for mm in re.finditer(r"\{[^{}]*\"hook\"[^{}]*\}", clean, re.S):
        try:
            out.append(json.loads(mm.group(0)))
        except Exception:
            continue
    return out


def judge(cands, recent_hooks):
    """AI 편집장 채점 → (가장 좋은 후보 index, 점수). 실패하면 담백한 후보 우선"""
    try:
        listing = "\n\n".join(f"[{i}] type={c['type']}\n{c['text']}" for i, c in enumerate(cands))
        user = ("[최근 발행 훅·클로저]\n" + "\n".join(f"- {h}" for h in recent_hooks) +
                "\n\n[후보]\n" + listing + "\n\n채점해서 JSON으로.")
        raw = call_claude(JUDGE_PROMPT, user, CLAUDE_MODEL)
        m = re.search(r"\{.*\}", re.sub(r"```(json)?", "", raw), re.S)
        res = json.loads(m.group(0))
        scores = {int(x["i"]): x for x in res.get("scores", []) if "i" in x and 0 <= int(x["i"]) < len(cands)}
        for i, x in sorted(scores.items()):
            print(f"  채점 [{i}] {cands[i]['type']} total={x.get('total')} — {x.get('why', '')}")
        best = max(scores, key=lambda i: (scores[i].get("total") or 0, cands[i]["type"] == "plain"))
        return best, scores[best]
    except Exception as e:
        print(f"[warn] 채점 실패 → 담백한 후보 우선: {e}")
        plain = [i for i, c in enumerate(cands) if c["type"] == "plain"]
        return (plain or [0])[0], None


def generate(job, inst, d_left, combo, post_text, recent_hooks, urgent=False):
    user = build_user_prompt(job, inst, d_left, combo, post_text, recent_hooks, urgent)
    recent_frames = frames_in(recent_hooks or [])   # [2026-10-19] 최근에 쓴 반복 금지 문장 틀 → 이번엔 못 씀
    if recent_frames:
        print(f"최근 글에 쓴 문장 틀 (이번엔 금지): {', '.join(sorted(recent_frames))}")
        user += "\n\n[이번엔 쓰면 안 되는 문장 틀 — 최근 글에 이미 나옴] " + ", ".join(sorted(recent_frames))
    errs = []
    for attempt in range(3):
        u = user if not errs else user + f"\n\n[이전 후보들이 규격 위반으로 탈락: {'; '.join(errs[-4:])}] 규격을 다시 지켜서 후보 4개를 출력해."
        raw = call_claude(SYSTEM_PROMPT, u, CLAUDE_MODEL)
        m_skip = re.search(r'"skip"\s*:\s*"([^"]*)"', raw or "")
        if m_skip and '"candidates"' not in raw:     # [2026-10-19] 박사 이상 전용 공고 → 이 공고는 앞으로 건너뜀
            print(f"[제외] AI 확인 결과 {m_skip.group(1)} — 이 공고는 앞으로 후보에서 뺌")
            return {"_skip": m_skip.group(1)}
        valid, errs = [], []
        cands = parse_candidates(raw)
        if not cands:
            errs.append("JSON 해석 실패")
            print(f"  [JSON 해석 실패] 응답 앞부분: {raw[:300]!r} … 끝부분: {raw[-200:]!r}")
        for c in cands:
            r, err = validate_candidate(c, inst, edu_hidden(job, post_text) or is_gojobs(job), is_cleaneye(job), is_gojobs(job),
                                        urgent, is_private(job),
                                        contract_only(job), few_heads(job), hire_parts(job)[1], tenure_job(job),
                                        recent_frames)
            if r:
                valid.append(r)
            else:
                errs.append(err)
                print(f"  [탈락] {err} | {(c.get('hook') or '').replace(chr(10), ' / ')[:60]}")
        if valid:
            best, sc = judge(valid, recent_hooks) if len(valid) > 1 else (0, None)
            if sc is not None and (sc.get("total") or 0) <= 0:
                errs.append("채점 0점 (제외 패턴)")
                print(f"[warn] {attempt+1}회차 최고점 후보도 0점 — 재생성")
                continue
            print(f"선택: [{best}] {valid[best]['type']} / {valid[best]['cat']} (통과 후보 {len(valid)}개)")
            return valid[best]
        print(f"[warn] 생성 {attempt+1}회차 통과 후보 없음: {errs}")
    # 3회 모두 탈락·채점 0점(제외 패턴) → 억지로 발행하지 않고 이번 회차 건너뜀 (매시간 실행이라 곧 재시도)
    print(f"[건너뜀] 3회 모두 발행할 만한 후보 없음 — 다음 회차에 재시도: {errs[-4:]}")
    summary("### ⏭️ 건너뜀\n후보가 규격·채점을 통과하지 못함 (다음 회차 재시도)")
    return None


BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
              "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}


def fetch_page(url):
    for _ in range(3):
        r = requests.get(url, headers=BROWSER_UA, timeout=15, verify=False)
        if r.encoding in (None, "ISO-8859-1"):
            r.encoding = r.apparent_encoding
        html = r.text
        if len(html) < 3000:
            clean = re.sub(r"(?s)<!--.*?-->", "", html)
            m = (re.search(r'http-equiv=["\']refresh["\'][^>]*url=([^"\'>]+)', clean, re.I) or
                 re.search(r'(?:location\.href|location\.replace\(|window\.location)\s*=?\s*["\']([^"\']+)["\']', clean))
            if m:
                url = urljoin(r.url, m.group(1).strip())
                continue
        return r
    return r


def _wd_match(e, inst):
    names = [e.get("label", ""), (e.get("match") or {}).get("text", "")] + (e.get("aliases") or [])
    return any(norm_key(n) == norm_key(inst) for n in names if n)


def wd_get(params):
    H = {"User-Agent": "job-compass-bot/1.0 (github teukgasniper)"}
    base = params.pop("_base", "https://www.wikidata.org/w/api.php")
    for i in range(4):
        r = requests.get(base, headers=H, timeout=20, params={**params, "format": "json"})
        if r.status_code == 429:
            time.sleep(4 + i * 4)
            continue
        return r.json()
    return {}

AGENCY_DOMAINS = ("cleaneye", "incruit", "gojobs", "recruiter.co.kr", "careerlink", "applyin",
                  "recruitcenter", "saramin", "fairyhr", "jobkorea", "alio", "kpcice", "jinhak",
                  "catch.co.kr", "worknet", "work24", "midashri", "hrlink", "insaworks", "career.co.kr",
                  "scout.co.kr")
CARD_W = 1440


def find_logo_file(inst: str):
    if not os.path.isdir(LOGO_DIR):
        return None
    target = norm_key(norm_inst(inst)).replace("재단법인", "")
    for fn in os.listdir(LOGO_DIR):
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        if norm_key(norm_inst(stem)).replace("재단법인", "") == target:
            return os.path.join(LOGO_DIR, fn)
    return None


def _visible_enough(im):
    rgba = im.convert("RGBA"); rgba.thumbnail((300, 300))
    px = list(rgba.getdata())
    vis = [p for p in px if p[3] > 128]
    if len(vis) < len(px) * 0.03:
        return False
    dark = sum(1 for r, g, b, a in vis if (0.299 * r + 0.587 * g + 0.114 * b) < 170)
    colorful = sum(1 for r, g, b, a in vis if max(r, g, b) - min(r, g, b) > 60)
    return dark + colorful >= len(px) * 0.02


def _load_image(url, ref):
    from PIL import Image
    r = requests.get(url, headers={**BROWSER_UA, "Referer": ref}, timeout=15, verify=False)
    r.raise_for_status()
    data = r.content
    if url.lower().split("?")[0].endswith(".svg") or b"<svg" in data[:500]:
        import cairosvg
        data = cairosvg.svg2png(bytestring=data, output_width=2400)
    im = Image.open(io.BytesIO(data)); im.load()
    return im


def _img_score(tag, inst):
    attrs = " ".join([tag.get("src", ""), tag.get("alt", ""), tag.get("title", ""),
                      str(tag.get("class", "")), str(tag.get("id", ""))]).lower()
    s = 0
    if "logo" in attrs: s += 5
    if inst[:4] in (tag.get("alt", "") + tag.get("title", "")): s += 3
    for p in tag.parents:
        if not hasattr(p, "get"): break
        if "logo" in (str(p.get("class", "")) + str(p.get("id", "")) + (p.name or "")).lower():
            s += 4; break
    for p in tag.parents:
        if not hasattr(p, "get"): break
        if p.name in ("header", "h1") or "header" in (str(p.get("class", "")) + str(p.get("id", ""))).lower():
            s += 2; break
    if any(b in attrs for b in ("footer", "foot", "banner", "sns", "icon", "btn", "top_", "close", "popup",
                                "visual", "slide", "wa_", "qr", "award", "egov", "fki", "ict", "prize")):
        s -= 6
    if re.search(r"(logo_f|f-logo|flogo|ft_logo|_bott|_w\.|white|_wh)", attrs):
        s -= 3
    return s


def _homepages(inst, job):
    sites = []
    net = urlparse(job.get("srcUrl") or "").netloc
    if net and not any(a in net for a in AGENCY_DOMAINS):
        parts = net.split(".")
        if parts[0] in ("recruit", "job", "jobs", "career", "info"):
            net = "www." + ".".join(parts[1:])
        sites.append("https://" + net + "/")
    try:
        d = wd_get({"action": "wbsearchentities", "search": inst, "language": "ko", "uselang": "ko", "limit": 1})
        for e in d.get("search", []):
            if not _wd_match(e, inst):
                continue
            ent = wd_get({"action": "wbgetentities", "ids": e["id"], "props": "claims"})
            for c in ent["entities"][e["id"]].get("claims", {}).get("P856", []):
                v = c["mainsnak"].get("datavalue", {}).get("value")
                if v: sites.append(v)
    except Exception:
        pass
    return list(dict.fromkeys(sites))


def make_card(im):
    from PIL import Image, ImageChops
    im = im.convert("RGBA")
    flat = Image.new("RGBA", im.size, (255, 255, 255, 255)); flat.alpha_composite(im)
    box = ImageChops.difference(flat.convert("RGB"), Image.new("RGB", im.size, "white")).getbbox()
    if box: im = im.crop(box)
    w, h = im.size
    ratio = min(max(w / h * 1.12, 3.2), 5.0)
    cw = int(min(CARD_W, max(720, w * 3 / 0.86)))
    ch = int(cw / ratio)
    s = min(cw * 0.86 / w, ch * 0.78 / h)
    im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    card = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    card.alpha_composite(im, ((cw - im.width) // 2, (ch - im.height) // 2))
    return card.convert("RGB")


def ai_is_logo(card, inst) -> bool:
    buf = io.BytesIO(); c = card.copy(); c.thumbnail((800, 450)); c.save(buf, "JPEG", quality=85)
    prompt = (f"이 이미지가 '{inst}'의 공식 대표 로고(심볼+기관명 또는 기관 워드마크)인가? "
              "수상 배너, 하위 서비스·캠페인 브랜드, 다른 기관 로고, 아이콘 조각, 흐릿하거나 잘린 이미지면 NO. "
              "YES 또는 NO 한 단어로만 답해.")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(buf.getvalue()).decode()}},
               {"type": "text", "text": prompt}]
    try:
        for model in (CLAUDE_MODEL, FALLBACK_MODEL):
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
                "x-api-key": os.environ["CLAUDE_API_KEY"], "anthropic-version": "2023-06-01",
                "content-type": "application/json"},
                json={"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": content}]})
            if r.status_code != 404:
                break
        r.raise_for_status()
        ans = "".join(b.get("text", "") for b in r.json()["content"]).strip().upper()
        return ans.startswith("YES")
    except Exception as e:
        print(f"[warn] 로고 AI 판별 실패: {e}")
        return False


def ai_find_homepage(inst):
    prompt = (f"'{inst}'의 ① CI·로고 소개 페이지 주소와 ② 공식 홈페이지 메인 주소를 웹 검색으로 찾아줘. "
              "채용대행 사이트(인크루트·잡코리아·사람인·recruiter.co.kr 등), 위키, 뉴스, 블로그는 안 됨. "
              "기관이 직접 운영하는 사이트 주소만. 설명 없이 URL만 한 줄에 하나씩, CI 페이지를 먼저. 못 찾으면 NONE.")
    urls = []
    try:
        for model in (CLAUDE_MODEL, FALLBACK_MODEL):
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=120, headers={
                "x-api-key": os.environ["CLAUDE_API_KEY"], "anthropic-version": "2023-06-01",
                "content-type": "application/json"},
                json={"model": model, "max_tokens": 300,
                      "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
                      "messages": [{"role": "user", "content": prompt}]})
            if r.status_code != 404:
                break
        r.raise_for_status()
        text = " ".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        for u in re.findall(r"https?://[^\s\"'<>()\]\[]+", text):
            net = urlparse(u).netloc
            if net and not any(a in net for a in AGENCY_DOMAINS) and "wiki" not in net:
                urls.append(u.rstrip(".,"))
        if urls:
            print(f"AI 홈페이지 검색: {inst} → {urls[:2]}")
    except Exception as e:
        print(f"[warn] AI 홈페이지 검색 실패: {e}")
    return list(dict.fromkeys(urls))[:2]


def _css_logo_urls(page_url, soup):
    css = [urljoin(page_url, l["href"]) for l in soup.find_all("link", href=True)
           if "stylesheet" in (l.get("rel") or [])][:8]
    sources = [(page_url, st.get_text()) for st in soup.find_all("style")]
    for c in css:
        try:
            sources.append((c, requests.get(c, headers=BROWSER_UA, timeout=10, verify=False).text))
        except Exception:
            pass
    out = []
    for base, text in sources:
        for m in re.finditer(r"([^{}]*logo[^{}]*)\{([^}]*)\}", text, re.I):
            sel, body = m.group(1), m.group(2)
            if re.search(r"(sns|foot|f_logo|ft_|footer|icon|btn|partner|family|banner)", sel, re.I):
                continue
            for u in re.findall(r"url\([\"']?([^\"')]+)[\"']?\)", body):
                if not u.startswith("data:"):
                    out.append(urljoin(base, u))
    return list(dict.fromkeys(out))


def _inline_svg_logos(soup):
    out = []
    for el in soup.select("[class*=logo], [id*=logo], header h1, h1"):
        cls = (str(el.get("class", "")) + str(el.get("id", ""))).lower()
        if re.search(r"(sns|foot|f_logo|ft_|footer|family|partner)", cls):
            continue
        svg = el.find("svg")
        if svg and len(str(svg)) > 300:
            out.append(str(svg))
    return out[:3]


def _logo_candidates(site, inst):
    from bs4 import BeautifulSoup
    r = fetch_page(site)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    cands = []
    for t in soup.find_all("img"):
        if not t.get("src") or t["src"].startswith("data:"):
            continue
        sc = _img_score(t, inst)
        if sc < 5:
            continue
        src = urljoin(r.url, t["src"])
        if t.get("srcset"):
            parts = [c.strip().split(" ") for c in t["srcset"].split(",") if c.strip()]
            def _w(c):
                try: return float(re.sub(r"[^0-9.]", "", c[1])) if len(c) > 1 else 1
                except Exception: return 1
            best = max(parts, key=_w, default=None)
            if best: src = urljoin(r.url, best[0])
        cands.append((sc, "url", src))
    for u in _css_logo_urls(r.url, soup):
        sc = 7 - (3 if re.search(r"(_w\.|white|_wh)", u.lower()) else 0)
        if re.search(r"(parents|special|event|season|xmas|christmas|newyear|new_year|anniv|20\d\d)", u.lower()):
            sc -= 4
        if u.lower().split("?")[0].endswith(".svg"):
            sc += 1
        cands.append((sc, "url", u))
    for svg in _inline_svg_logos(soup):
        cands.append((6, "svg", svg))
    cands.sort(key=lambda x: -x[0])
    return r.url, cands


def _open_candidate(kind, val, ref):
    from PIL import Image
    if kind == "svg":
        import cairosvg
        png = cairosvg.svg2png(bytestring=val.encode("utf-8"), output_width=2400)
        im = Image.open(io.BytesIO(png)); im.load()
        return im
    return _load_image(val, ref)


def _try_site_logo(site, inst, max_ai=3):
    try:
        page, cands = _logo_candidates(site, inst)
    except Exception:
        return None
    ai_used = 0
    seen = set()
    for _, kind, val in cands[:12]:
        key = val[:200]
        if key in seen:
            continue
        seen.add(key)
        try:
            im = _open_candidate(kind, val, page)
        except Exception:
            continue
        w, h = im.size
        if w < 60 or h < 15 or w / h > 12 or h / w > 3 or not _visible_enough(im):
            continue
        card = make_card(im)
        ai_used += 1
        if ai_is_logo(card, inst):
            print(f"로고 자동 수집 성공: {val[:120] if kind == 'url' else '인라인 SVG'}")
            return card
        print(f"[info] AI가 로고 아님으로 판별: {val[:120] if kind == 'url' else '인라인 SVG'}")
        if ai_used >= max_ai:
            break
    return None


def commons_search_logo(inst):
    H = {"User-Agent": "job-compass-bot/1.0 (github teukgasniper)"}
    from PIL import Image
    try:
        titles = []
        en = None
        d = requests.get("https://www.wikidata.org/w/api.php", headers=H, timeout=15, params={
            "action": "wbsearchentities", "search": inst, "language": "ko", "uselang": "ko", "format": "json", "limit": 1}).json()
        for e in d.get("search", []):
            if _wd_match(e, inst):
                ent = requests.get("https://www.wikidata.org/w/api.php", headers=H, timeout=15, params={
                    "action": "wbgetentities", "ids": e["id"], "props": "labels", "languages": "en",
                    "format": "json"}).json()
                en = ent["entities"][e["id"]].get("labels", {}).get("en", {}).get("value")
        for term in ([f"{en} logo"] if en else []) + [f"{inst} 로고"]:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=H, timeout=15, params={
                "action": "query", "list": "search", "srsearch": term, "srnamespace": 6,
                "srlimit": 5, "format": "json"}).json()
            for h in r.get("query", {}).get("search", []):
                t = h["title"]
                if re.search(r"(logo|로고|CI\b|symbol)", t, re.I) and t.lower().endswith((".svg", ".png", ".jpg")):
                    titles.append(t)
        for t in list(dict.fromkeys(titles))[:2]:
            url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(t[5:].replace(" ", "_")) + "?width=2400"
            r = requests.get(url, headers=H, timeout=30)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                im = Image.open(io.BytesIO(r.content)); im.load()
                if _visible_enough(im):
                    card = make_card(im)
                    if ai_is_logo(card, inst):
                        print(f"로고 자동 수집 성공: 위키미디어 {t}")
                        return card
    except Exception as e:
        print(f"[warn] 위키미디어 검색 실패: {e}")
    return None


def commons_logo(inst):
    H = {"User-Agent": "job-compass-bot/1.0 (github teukgasniper)"}
    try:
        d = requests.get("https://www.wikidata.org/w/api.php", headers=H, timeout=15, params={
            "action": "wbsearchentities", "search": inst, "language": "ko", "uselang": "ko", "format": "json", "limit": 1}).json()
        for e in d.get("search", []):
            if not _wd_match(e, inst):
                continue
            ent = requests.get("https://www.wikidata.org/w/api.php", headers=H, timeout=15, params={
                "action": "wbgetentities", "ids": e["id"], "props": "claims", "format": "json"}).json()
            files = [c["mainsnak"]["datavalue"]["value"] for c in
                     ent["entities"][e["id"]].get("claims", {}).get("P154", []) if "datavalue" in c["mainsnak"]]
            if not files:
                return None
            from PIL import Image
            url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(files[-1].replace(" ", "_")) + "?width=2400"
            r = requests.get(url, headers=H, timeout=30)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                im = Image.open(io.BytesIO(r.content)); im.load()
                return im
    except Exception as e:
        print(f"[warn] 위키미디어 로고 조회 실패: {e}")
    return None


def auto_collect_logo(inst, job):
    try:
        import bs4  # noqa
        import urllib3; urllib3.disable_warnings()
    except Exception:
        return None
    im = commons_logo(inst)
    if im is not None and _visible_enough(im):
        card = make_card(im)
        if ai_is_logo(card, inst):
            print("로고 자동 수집 성공: 위키미디어 공식 로고")
            return card
    tried = []
    for site in _homepages(inst, job):
        tried.append(urlparse(site).netloc.replace("www.", ""))
        card = _try_site_logo(site, inst)
        if card:
            return card
    card = commons_search_logo(inst)
    if card:
        return card
    for site in ai_find_homepage(inst):
        if urlparse(site).path.strip("/") == "" and urlparse(site).netloc.replace("www.", "") in tried:
            continue
        card = _try_site_logo(site, inst)
        if card:
            return card
    return None


def git_push(paths, msg):
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", *paths], check=True)
        subprocess.run(["git", "commit", "-m", msg], check=True)
        for _ in range(3):
            # [2026-10-12] --autostash: 학력 기록(edu_cache)·logos_missing.txt 같은 저장 안 된 변경이 있으면
            #              pull --rebase가 실패해서 로고 주소를 못 받고 글만 발행되던 문제
            if subprocess.run(["git", "pull", "--rebase", "--autostash"]).returncode == 0 and \
               subprocess.run(["git", "push"]).returncode == 0:
                return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            time.sleep(5)
    except Exception as e:
        print(f"[warn] 로고 push 실패: {e}")
    return None


def raw_url(path, ref="main"):
    return f"https://raw.githubusercontent.com/{REPO}/{ref}/" + "/".join(quote(p) for p in path.split("/"))


TEXT_CARD_DIR = "logos_text"
FONT_CANDIDATES = ["/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
                   "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]


def make_text_card(inst):
    """로고를 못 구했을 때: 흰 바탕에 기관명만 크게 (로고 카드와 같은 가로 비율)"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    font_path = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
    if not font_path:
        print("[warn] 한글 폰트 없음 → 텍스트 카드 생략")
        return None
    W, H = 1440, 400
    card = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(card)
    size = 150
    while size > 40:
        font = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), inst, font=font)
        if box[2] - box[0] <= W * 0.86:
            break
        size -= 6
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(((W - tw) / 2 - box[0], (H - th) / 2 - box[1]), inst, font=font, fill=(30, 41, 89))
    return card


def text_card_url(inst):
    """기관명 텍스트 카드 저장·업로드 → raw 주소 (logos/ 와 따로 둬서 진짜 로고 수집은 계속 시도)"""
    path = os.path.join(TEXT_CARD_DIR, f"{inst}.png")
    if not os.path.exists(path):
        card = make_text_card(inst)
        if card is None:
            return None
        if DRY_RUN:
            return "(DRY_RUN — 텍스트 카드 생성만 확인)"
        os.makedirs(TEXT_CARD_DIR, exist_ok=True)
        card.save(path, optimize=True)
        sha = git_push([path], f"logo(text): {inst} 기관명 카드")
        return raw_url(path, sha) if sha else None
    return raw_url(path)


def resolve_logo(inst, job, state):
    url, msg = _resolve_logo(inst, job, state)
    if url or not USE_LOGO or "성공" in msg:      # 로고를 구했으면(DRY_RUN 포함) 텍스트 카드 불필요
        return url, msg
    t = text_card_url(inst)                       # [v3.5] 로고 실패 → 기관명 텍스트 카드
    if t and not t.startswith("(DRY"):
        return t, msg + " → 기관명 텍스트 카드로 대체"
    return None, msg + (" → 텍스트 카드 생성 가능(DRY_RUN)" if t else "")


def _resolve_logo(inst, job, state):
    if not USE_LOGO:
        return None, "로고 사용 안 함"
    path = find_logo_file(inst)
    if path:
        return raw_url(path), f"로고 있음 ({path})"

    tried = state.setdefault("logo_tried", {})
    last = tried.get(inst)
    if last and (dt.datetime.now(KST).date() - dt.date.fromisoformat(last)).days < LOGO_RETRY_DAYS:
        return None, "로고 없음 (최근 자동수집 실패 — 글만 발행)"

    card = auto_collect_logo(inst, job)
    if DRY_RUN:
        return None, "자동수집 성공 (DRY_RUN이라 저장 안 함)" if card else "로고 없음 · 자동수집 실패"
    if not card:
        tried[inst] = dt.datetime.now(KST).date().isoformat()
        missing = set()
        if os.path.exists(MISSING_PATH):
            missing = {l.strip() for l in open(MISSING_PATH, encoding="utf-8") if l.strip()}
        missing.add(inst)
        with open(MISSING_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(missing)) + "\n")
        return None, "로고 없음 · 자동수집 실패 → logos_missing.txt 기록"

    os.makedirs(LOGO_DIR, exist_ok=True)
    path = os.path.join(LOGO_DIR, f"{inst}.png")
    card.save(path, optimize=True)
    if os.path.exists(MISSING_PATH):
        rest = [l.strip() for l in open(MISSING_PATH, encoding="utf-8") if l.strip() and l.strip() != inst]
        with open(MISSING_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(rest) + ("\n" if rest else ""))
    sha = git_push([path, MISSING_PATH] if os.path.exists(MISSING_PATH) else [path], f"logo: {inst} 자동 수집")
    if not sha:
        return None, "자동수집 성공했지만 업로드 실패 — 글만 발행"
    return raw_url(path, sha), "로고 자동수집 성공 → logos/ 저장"


# ─────────────────────────── Threads API ───────────────────────────
def threads_post(text: str, reply_to: str = None, image_url: str = None) -> str:
    uid, token = os.environ["THREADS_USER_ID"], os.environ["THREADS_TOKEN"]
    params = {"media_type": "IMAGE" if image_url else "TEXT", "text": text, "access_token": token}
    if image_url:
        params["image_url"] = image_url
    if reply_to:
        params["reply_to_id"] = reply_to
    r = requests.post(f"{THREADS_API}/{uid}/threads", data=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"컨테이너 생성 실패 {r.status_code}: {r.text}")
    cid = r.json()["id"]
    for _ in range(20):
        time.sleep(6)
        st = requests.get(f"{THREADS_API}/{cid}", params={"fields": "status,error_message",
                                                          "access_token": token}, timeout=30).json()
        if st.get("status") == "FINISHED":
            break
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 처리 실패: {st}")
    r = requests.post(f"{THREADS_API}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"발행 실패 {r.status_code}: {r.text}")
    return r.json()["id"]


def build_comment(post: dict, d_left: int):
    if COMMENT_LINK == "none":
        return None
    if COMMENT_LINK in ("hiring", "post"):
        link = post["url"] if (COMMENT_LINK == "post" and post) else HIRING_URL
        lead = f"D-{d_left} 곧 마감 👇" if d_left <= 5 else "지원자격 총정리 👇"
        return f"{lead}\n{link}"
    return COMMENT_TEXT


def summary(md: str):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


# ─────────────────────────── 쓰레드 동기화 ───────────────────────────
SYNC_STOP = {"채용", "공고", "모집", "직원", "신규", "년도", "하반기", "상반기", "2026년", "2026", "제1차", "제2차", "공개", "근로자",
             "공무직", "공무직근로자", "정규직", "신입", "일반", "및", "직"}


def match_post_to_job(text: str, ts: str, cands: list, first_rest: str = ""):
    """[2026-10-20] 수동으로 올린 글 → 공고 1개 찾기. 같은 기관 공고가 여러 개여도 마감일·직무 단어·인원으로 가려냄.
    글 올린 날짜보다 나중에 시작한 공고는 제외 (예전 글이 같은 기관의 새 공고로 잘못 잡히던 문제 — 대한법률구조공단 사례)"""
    post_day = (ts or "")[:10].replace("-", "")
    if post_day:
        cands = [j for j in cands if (j.get("pbancBgngYmd") or "0") <= post_day <= (j.get("pbancEndYmd") or "99999999")]
    if len(cands) <= 1:
        return cands[0] if cands else None
    flat = re.sub(r"\s+", "", text)

    def sc(j):
        s = 0
        end = j.get("pbancEndYmd") or ""
        if len(end) == 8:
            mo, d = int(end[4:6]), int(end[6:8])
            if re.search(rf"(?<!\d){mo}\s*[/.월]\s*{d}(?!\d)", text):
                s += 3
        title = re.sub(r"[()\[\]·,/]", " ", (j.get("recrutPbancTtl") or "") + " " + (j.get("hireTypeNmLst") or ""))
        inst_words = set(norm_inst(j.get("instNm")).split())
        for w in set(title.split()):
            w = w.strip("'\"")
            if len(w) >= 2 and w not in SYNC_STOP and w not in inst_words and w in flat:
                s += 1
        n = re.search(r"(\d+)\s*명", first_rest or "")
        if n and str(j.get("recrutNope") or "") == n.group(1):
            s += 2
        return s
    ranked = sorted(((sc(j), j) for j in cands), key=lambda x: -x[0])
    if ranked[0][0] > 0 and ranked[0][0] > ranked[1][0]:
        return ranked[0][1]
    return None


def sync_from_threads(state: dict, jobs: list) -> int:
    uid, token = os.environ.get("THREADS_USER_ID"), os.environ.get("THREADS_TOKEN")
    if not uid or not token:
        return 0
    try:
        r = requests.get(f"{THREADS_API}/{uid}/threads",
                         params={"fields": "id,text,timestamp", "limit": 50, "access_token": token}, timeout=30)
        items = r.json().get("data", []) if r.ok else []
    except Exception as e:
        print(f"[warn] 쓰레드 동기화 실패: {e}")
        return 0

    known = {str(p.get("thread_id")) for p in state["posts"] if p.get("thread_id")}
    added = 0
    for it in items:
        tid, text = str(it.get("id")), it.get("text") or ""
        if tid in known:
            continue
        m = re.search(r"^\s*1\.\s*'([^']+)'(.*)$", text, re.M)
        if not m:
            continue
        inst_k = norm_key(norm_inst(m.group(1)))
        cands = [j for j in jobs
                 if inst_k and (inst_k in norm_key(norm_inst(j.get("instNm"))) or norm_key(norm_inst(j.get("instNm"))) in inst_k)]
        j = match_post_to_job(text, it.get("timestamp") or "", cands, m.group(2))
        if not j:
            continue
        try:
            at = dt.datetime.strptime(it["timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        except Exception:
            at = ""
        hook = "\n".join(text.split("\n\n")[0].split("\n")[:2])
        state["posts"].append({
            "id": j["recrutPblntSn"], "instNm": norm_inst(j["instNm"]), "title": j["recrutPbancTtl"],
            "combo_idx": None, "combo_cat": None, "hook": hook, "tier": 0, "thread_id": tid, "at": at, "synced": True,
        })
        added += 1
    if added:
        state["posts"].sort(key=lambda p: p.get("at") or "")
        print(f"쓰레드 동기화: 기록에 없던 발행글 {added}건 자동 복구")
    return added


def minutes_since_last_post(state: dict):
    """이 계정의 마지막 발행 후 지난 분 — Threads API 기준(직접 올린 글 포함), 실패 시 기록 기준"""
    now = dt.datetime.now(dt.timezone.utc)
    uid, token = os.environ.get("THREADS_USER_ID"), os.environ.get("THREADS_TOKEN")
    if uid and token:
        try:
            r = requests.get(f"{THREADS_API}/{uid}/threads",
                             params={"fields": "timestamp", "limit": 1, "access_token": token}, timeout=30)
            data = r.json().get("data", []) if r.ok else []
            if data:
                ts = dt.datetime.strptime(data[0]["timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
                return (now - ts).total_seconds() / 60
        except Exception as e:
            print(f"[warn] 마지막 발행 시각 조회 실패 → 기록으로 판단: {e}")
    ats = [p.get("at") for p in state.get("posts", []) if p.get("at")]
    if ats:
        last = dt.datetime.strptime(max(ats), "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        return (now - last).total_seconds() / 60
    return None


def too_soon(state: dict, where: str) -> bool:
    gap = minutes_since_last_post(state)
    if gap is not None and gap < MIN_GAP_MIN:
        left = int(MIN_GAP_MIN - gap) + 1
        print(f"[건너뜀] 마지막 발행 후 {int(gap)}분 — 최소 간격 {MIN_GAP_MIN}분 ({where}). {left}분 뒤부터 가능")
        summary(f"### ⏭️ 건너뜀\n마지막 발행 후 {int(gap)}분 — 최소 {MIN_GAP_MIN}분 간격 규칙 ({left}분 뒤부터 가능)")
        return True
    return False


# ─────────────────────────── main ───────────────────────────
def main():
    today = dt.datetime.now(KST).date()
    jobs = requests.get(JOBS_URL, timeout=30).json()["result"]
    posts = requests.get(POSTS_URL, timeout=30).json()
    state = load_state()
    sync_from_threads(state, jobs)
    others = load_other_states()                     # [2026-10-12] 다른 계정 기록
    if others:
        print("다른 계정 기록: " + ", ".join(f"{a} {len(ps)}건" for a, ps in others.items()))
    if refresh_my_views(state) and not DRY_RUN:
        save_state(state)                            # 건너뛰는 회차에도 조회수는 저장
    if not DRY_RUN and too_soon(state, "시작 전"):   # 생성 비용도 아끼려고 먼저 확인
        return

    # [2026-10-06] 민간 공고는 본문 '지원 자격 상세'로 학력을 확인 — 확인 안 되면 다음 후보로
    excluded = set(state.get("skip_jobs", []))      # [2026-10-19] AI가 박사 이상 전용으로 확인한 공고
    # [2026-10-20] 계정별 발행 제외 공고 — 워크플로 SKIP_IDS(쉼표 구분). 다른 계정에서 조회수가 안 나온 공고를 이 계정에서만 뺄 때
    skip_env = {x.strip() for x in os.environ.get("SKIP_IDS", "").split(",") if x.strip()}
    if skip_env:
        print(f"이 계정 제외 공고 {len(skip_env)}개: " + ", ".join(sorted(skip_env)))
        excluded |= skip_env
    job, post, post_text, borrow = None, None, "", None
    for _ in range(6):
        job, tier, n_cands, borrow = pick_job(jobs, posts, state, today, excluded, others)
        if not job:
            break
        post = posts.get(str(job["recrutPblntSn"]))
        post_text = fetch_post_text(post) if post else ""
        if is_private(job) and not job.get("_manual") and not private_edu_ok(post_text):   # 수동 공고 학력은 직접 입력값이라 신뢰
            print(f"[제외] 민간 공고 학력 확인 불가(본문 없음·석사/박사 전용): {job['instNm']} / {job['recrutPbancTtl']}")
            excluded.add(str(job["recrutPblntSn"]))
            job = None
            continue
        # [2026-10-12] 클린아이는 학력 칸이 없음 → 공고문을 읽어 확인 (저장값 있으면 그대로, 못 찾으면 학력 언급 없이 발행)
        # [2026-10-15] 같은 호출로 실제 모집 직무·주력 고용형태도 확인 → 요양보호사·미화 등 현장직이나 계약직·시간제가 주력이면 제외
        #              (제목이 '직원 채용 공고'뿐이고 고용형태가 '정규직'으로 들어오는 클린아이 공고 대응 — 인천광역시사회서비스원 사례)
        if is_cleaneye(job):
            info = lookup_edu(job)
            why = blocked_reason(info)
            if why:
                print(f"[제외] 클린아이 공고 {why}: {job['instNm']} / {job['recrutPbancTtl']}")
                excluded.add(str(job["recrutPblntSn"]))
                job = None
                continue
            job = apply_edu(job)
            if job.get("acbgCondNmLst") in ("석사 이상", "박사"):
                print(f"[제외] 클린아이 공고 석사·박사 전용: {job['instNm']} / {job['recrutPbancTtl']}")
                excluded.add(str(job["recrutPblntSn"]))
                job = None
                continue
        break
    if not job:
        print("발행할 공고 없음 — 이번 회차는 건너뜀")
        summary("### ⏭️ 건너뜀\n진행 중인 공고 없음 (또는 학력 확인 불가)")
        return
    tier_label = {0: "0순위 수동 공고", 1: "1순위 신규", 2: "2순위 마감 임박", 3: "3순위 나머지 새 공고",
                  4: "4순위 다른 계정 터진 글 각색", 5: "5순위 내 글 재발행"}[tier]   # [2026-10-15]
    tier_label += " · 본문 " + ("있음" if post else "없음")

    inst = gojobs_inst(job["instNm"]) if is_gojobs(job) else norm_inst(job["instNm"])   # [2026-10-14] 나라일터는 짧은 이름
    d_left = dday(job["pbancEndYmd"], today)
    if job.get("always"):
        d_left = 99                               # [2026-10-08] 상시채용 → 시한폭탄·막차 조합 제외
    open_fact = has_open_fact(job, post_text)
    urgent = tier == 2                               # [2026-10-15] 마감 임박 → 시한폭탄/막차 조합 고정 + ⚠️ 강제
    if urgent:
        combo_idx = next(i for i, c in enumerate(COMBOS) if c["structure"] == "시한폭탄 / 막차")
        combo = COMBOS[combo_idx]
    else:
        combo_idx, combo = pick_combo(state, d_left, open_fact)
    if borrow and borrow.get("cat"):                 # [2026-10-12] 원글과 다른 유형으로 각색
        for _ in range(8):
            if combo["cat"] != borrow["cat"]:
                break
            combo_idx, combo = pick_combo(state, d_left, open_fact)
        print(f"각색 원글 [{borrow['account']} · 조회 {borrow.get('views')}]: {borrow['hook'].replace(chr(10), ' / ')} (유형 {borrow['cat']})")
    print(f"선정 [{tier_label}]: {inst} / {job['recrutPbancTtl']} / D-{d_left} (이 순위 후보 {n_cands}건)")
    print(f"조합: {combo['cat']} / {combo['person']} / {combo['structure']}" + ("" if open_fact else " (열린 조건 없음 → 포기 방지형 제외)"))

    same_job = [p for p in state["posts"] if str(p["id"]) == str(job["recrutPblntSn"])]
    hook_src = state["posts"][-10:] + [p for p in same_job if p not in state["posts"][-10:]]
    recent_hooks = [p["hook"].replace("\n", " / ") + (f"  ‖ 클로저: {p['closer']}" if p.get("closer") else "")
                    for p in hook_src if p.get("hook")]
    # [2026-10-20] 다른 계정이 이미 올린 공고면 그 글들의 훅·클로저도 반복 금지 + 유형도 다르게
    if not borrow:
        other_same = [p for ps in others.values() for p in ps
                      if str(p.get("id")) == str(job["recrutPblntSn"]) and p.get("hook")]
        if other_same:
            used_cats = {p.get("combo_cat") for p in other_same if p.get("combo_cat")}
            if not urgent and used_cats:
                for _ in range(8):
                    if combo["cat"] not in used_cats:
                        break
                    combo_idx, combo = pick_combo(state, d_left, open_fact)
            for p in other_same[-3:]:
                recent_hooks.insert(0, "[다른 계정에 이미 올라간 같은 공고 글 — 같은 팩트로 쓰되 훅·클로저·장면·유형을 완전히 다르게] "
                                    + p["hook"].replace("\n", " / ") + (f"  ‖ 클로저: {p['closer']}" if p.get("closer") else ""))
            print(f"다른 계정에 이미 올라간 공고 ({len(other_same)}건) → 다른 유형·문장으로 작성")
    if borrow and borrow.get("hook"):                # 원글 훅·클로저를 반복 금지 목록 맨 앞에
        recent_hooks.insert(0, "[다른 계정 원글 — 이 공고의 같은 팩트로 쓰되 훅·클로저·장면·유형을 완전히 다르게] "
                            + borrow["hook"].replace("\n", " / ") + (f"  ‖ 클로저: {borrow['closer']}" if borrow.get("closer") else ""))
    result = generate(job, inst, d_left, combo, post_text, recent_hooks, urgent)
    if result and result.get("_skip"):              # [2026-10-19] 박사 이상 전용 → 기록해두고 다음 회차부터 후보에서 제외
        if not DRY_RUN:
            sk = state.setdefault("skip_jobs", [])
            if str(job["recrutPblntSn"]) not in sk:
                sk.append(str(job["recrutPblntSn"]))
            save_state(state)
        summary(f"### ⏭️ 건너뜀\n{inst}: {result['_skip']} (다음 회차부터 후보 제외)")
        return
    if result is None:
        return
    comment = build_comment(post, d_left)
    logo_url, logo_msg = resolve_logo(inst, job, state)
    print(f"로고: {logo_msg}" + (f" → {logo_url}" if logo_url else ""))

    print("\n" + "=" * 40 + "\n" + result["text"] + "\n" + "=" * 40)
    if comment:
        print(f"[첫 댓글]\n{comment}")

    md = (f"### {'🧪 DRY RUN' if DRY_RUN else '✅ 발행'} — {inst} (D-{d_left}) · {tier_label}\n"
          f"지정 유형: {combo['cat']} / {combo['structure']} → 선택: {result.get('type')} / {result.get('cat')}\n\n로고: {logo_msg}\n\n```\n{result['text']}\n```\n")
    if logo_url:
        md += f'\n<img src="{logo_url}" width="420">\n\n'
    if comment:
        md += f"첫 댓글:\n```\n{comment}\n```\n"

    if DRY_RUN:
        summary(md)
        print("\nDRY_RUN — 발행·기록하지 않음")
        return

    if JITTER_MAX_MIN > 0:
        wait = random.randint(0, JITTER_MAX_MIN * 60)
        print(f"랜덤 대기 {wait // 60}분 {wait % 60}초")
        time.sleep(wait)
    if too_soon(state, "발행 직전"):               # 대기하는 사이 수동 발행이 끼어든 경우
        return

    try:
        thread_id = threads_post(result["text"], image_url=logo_url)
    except Exception as e:
        if not logo_url:
            raise
        print(f"[warn] 이미지 발행 실패 → 글만 발행: {e}")
        thread_id = threads_post(result["text"])
    print(f"본문 발행 완료: {thread_id}")

    comment_id = None
    if comment:
        time.sleep(random.randint(30, 90))
        try:
            comment_id = threads_post(comment, reply_to=thread_id)
            print(f"첫 댓글 완료: {comment_id}")
        except Exception as e:
            print(f"[warn] 첫 댓글 실패: {e}")
            md += f"\n⚠️ 첫 댓글 실패: {e}\n"

    state["posts"].append({
        "id": job["recrutPblntSn"], "instNm": inst, "title": job["recrutPbancTtl"],
        "combo_idx": combo_idx, "combo_cat": result.get("cat") or combo["cat"], "hook": result["hook"],
        "closer": result["closer"], "hook_type": result.get("type"),
        "tier": tier, "logo": bool(logo_url), "urgent": urgent,
        **({"borrowed_from": borrow["account"], "orig_thread_id": borrow.get("thread_id")} if borrow else {}),
        "thread_id": thread_id, "comment_id": comment_id,
        "at": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    })
    save_state(state)
    summary(md)


if __name__ == "__main__":
    main()
