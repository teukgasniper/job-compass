# -*- coding: utf-8 -*-
"""
쓰레드 자동발행 (지침서 v3.3 규격)
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
NEWBIE_OK = ("신입",)                # '신입', '신입+경력', '신입/경력'
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
    """지침서 4장 조건 (본문 글 여부는 pick_job에서 우선순위로 처리)"""
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
    if dday(job.get("pbancEndYmd", ""), today) < 1:   # D-0·마감 지난 공고 제외
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
    try:  # 새로 올라온 공고 가산 (3일 이내 등록)
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
    """
    우선순위
      1순위: 본문 글(hiring03) 있는 새 공고
      2순위: 본문 글 없는 새 공고
      3순위: 새 공고가 없으면 이미 올린 공고 재발행 — 반복 횟수 적은 것 → 오래전에 올린 것 → 인기순
    같은 순위 안에서는 인기 점수순(상위 5개 중 가중 랜덤), 최근 6건과 같은 기관은 뒤로
    반환: (job, tier, 후보 수)
    """
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

    # 3순위: 재발행 — 최근 12건(약 하루)에 올린 공고는 제외, 그래도 없으면 전부 허용
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
        times(j),                                   # 덜 반복된 것 먼저
        str(j["recrutPblntSn"]) not in posts,       # 본문 글 있는 것 먼저
        last_at(j),                                 # 오래전에 올린 것 먼저
        -score(j, today),                           # 인기순
    ))
    fresh = [j for j in repeat if norm_key(norm_inst(j["instNm"])) not in recent_insts] or repeat
    return fresh[0], 3, len(repeat)


# ─────────────────────────── 본문 글에서 팩트 보강 ───────────────────────────
def fetch_post_text(post: dict) -> str:
    """hiring03 본문을 Blogger 피드로 읽어 텍스트만 추출 (실패 시 빈 문자열)"""
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


# ─────────────────────────── 후킹 조합 순환 (지침서 6장) ───────────────────────────
COMBOS = [
    ("부모님", "반응 역전", "기관 업무를 일상 한 마디로 재정의", "📍"),
    ("엄마", "세대 연결", "기관 고유 소재", "📍"),
    ("아버지", "반응 역전", "오해→사실", "📍"),
    ("여자친구", "설득→반응 역전", "오해→사실", "📍"),
    ("여자친구", "먼저 찾아줌", "상황저격형", "📍"),
    ("여자친구", "몰래 지원→합격 고백", "기관 고유 클로저", "📍"),
    ("회사동료", "경쟁 (동료가 먼저 넣음)", "손실회피형", "📍"),
    ("회사동료", "발견 계기 (점심시간)", "숨은공채형", "📍"),
    ("본인(독백)", "어차피 안 되겠지→역전", "역전형", "📍"),
    ("본인(독백)", "발견 계기", "기관 고유 소재", "📍"),
    ("친구", "친구 경험→나도 발견", "상황저격형", "📍"),
    ("—", "팩트 한 줄", "저격형", "📍"),
    ("—", "팩트 한 줄", "오류의심형", "📍"),
    ("—", "팩트 한 줄", "경고형", "⚠️"),
    ("—", "마감 카운트다운", "시한폭탄형", "⚠️"),
]


def pick_combo(state, d_left: int):
    recent = [p.get("combo_idx") for p in state["posts"][-10:]]
    pool = [i for i in range(len(COMBOS)) if i not in recent]
    if d_left > 7:  # 마감 여유 있으면 시한폭탄형 제외
        pool = [i for i in pool if COMBOS[i][2] != "시한폭탄형"] or pool
    if not pool:
        pool = list(range(len(COMBOS)))
    idx = random.choice(pool)
    return idx, COMBOS[idx]


# ─────────────────────────── Claude 프롬프트 ───────────────────────────
SYSTEM_PROMPT = """너는 한국 채용정보 쓰레드 계정의 후킹글 작가다. 아래 규격을 100% 지킨다.

[핵심 원칙]
- 과장은 OK, 거짓은 NO. 훅·클로저는 자극적으로 과장 가능. 리스트 5개의 수치·조건은 반드시 제공된 [공고 데이터]/[본문 발췌]에 있는 팩트만.
- 후킹은 항상 강력하게. 설명하지 말고 궁금하게. 읽고 "뭔데?"가 떠올라야 함.
- 기관 고유 소재로 쓴다. 기관이 하는 일·만드는 것·위치·산업 특성을 훅과 클로저에 녹여서 다른 기관에 복붙 불가능해야 함.

