# -*- coding: utf-8 -*-
"""
쓰레드 자동발행 (지침서 v3.4 규격)
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

[2026-09-29 수정] v3.4 후킹 스타일 적용 — 유형별 비중(인물 30%/비인물 70%) + 제외 패턴 8종 + 센스 있는 오해 원칙
"""
import os, re, io, json, time, base64, random, subprocess, datetime as dt
from urllib.parse import urljoin, urlparse, quote
import requests

JOBS_URL = "https://teukgasniper.github.io/job-compass/jobs.json"
POSTS_URL = "https://teukgasniper.github.io/job-compass/job_posts.json"
HIRING_URL = "https://hiring.ddolbestory.com/"
THREADS_API = "https://graph.threads.net/v1.0"

ACCOUNT = os.environ.get("ACCOUNT", "jami").strip().lower()
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
COMMENT_LINK = os.environ.get("COMMENT_LINK", "").strip().lower() or "profile"
COMMENT_TEXT = os.environ.get("COMMENT_TEXT", "").strip() or "👆 프로필 링크 확인!"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5"
FALLBACK_MODEL = "claude-sonnet-4-6"
JITTER_MAX_MIN = int(os.environ.get("JITTER_MAX_MIN", "0") or 0)

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
DOCTOR_WORDS = ("전임의", "레지던트", "전공의", "수련의", "의사직", "전문의", "임상강사", "일반의")
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


def eligible(job: dict, today: dt.date) -> bool:
    if job.get("ongoingYn") != "Y":
        return False
    hire = job.get("hireTypeNmLst") or ""
    if not any(h in hire for h in GOOD_HIRE):
        return False
    se = job.get("recrutSeNm") or ""
    if not (any(n in se for n in NEWBIE_OK) or "무관" in se):
        return False
    title = job.get("recrutPbancTtl") or ""
    if any(w in title for w in DOCTOR_WORDS):
        return False
    if dday(job.get("pbancEndYmd", ""), today) < 1:
        return False
    return True


def score(job: dict, today: dt.date) -> float:
    s = min(int(job.get("recrutNope") or 0), 100)
    inst = norm_inst(job.get("instNm"))
    if any(b in inst for b in BRANDS):
        s += 20
    d = dday(job.get("pbancEndYmd", ""), today)
    if 1 <= d <= 10:
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


def job_key(j: dict) -> str:
    return norm_key(norm_inst(j.get("instNm"))) + "|" + norm_key(j.get("recrutPbancTtl"))


def pick_job(jobs, posts, state, today):
    history = state["posts"]
    used_ids = {str(p["id"]) for p in history}
    used_keys = {norm_key(norm_inst(p["instNm"])) + "|" + norm_key(p["title"]) for p in history}
    recent_insts = {norm_key(norm_inst(p["instNm"])) for p in history[-6:]}

    live = [j for j in jobs if eligible(j, today)]
    new = [j for j in live if str(j["recrutPblntSn"]) not in used_ids and job_key(j) not in used_keys]
    tier1 = [j for j in new if str(j["recrutPblntSn"]) in posts]
    tier2 = [j for j in new if str(j["recrutPblntSn"]) not in posts]

    def choose(cands):
        fresh = [j for j in cands if norm_key(norm_inst(j["instNm"])) not in recent_insts] or cands
        fresh.sort(key=lambda j: score(j, today), reverse=True)
        top = fresh[:5]
        return random.choices(top, weights=[max(score(j, today), 1) for j in top], k=1)[0]

    if tier1:
        return choose(tier1), 1, len(tier1)
    if tier2:
        return choose(tier2), 2, len(tier2)

    recent_ids = {str(p["id"]) for p in history[-12:]}
    repeat = [j for j in live if str(j["recrutPblntSn"]) not in recent_ids] or live
    if not repeat:
        return None, 0, 0

    def times(j):
        return sum(1 for p in history if str(p["id"]) == str(j["recrutPblntSn"]))

    def last_at(j):
        ts = [p["at"] for p in history if str(p["id"]) == str(j["recrutPblntSn"])]
        return max(ts) if ts else ""

    repeat.sort(key=lambda j: (
        times(j),
        str(j["recrutPblntSn"]) not in posts,
        last_at(j),
        -score(j, today),
    ))
    fresh = [j for j in repeat if norm_key(norm_inst(j["instNm"])) not in recent_insts] or repeat
    return fresh[0], 3, len(repeat)


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
    text = re.sub(r"(?s)<[^>]+>", "\n", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z#0-9]+;", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:4000]


# ─────────────────────────── 후킹 유형 (지침서 v3.4 6장) ───────────────────────────
# 카테고리: person(인물형 30%) / monologue(1인칭독백 20%) / fact(팩트충격 20%) / urgent(긴급 15%) / sniper(특가스나이퍼 15%)
COMBOS = [
    # 인물 대화형 30% — 반드시 "센스 있는 오해 + 리얼한 부정 반응 → 역전"
    {"cat": "person", "person": "부모님", "structure": "오해→부정반응→역전", "emoji": "📍",
     "desc": "기관 업무를 일상 한 마디로 재정의 → 부모님의 진짜 오해(사기치지 말라, 무슨 직업이냐고) → 공고 보여줬더니 전환"},
    {"cat": "person", "person": "여자친구", "structure": "오해→부정반응→역전", "emoji": "📍",
     "desc": "기관 업무 한 마디 재정의 → 여자친구 진짜 오해(차일 뻔함, 미쳤냐고) → 공고 보여줬더니 전환"},
    {"cat": "person", "person": "회사동료/친구", "structure": "동료가 넣었음→나도 발견", "emoji": "📍",
     "desc": "동료가 점심에 지원서 제출 누르는 거 봤다 / 뭔지 봤더니 나도 조건 맞음"},
    # 1인칭 독백형 20%
    {"cat": "monologue", "person": "본인", "structure": "어차피 안 되겠지→역전", "emoji": "📍",
     "desc": "어차피 안 되겠지 하고 넣었는데 서류 붙어버림 / 조건 보니 나도 가능"},
    {"cat": "monologue", "person": "본인", "structure": "조용히 넣었다 / 다짐·선언 / 발견", "emoji": "📍",
     "desc": "조용히 넣었다 — N명이면 확률 있다 / 서울 포기하고 ○○ 가기로 했음 / 산책하다 관리사무소 봤는데 공기업이었음"},
    # 팩트 충격형 20%
    {"cat": "fact", "person": "—", "structure": "숫자·규모 충격", "emoji": "📍",
     "desc": "매출 N조짜리 공기업이 학력무관 / 자본금 N조에 서울 근무로 N명 / 역대 최대 N명인데 학력무관"},
    {"cat": "fact", "person": "—", "structure": "근속·안정·조건 나열", "emoji": "📍",
     "desc": "근속 N년이면 들어간 사람이 안 나온다는 뜻 / N년째 운영 중인 공기업이 역대 최대로 뽑음"},
    # 긴급형 15%
    {"cat": "urgent", "person": "—", "structure": "경고", "emoji": "⚠️",
     "desc": "N명 학력무관인데 안 넣는 게 사기임 / 이 조건 보고도 안 넣으면 진짜 바보"},
    {"cat": "urgent", "person": "—", "structure": "시한폭탄 / 막차", "emoji": "⚠️",
     "desc": "D-N이라 이번 주 안에 넣어야 됨 / 오후 3시에 접수 닫힘 — 6시까지인 줄 알고 놓치지 마"},
    # 특가스나이퍼형 15%
    {"cat": "sniper", "person": "—", "structure": "포기 방지 / 바보 손실", "emoji": "📍",
     "desc": "스펙 없어서 공기업 접은 사람 다시 펴 / 이거 안 넣는 게 손해가 아니라 바보임"},
    {"cat": "sniper", "person": "—", "structure": "상황 저격", "emoji": "📍",
     "desc": "서울 월세 80 내면서 출퇴근 3시간 vs ○○에서 연봉 N만 정규직 / 취준생인데 이 공채 모르면~"},
]

# 유형별 가중치 (비중 반영)
CAT_WEIGHTS = {"person": 30, "monologue": 20, "fact": 20, "urgent": 15, "sniper": 15}


def pick_combo(state, d_left: int):
    recent = state["posts"][-10:]
    recent_idxs = {p.get("combo_idx") for p in recent if p.get("combo_idx") is not None}
    recent_cats = [p.get("combo_cat") for p in recent[-2:] if p.get("combo_cat")]

    # 최근 2건이 인물형이면 비인물형 강제
    force_nonperson = all(c == "person" for c in recent_cats) and len(recent_cats) == 2

    pool = []
    for i, c in enumerate(COMBOS):
        if i in recent_idxs:
            continue
        if force_nonperson and c["cat"] == "person":
            continue
        if d_left > 7 and c["structure"] in ("시한폭탄 / 막차",):
            continue
        pool.append(i)

    if not pool:
        pool = list(range(len(COMBOS)))
        if force_nonperson:
            pool = [i for i in pool if COMBOS[i]["cat"] != "person"] or pool

    # 가중 랜덤 — 유형별 비중 반영
    weights = [CAT_WEIGHTS.get(COMBOS[i]["cat"], 10) for i in pool]
    idx = random.choices(pool, weights=weights, k=1)[0]
    return idx, COMBOS[idx]


# ─────────────────────────── Claude 프롬프트 (v3.4) ───────────────────────────
SYSTEM_PROMPT = """너는 한국 채용정보 쓰레드 계정의 후킹글 작가다. 아래 규격을 100% 지킨다.

[핵심 원칙]
- 과장은 OK, 거짓은 NO. 훅·클로저는 자극적으로 과장 가능. 리스트 5개의 수치·조건은 반드시 제공된 [공고 데이터]/[본문 발췌]에 있는 팩트만.
- 후킹은 항상 강력하게. 설명하지 말고 궁금하게. 읽고 "뭔데?"가 떠올라야 함.
- 기관 고유 소재로 쓴다. 다른 기관에 복붙 불가능해야 함.
- 클로저도 매번 다르게. 고정 문장 반복 금지.

[포맷]
- 훅: 최대 2줄. 맨 앞에 지정된 이모지(📍 또는 ⚠️) 1개. 기관명·줄임말 절대 넣지 않음.
- 리스트: 정확히 5개. 1번은 반드시 '기관 정식명칭' 작은따옴표 + 핵심 팩트.
  필수 팩트: 고용형태, 학력조건, 마감일. 각 항목 짧게 한 줄.
- 클로저: 1줄. 과장 OK. 인물형이면 훅과 스토리 연결.
- 반말 구어체. 링크·해시태그 금지. 훅 앞 이모지 외 이모지 금지.

[제외 패턴 8종 — 절대 사용 금지]
1. 질문유도형 ("~인지 알아?")
2. 일상 스토리형 ("전화/신고했더니 공기업이었음")
3. 생활 연결형 ("~할 때 신고하는 곳 → 그 기관이 사람 뽑음", "~하는 그곳", "알고 보니 이 공단이")
4. 비교형 ("A vs B → 후자가 정규직")
5. 어린 시절 연결형 ("기차 좋아하던 7살의 나한테 할 말 생김")
6. 오해 없는 질문형 반응 ("LH냐?" → "SH공사" → "좋은 데네" — 진짜 오해 아니고 그냥 질문)
7. 기관 업무 프로세스 설명형 ("신고하면→조사해서→퇴출시키는 곳" — 정보 전달이 됨)
8. 정보 전달형 동료 멘트 ("~하는 공공기관 있대" — 동료가 기관을 설명해주는 구조)

[인물 대화형 — 센스 있는 오해 원칙]
인물형의 핵심은 "기관 업무를 일상 한 마디로 재정의했을 때 생기는 진짜 오해"다.
오해가 클수록 반전이 세고, 반전이 셀수록 터진다.

OK (진짜 오해 + 리얼한 부정 반응):
- "나 돈 찍는 데 취직한다" → "사기치지 말라고" (조폐공사)
- "나 돈 만드는 회사 간다" → "사기꾼이냐고 차일 뻔함" (조폐공사)
- "우리 울산 갈까?" → "미쳤냐고" (에너지공단)
- "나 에너지 쪽 취직한다" → "레드불이냐?" (에너지공단)
- "나 김치 수출하는 공기업 간다" → "김치 공장이야?" (농수산식품유통공사)
- "나 도시 만드는 공기업 간다" → "공사판이냐?" (김포도시공사)

NG (오해 없는 일반 질문 → 밋밋한 긍정):
- "LH냐?" → "SH공사" → "더 낫네" ❌
- "어딘데?" → 설명 → "좋은 데네" ❌
- "뭐하는 덴데?" → 설명 → "괜찮네" ❌

[비인물형 — 이런 감각으로]
팩트 충격: "매출 8조짜리 공기업이 학력무관으로 뽑고 있음"
긴급: "66명 역대 최대인데 학력무관이면 안 넣는 게 사기임"
특가스나이퍼: "스펙 없어서 공기업 접은 사람 다시 펴 — 학력 칸 자체가 없는 정규직 66명"
1인칭 독백: "조용히 넣었다 — 66명이면 확률 있다고 봤음"
상황 저격: "서울 월세 80 내면서 출퇴근 3시간 vs 김포에서 연봉 6,200만 정규직"

[고정 클로저 금지 — 이 문장들 사용 금지]
"세 번 확인했는데 진짜임", "모르는 사람이 많을수록 경쟁률은 낮음",
"넘기려다 공고 열어본 사람이 붙는 거임", "말하고 싶으면 일단 넣어야 됨",
"합격하면 그때 말하려고", "동료는 이미 넣었고 나만 안 넣었음"

[팩트 주의]
- 고용형태가 여러 개면 데이터 그대로 반영.
- 평균 연봉은 전 직원 평균이지 신입 초봉이 아님.
- "필기 없음", "자소서 없음" 같은 표현은 데이터에 있을 때만.
- 데이터에 없는 내용은 리스트에 넣지 않는다.

[검증된 베스트]
📍엄마한테 "나 돈 찍는 데 취직한다" 했더니
사기치지 말라고 하길래 공고 보여줬음
1. '한국조폐공사' 57명 정규직 채용
2. 화폐·여권·신분증 만드는 공기업
3. 학력 안 봄 - 누구나 지원 가능
4. 대전·서울·경산·부여 배치
5. 10/2 마감 - 아직 열흘 남음
공고 보더니 본인도 넣겠다고 함

⚠️취준생 심장 약하면 스크롤 멈춰
1. '한국토지주택공사' 235명 정규직
2. 서류에서 자소서 평가 아예 없앰
3. 학력·나이·경력 제한 전부 없음
4. 고졸 전형 24명 별도 운영
5. 접수 9월 29일 마감
자소서 없는 235명 공채는 다음에 없음

📍조용히 넣었다 — 66명이면 확률 있다고 봤음
1. '한국농수산식품유통공사' 66명 정규직
2. K-Food 수출 + 농수산물 유통 전담
3. 학력무관 — 고졸 전형 9명 별도
4. 행정·농업·AI전산 등 6개 분야
5. 마감 10/13 — 필기 11/1
안 되면 말고 — 근데 되면 연봉 7,800만임

📍스펙 없어서 공기업 접은 사람 다시 펴
학력 칸 자체가 없는 정규직 66명
1. '한국농수산식품유통공사' 66명 정규직
2. 5급 57명 + 6급(고졸) 9명 — 역대 최대
3. 행정·농업·AI전산·산업안전 등 6개 분야
4. 전국 배치 — 평균연봉 약 7,800만
5. 마감 10/13 — 필기 11/1
포기하기엔 66자리가 너무 많음

[출력]
설명 없이 JSON 객체 하나만 출력. 코드블록 금지.
{"hook": "훅(줄바꿈은 \\n, 최대 2줄)", "items": ["1번 내용", "2번", "3번", "4번", "5번"], "closer": "클로저 1줄"}
items 각 원소에는 번호("1.")를 붙이지 말 것.
"""


def build_user_prompt(job, inst, d_left, combo, post_text, recent_hooks):
    end = dt.datetime.strptime(job["pbancEndYmd"], "%Y%m%d")
    data = {
        "기관 정식명칭(리스트 1번에 '따옴표'로)": inst,
        "공고명": job.get("recrutPbancTtl"),
        "고용형태": job.get("hireTypeNmLst"),
        "신입/경력": job.get("recrutSeNm"),
        "모집인원": job.get("recrutNope"),
        "학력조건": job.get("acbgCondNmLst"),
        "근무지역": job.get("workRgnNmLst"),
        "직무분야(NCS)": job.get("ncsCdNmLst"),
        "마감일": f"{end.month}월 {end.day}일",
        "D-day": f"D-{d_left}",
    }
    for k_src, k_out in (("yearIncome", "연봉(클린아이)"), ("judgeMethod", "전형방법(클린아이)")):
        if job.get(k_src):
            data[k_out] = job[k_src]

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

    lines += [
        "",
        "[공고 데이터]",
        json.dumps(data, ensure_ascii=False, indent=1),
        "",
        "[본문 발췌 — 팩트 보강용, 여기 있는 내용만 추가 팩트로 사용 가능]",
        post_text or "(없음)",
    ]
    if recent_hooks:
        lines += ["", "[최근 발행한 훅 — 이것들과 문장·구조가 겹치면 안 됨]"] + [f"- {h}" for h in recent_hooks]
    lines += ["", "위 규격대로 쓰레드 글 1개를 JSON으로 출력해."]
    return "\n".join(lines)


def call_claude(system, user, model):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["CLAUDE_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": model, "max_tokens": 1000, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    if r.status_code == 404 and model != FALLBACK_MODEL:
        print(f"[warn] 모델 {model} 없음 → {FALLBACK_MODEL}로 재시도")
        return call_claude(system, user, FALLBACK_MODEL)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def parse_and_validate(raw: str, combo: dict, inst: str = ""):
    emoji = combo["emoji"]
    clean = re.sub(r"```(json)?", "", raw).strip()
    m = re.search(r"\{.*\}", clean, re.S)
    if not m:
        return None, "JSON 없음"
    try:
        d = json.loads(m.group(0))
    except Exception as e:
        return None, f"JSON 파싱 실패: {e}"
    hook = (d.get("hook") or "").strip()
    items = [re.sub(r"^\s*\d+[\.\)]\s*", "", str(x)).strip() for x in (d.get("items") or [])]
    closer = (d.get("closer") or "").strip()

    hook_lines = [l for l in hook.split("\n") if l.strip()]
    if not hook_lines or len(hook_lines) > 2:
        return None, "훅 줄 수 오류"
    if not hook.startswith(emoji):
        return None, f"훅 이모지 오류 (필요: {emoji})"
    if inst:
        full = norm_key(inst)
        short = re.sub(r"^(한국|국가|국립|재단법인|대한)", "", full)
        hook_k = norm_key(hook)
        for v in {full, short}:
            if len(v) >= 3 and v in hook_k:
                return None, f"훅에 기관명('{v}') 들어감 — 기관명은 리스트 1번에만"
    # 생활 연결형 차단
    if re.search(r"(그곳|그 곳|하는 곳|하던 곳|던 그|알고 보니|알고보니|이 공단이|이 기관이|이 공사가|이 재단이|거기였음|곳이었음|거였음)", hook):
        return None, "생활 연결형 훅 차단"
    # 비인물형인데 인물 대화체가 들어간 경우 차단
    if combo["cat"] != "person" and re.search(r"(했더니|하길래|보여줬|보여드렸|말했더니|했는데$)", hook):
        return None, "비인물형인데 인물 대화체(했더니/하길래/보여줬) 포함 — 재생성"
    # 고정 클로저 차단
    banned_closers = ["세 번 확인했는데 진짜임", "모르는 사람이 많을수록 경쟁률은 낮음",
                      "넘기려다 공고 열어본 사람이 붙는 거임", "말하고 싶으면 일단 넣어야 됨",
                      "합격하면 그때 말하려고", "동료는 이미 넣었고 나만 안 넣었음"]
    if any(norm_key(bc) == norm_key(closer) for bc in banned_closers):
        return None, "고정 클로저 사용 — 다른 클로저로 재생성"
    if len(items) != 5 or any(not x for x in items):
        return None, "리스트 5개 아님"
    if not re.match(r"^'[^']+'", items[0]):
        return None, "1번에 '기관명' 없음"
    if not closer or "\n" in closer:
        return None, "클로저 오류"
    body = hook + "\n\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(items)) + "\n\n" + closer
    if re.search(r"https?://|#\S", body):
        return None, "링크/해시태그 포함"
    if len(body) > 490:
        return None, f"길이 초과 ({len(body)}자)"
    return {"hook": hook, "items": items, "closer": closer, "text": body}, None


def generate(job, inst, d_left, combo, post_text, recent_hooks):
    user = build_user_prompt(job, inst, d_left, combo, post_text, recent_hooks)
    err = None
    for attempt in range(3):
        u = user if not err else user + f"\n\n[이전 출력 오류: {err}] 규격을 다시 지켜서 출력해."
        raw = call_claude(SYSTEM_PROMPT, u, CLAUDE_MODEL)
        result, err = parse_and_validate(raw, combo, inst)
        if result:
            return result
        print(f"[warn] 생성 {attempt+1}회차 검증 실패: {err}")
    raise RuntimeError(f"후킹글 생성 실패: {err}")


# ─────────────────────────── 기관 로고 카드 ───────────────────────────
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
            if subprocess.run(["git", "pull", "--rebase"]).returncode == 0 and \
               subprocess.run(["git", "push"]).returncode == 0:
                return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            time.sleep(5)
    except Exception as e:
        print(f"[warn] 로고 push 실패: {e}")
    return None


def raw_url(path, ref="main"):
    return f"https://raw.githubusercontent.com/{REPO}/{ref}/" + "/".join(quote(p) for p in path.split("/"))


def resolve_logo(inst, job, state):
    if not USE_LOGO:
        return None, "로고 사용 안 함"
    path = find_logo_file(inst)
    if path:
        return raw_url(path), f"로고 있음 ({path})"

    tried = state.setdefault("logo_tried", {})
    last = tried.get(inst)
    if last and (dt.date.today() - dt.date.fromisoformat(last)).days < LOGO_RETRY_DAYS:
        return None, "로고 없음 (최근 자동수집 실패 — 글만 발행)"

    card = auto_collect_logo(inst, job)
    if DRY_RUN:
        return None, "자동수집 성공 (DRY_RUN이라 저장 안 함)" if card else "로고 없음 · 자동수집 실패"
    if not card:
        tried[inst] = dt.date.today().isoformat()
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
        if len(cands) > 1:
            n = re.search(r"(\d+)\s*명", m.group(2))
            if n:
                cands = [j for j in cands if str(j.get("recrutNope") or "") == n.group(1)]
        if len(cands) != 1:
            continue
        j = cands[0]
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


# ─────────────────────────── main ───────────────────────────
def main():
    today = dt.datetime.now(KST).date()
    jobs = requests.get(JOBS_URL, timeout=30).json()["result"]
    posts = requests.get(POSTS_URL, timeout=30).json()
    state = load_state()
    sync_from_threads(state, jobs)

    job, tier, n_cands = pick_job(jobs, posts, state, today)
    if not job:
        print("진행 중인 공고 자체가 없음 — 이번 회차는 건너뜀")
        summary("### ⏭️ 건너뜀\n진행 중인 공고 없음")
        return
    tier_label = {1: "1순위 본문 있음", 2: "2순위 본문 없음", 3: "3순위 재발행"}[tier]

    inst = norm_inst(job["instNm"])
    d_left = dday(job["pbancEndYmd"], today)
    post = posts.get(str(job["recrutPblntSn"]))
    combo_idx, combo = pick_combo(state, d_left)
    print(f"선정 [{tier_label}]: {inst} / {job['recrutPbancTtl']} / D-{d_left} (이 순위 후보 {n_cands}건)")
    print(f"조합: {combo['cat']} / {combo['person']} / {combo['structure']}")

    post_text = fetch_post_text(post) if post else ""
    same_job = [p for p in state["posts"] if str(p["id"]) == str(job["recrutPblntSn"])]
    hook_src = state["posts"][-8:] + [p for p in same_job if p not in state["posts"][-8:]]
    recent_hooks = [p["hook"].replace("\n", " / ") for p in hook_src if p.get("hook")]
    result = generate(job, inst, d_left, combo, post_text, recent_hooks)
    comment = build_comment(post, d_left)
    logo_url, logo_msg = resolve_logo(inst, job, state)
    print(f"로고: {logo_msg}" + (f" → {logo_url}" if logo_url else ""))

    print("\n" + "=" * 40 + "\n" + result["text"] + "\n" + "=" * 40)
    if comment:
        print(f"[첫 댓글]\n{comment}")

    md = (f"### {'🧪 DRY RUN' if DRY_RUN else '✅ 발행'} — {inst} (D-{d_left}) · {tier_label}\n"
          f"유형: {combo['cat']} / {combo['person']} / {combo['structure']}\n\n로고: {logo_msg}\n\n```\n{result['text']}\n```\n")
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
        "combo_idx": combo_idx, "combo_cat": combo["cat"], "hook": result["hook"],
        "tier": tier, "logo": bool(logo_url),
        "thread_id": thread_id, "comment_id": comment_id,
        "at": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    })
    save_state(state)
    summary(md)


if __name__ == "__main__":
    main()