[포맷]
- 훅: 최대 2줄. 맨 앞에 지정된 이모지(📍 또는 ⚠️) 1개. 기관명·줄임말(예: '철도공단', '에너지공단') 절대 넣지 않음 — 하는 일로 돌려 말함(예: '기차 선로 까는 데'). 모집 인원은 넣어도 됨.
- 리스트: 정확히 5개. 1번은 반드시 '기관 정식명칭'을 작은따옴표로 감싸 시작 + 핵심 팩트(인원·고용형태). 
  필수 팩트: 고용형태, 학력조건, 마감일(보통 5번). 각 항목 짧게 한 줄.
- 클로저: 1줄. 과장 OK. 훅과 스토리가 이어지게 (예: "보여줬음" → "같이 넣겠다고 함"). 
- 반말 구어체. 링크·해시태그 금지. 훅 앞 이모지 외 이모지 쓰지 않음.

[터지는 훅 공통 패턴 — 반드시 이 중 하나 이상]
1. 기관 업무를 누구나 아는 물건·단어 한 마디로 재정의 — 단, 인물의 대화 속에서. ("돈 찍는 데", "울산 갈까?", "냉장고 1등급 스티커")
2. 구체적 인물의 리얼한 반응 — 웃기거나 찔리는 반응 ("사기치지 말라", "미쳤냐고", "무슨 직업이냐고 비웃음")
3. 훅 → 클로저 스토리 연결 — 클로저에서 그 인물의 반응이 뒤집힘 ("보여줬음" → "같이 넣겠다고 함")
4. 팩트가 강하면 경고형 한 줄 — 설명 없이 팩트만으로 스크롤 멈춤

[생활 연결형 차단 — 가장 자주 나오는 실패]
- 기관을 설명하는 수식어로 훅을 만들지 말 것: "~하는 그곳", "~하던 곳", "알고 보니 이 공단이", "이 기관이 다 관리하는 거였음" 전부 금지.
- 일상 경험 → "그게 이 기관이었음" 반전 구조 금지. 기관은 '내가 거기 간다/넣었다'는 말 속에서만 등장.
- 실제로 사람이 입 밖으로 낼 법한 말만. 아무도 안 하는 설명형 문장("전기 아끼라고 잔소리하는 회사")은 억지.

[나쁜 예 — 이렇게 쓰면 실패]
✗ ⚠️매달 월급에서 건강보험료 떼가는 그곳 / 내일이면 지원서 접수 끝남  (생활 연결형: 기관을 설명하는 수식어)
✗ 📍엄마가 평생 "전기 아껴 써라" 잔소리하던 그 이유 / 이 공단이 다 관리하는 거였음  (일상 → 알고 보니 이 기관)
✗ 📍엄마한테 "나 전기 아끼라고 잔소리하는 회사 간다" 했더니 / 그런 회사가 어딨냐고 해서 공고 보여줬음  (아무도 안 하는 억지 말 + 밋밋한 반응)

[좋은 예 — 이 감각으로]
✓ 📍엄마한테 "나 냉장고 1등급 스티커 붙이는 데 간다" 했더니 / 그게 무슨 직업이냐고 비웃길래 공고 보여줬음  →  클로저: 공고 보더니 집 냉장고 등급부터 확인함
✓ 📍채용형 인턴이라 대충 넘기려다 끝까지 읽었는데 / 학력 칸이 아예 없었음
✓ 📍엄마한테 "나 돈 찍는 데 취직한다" 했더니 / 사기치지 말라고 하길래 공고 보여줬음

[금지 패턴]
- 질문유도형 ("~인지 알아?"), 일상 스토리형 ("전화/신고했더니 공기업이었음"),
  생활 연결형 ("~할 때 신고하는 곳 → 그 기관이 사람 뽑음"), 비교형 ("A vs B").
- 아무도 안 할 억지 대화를 지어내는 훅, 잡학 트리비아 톤, AI가 짜낸 티 나는 훅.
- 고정 클로저 금지: "세 번 확인했는데 진짜임", "모르는 사람이 많을수록 경쟁률은 낮음",
  "넘기려다 공고 열어본 사람이 붙는 거임", "말하고 싶으면 일단 넣어야 됨", "합격하면 그때 말하려고",
  "동료는 이미 넣었고 나만 안 넣었음".

[팩트 주의]
- 고용형태가 여러 개면 데이터 그대로 반영 (예: "정규직 외"), 대체인력·비정규직을 정규직이라고 쓰지 말 것.
- 평균 연봉은 전 직원 평균이지 신입 초봉이 아님. 연봉을 쓸 거면 무엇인지 명시.
- "필기 없음", "자소서 없음" 같은 전형 표현은 데이터에 명시돼 있을 때만.
- 데이터에 없는 내용은 리스트에 넣지 않는다.

[검증된 베스트 예시]
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

📍여자친구한테 "우리 울산 갈까?" 했더니
미쳤냐고 하길래 이거 보여줬음

1. '한국에너지공단' 93명 정규직
2. 학력 안 봄 - 블라인드 채용
3. 울산 본사 + 전국 지역본부 배치
4. 기계·전기·전산·화공 전 직군
5. 10월 1일 마감 - D-9

보여줬더니 같이 넣겠다고 함

[출력]
설명 없이 JSON 객체 하나만 출력. 코드블록 금지.
{"hook": "훅(줄바꿈은 \\n, 최대 2줄)", "items": ["1번 내용", "2번", "3번", "4번", "5번"], "closer": "클로저 1줄"}
items 각 원소에는 번호("1.")를 붙이지 말 것.
"""


def build_user_prompt(job, inst, d_left, combo, post_text, recent_hooks):
    person, structure, tone, emoji = combo
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
        "[이번 글의 조합]",
        f"- 인물: {person}",
        f"- 구조: {structure}",
        f"- 톤: {tone}",
        f"- 훅 맨 앞 이모지: {emoji}",
        "- 구조가 '세대 연결'·'발견 계기'여도 기관은 반드시 인물의 대화·반응 속에서 등장 (생활 연결형 금지)",
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


def parse_and_validate(raw: str, emoji: str, inst: str = ""):
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
                return None, f"훅에 기관명('{v}') 들어감 — 기관명은 리스트 1번에만. 훅에서는 하는 일로 돌려 말할 것"
    if re.search(r"(그곳|그 곳|하는 곳|하던 곳|던 그|알고 보니|알고보니|이 공단이|이 기관이|이 공사가|이 재단이|거기였음|곳이었음|거였음)", hook):
        return None, "생활 연결형 훅 (기관을 설명하는 수식어·'알고 보니' 구조) — 인물의 대화·반응 속에서 기관을 재정의할 것"
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
        result, err = parse_and_validate(raw, combo[3], inst)
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
    """홈페이지 열기 — meta refresh·자바스크립트 이동까지 따라감"""
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
    """위키데이터 검색 결과가 기관명과 정확히 일치하는지 (한글 라벨·별칭 포함)"""
    names = [e.get("label", ""), (e.get("match") or {}).get("text", "")] + (e.get("aliases") or [])
    return any(norm_key(n) == norm_key(inst) for n in names if n)


def wd_get(params):
    """위키데이터·위키미디어 요청 (429 재시도)"""
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
    """logos/ 폴더에서 기관명으로 카드 찾기 (띄어쓰기·(재) 등 무시)"""
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
    try:  # 위키데이터 공식 홈페이지 (라벨이 기관명과 맞을 때만)
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
    """흰 배경 가로형 로고 카드 — 쓰레드 피드에서 납작하고 꽉 차게 (레퍼런스: aT·질병관리청 스타일)"""
    from PIL import Image, ImageChops
    im = im.convert("RGBA")
    flat = Image.new("RGBA", im.size, (255, 255, 255, 255)); flat.alpha_composite(im)
    box = ImageChops.difference(flat.convert("RGB"), Image.new("RGB", im.size, "white")).getbbox()
    if box: im = im.crop(box)
    w, h = im.size
    ratio = min(max(w / h * 1.12, 3.2), 5.0)          # 가로:세로 3.2~5.0 (피드에서 납작하게)
    cw = int(min(CARD_W, max(720, w * 3 / 0.86)))     # 원본의 3배 이상은 키우지 않음
    ch = int(cw / ratio)
    s = min(cw * 0.86 / w, ch * 0.78 / h)
    im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    card = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    card.alpha_composite(im, ((cw - im.width) // 2, (ch - im.height) // 2))
    return card.convert("RGB")


def ai_is_logo(card, inst) -> bool:
    """Claude가 이미지를 보고 공식 대표 로고가 맞는지 판별 (1건 1~2원)"""
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
    """Claude 웹 검색으로 기관 CI(로고) 소개 페이지 + 공식 홈페이지 주소 찾기 (새 기관일 때만)"""
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
    """CSS 배경이미지로 넣은 로고 (#logo a {background:url(...)}) 찾기"""
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
    """<h1 class="logo"><svg>...</svg></h1> 처럼 코드로 박힌 로고"""
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
    """홈페이지에서 로고 후보 모으기: img 태그 + CSS 배경 + 인라인 SVG"""
    from bs4 import BeautifulSoup
    r = fetch_page(site)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    cands = []  # (점수, 종류, 값)
    for t in soup.find_all("img"):
        if not t.get("src") or t["src"].startswith("data:"):
            continue
        sc = _img_score(t, inst)
        if sc < 5:
            continue
        src = urljoin(r.url, t["src"])
        if t.get("srcset"):  # 고해상도(2x 등) 버전이 있으면 그걸로
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
            sc -= 4  # 기념일·이벤트용 스페셜 로고는 뒤로
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
    """홈페이지 1곳에서 로고 찾기 → AI 판별 통과한 카드 반환"""
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
    """위키미디어 공용에서 '기관명 로고' 파일 검색 (P154 등록이 없을 때)"""
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
    """위키데이터에 등록된 공식 로고(SVG 등)를 고해상도로 받기"""
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
    """⓪ 위키미디어 공식 로고 → ① 홈페이지(img·CSS·SVG) → ② 위키미디어 검색 → ③ Claude 웹검색(CI 페이지·홈페이지)"""
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
    """새 로고를 저장소에 올리고 커밋 SHA 반환 (이미지 공개 URL용)"""
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
    """반환: (이미지 URL 또는 None, 상태 메시지)"""
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
    # 이미지 처리 완료 대기
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
    """첫 댓글 — 기본은 링크 없는 고정 문구 (계정 안정성)"""
    if COMMENT_LINK == "none":
        return None
    if COMMENT_LINK in ("hiring", "post"):  # 나중에 링크 달고 싶을 때만
        link = post["url"] if (COMMENT_LINK == "post" and post) else HIRING_URL
        lead = f"D-{d_left} 곧 마감 👇" if d_left <= 5 else "지원자격 총정리 👇"
        return f"{lead}\n{link}"
    return COMMENT_TEXT


def summary(md: str):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


# ─────────────────────────── main ───────────────────────────
def main():
    today = dt.datetime.now(KST).date()
    jobs = requests.get(JOBS_URL, timeout=30).json()["result"]
    posts = requests.get(POSTS_URL, timeout=30).json()
    state = load_state()

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
    print(f"조합: {combo}")

    post_text = fetch_post_text(post) if post else ""
    # 최근 훅 + (재발행이면) 같은 공고로 예전에 쓴 훅 전부 → 겹치지 않게
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
          f"조합: {' / '.join(combo[:3])}\n\n로고: {logo_msg}\n\n```\n{result['text']}\n```\n")
    if logo_url:
        md += f'\n<img src="{logo_url}" width="420">\n'
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
        except Exception as e:  # 댓글 실패해도 본문은 이미 발행됨 → 기록은 남김
            print(f"[warn] 첫 댓글 실패 (권한 threads_manage_replies 확인): {e}")
            md += f"\n⚠️ 첫 댓글 실패: {e}\n"

    state["posts"].append({
        "id": job["recrutPblntSn"], "instNm": inst, "title": job["recrutPbancTtl"],
        "combo_idx": combo_idx, "hook": result["hook"], "tier": tier, "logo": bool(logo_url),
        "thread_id": thread_id, "comment_id": comment_id,
        "at": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    })
    save_state(state)
    summary(md)


if __name__ == "__main__":
    main()
