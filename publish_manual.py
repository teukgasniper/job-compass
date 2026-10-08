"""수동 공고 발행 (manual_jobs.json → 카드 + hiring03 본문)  [2026-10-08 신설]
─────────────────────────────────────────────
GitHub Actions '수동 공고 발행' 버튼 전용. 예약 자동발행(publish_to_blogger.py)·본문 보강(enhance_posts.py)은
수동 공고(MN-)를 건드리지 않는다.

하는 일
  1) manual_jobs.json의 살아있는 공고(pbancEndYmd ≥ 오늘)를 jobs.json에 바로 반영 → 카드 즉시 갱신
     (지운 항목·날짜 지난 항목은 카드에서 빠짐. 이미 발행된 글은 지우지 않음)
  2) 본문 글
     - post_url 이 있는 공고 = 내가 직접 쓴 본문 → 발행·수정 안 하고 job_posts.json에 주소만 연결
     - manual_post: true      = 직접 쓸 예정 → 아무것도 안 함 (자동 글 안 씀)
     - 그 외 아직 글이 없는 공고 = Claude(Sonnet)가 본문 작성 → hiring03 발행
  3) 이미 발행된 글은 다시 쓰지 않음 (force 체크 + 공고번호 지정 시에만 Claude 작성 글을 다시 씀,
     직접 쓴 본문(post_url)은 force여도 절대 안 건드림)

본문 재료 (위에서부터 있는 것 사용)
  detail(manual_jobs.json에 붙여넣은 공고 원문) → 토스 채용 API 원문(srcUrl이 toss.im/career/job-detail) →
  srcUrl 페이지 글자 → Claude 웹 검색 → 카드 정보만
  ※ 재료에 없는 담당업무·자격은 지어내지 않고 '원문 공고에서 확인' 안내로 대신함

실행
  python publish_manual.py                    # 새 공고 전부
  python publish_manual.py MN-TOSS-05 --dry-run
  MANUAL_IDS="MN-TOSS-05,MN-TOSS-17" MANUAL_FORCE=true python publish_manual.py
필요한 Secrets: CLAUDE_API_KEY, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID
"""
import json, os, re, sys, time, html as htmllib, urllib.request, urllib.error
from datetime import datetime
from post_template import (KST, AD, HIRING, p, r, cta, h2, table, box, toc, faq, arrow_step,
                           clean_inst, clean_title, hire_list, hire_short, region_text, make_title, make_labels,
                           is_always, end_label, md, md_w, dot, ymd, WEEK, RED, _e)
from publish_to_blogger import access_token, api, slug_for, related_jobs
from enhance_posts import CLAUDE_MODEL, FALLBACK_MODEL, PRICE

MANUAL_FILE, JOBS_FILE, MAPPING_FILE = "manual_jobs.json", "jobs.json", "job_posts.json"
CHANGED_FILE = ".manual_changed.json"   # 이번에 바꾼 공고번호 → save_to_repo.py가 저장소 기록보다 이쪽을 우선
WEB_SEARCH = os.environ.get("MANUAL_WEB_SEARCH", "1") != "0"   # 재료 없을 때 Claude 웹 검색 사용
UA = {"User-Agent": "Mozilla/5.0 (job-compass manual)"}
GENERIC_SRC = ("toss.im/career/jobs",)                          # 목록 페이지 = 재료로 못 씀
CARD_SKIP = ("detail", "post_url", "post_id", "manual_post")      # 카드(jobs.json)에 안 싣는 입력 칸


# ───────── 0. 공통 ─────────
def normalize_inst(name):
    name = re.sub(r'\(주\)|\(재\)|\(사\)|\(학\)', '', name or "")
    name = re.sub(r'[㈜㈔\s]', '', name)
    return re.sub(r'^(재단법인|주식회사)', '', name).strip()


def dedup_key(inst, title):   # fetch_jobs.py와 같은 기준
    t = re.sub(r'[\s\-·~]', '', title or '')
    return f"{normalize_inst(inst)}|{t[:30]}"


def live_manual(today_str):
    doc = json.load(open(MANUAL_FILE, encoding="utf-8"))
    items = doc.get("items", []) if isinstance(doc, dict) else doc
    out = []
    for x in items:
        if (x.get("pbancEndYmd") or "") < today_str:
            continue
        x = dict(x); x["_manual"] = True; x["ongoingYn"] = "Y"
        out.append(x)                                   # detail(원문)은 본문 재료용, 카드에는 안 실음 (sync_cards)
    return out


def sync_cards(data, manual):
    """jobs.json의 수동 공고를 manual_jobs.json 기준으로 교체 (API 공고와 겹치면 API 쪽 유지)"""
    api_jobs = [j for j in data["result"] if not j.get("_manual") and not str(j.get("recrutPblntSn", "")).startswith("MN-")]
    keys = {dedup_key(j.get("instNm"), j.get("recrutPbancTtl")) for j in api_jobs}
    add = [m for m in manual if dedup_key(m.get("instNm"), m.get("recrutPbancTtl")) not in keys]
    data["result"] = api_jobs + [{k: v for k, v in m.items() if k not in CARD_SKIP} for m in add]
    data["count"] = len(data["result"])
    print(f"[카드] 수동 공고 {len(add)}건 반영 (API 공고와 겹쳐서 뺀 것 {len(manual) - len(add)}건)")
    return add


# ───────── 1. 본문 재료 ─────────
def page_text(url):
    if not url or url.rstrip("/").endswith(GENERIC_SRC):
        return ""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as res:
            t = res.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  [재료] 페이지 읽기 실패: {e}")
        return ""
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)   # JS 페이지의 내장 데이터
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
    t = htmllib.unescape(re.sub(r"(?s)<[^>]+>", "\n", t))
    t = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t)).strip()
    if len(t) < 400 and nd:
        t = re.sub(r"\\n|\\u003c[^>]*?\\u003e|<[^>]+>", " ", nd.group(1))
    return t[:20000] if len(t) >= 400 else ""


TOSS_API = "https://api-public.toss.im/api/v3/ipd-eggnog/career/job-groups"   # 토스 채용 페이지가 쓰는 공개 데이터
_toss_cache = None


def toss_jd(url):
    """토스 공고 주소(job-detail?gh_jid=번호 또는 job_id=번호) → 채용 페이지에 보이는 Job Description 원문"""
    global _toss_cache
    m = re.search(r"(?:gh_jid|job_id)=(\d+)", url or "")
    if "toss.im/career" not in (url or "") or not m:
        return ""
    if _toss_cache is None:
        _toss_cache = {}
        try:
            with urllib.request.urlopen(urllib.request.Request(TOSS_API, headers=UA), timeout=60) as res:
                groups = json.loads(res.read()).get("success") or []
            for g in groups:
                for x in g.get("jobs") or [g.get("primary_job") or {}]:
                    jd = next((mt.get("value") for mt in x.get("metadata") or []
                               if str(mt.get("name", "")).startswith("Job Description")), "") or ""
                    _toss_cache[str(x.get("id"))] = f"# {x.get('title', '')}\n{jd}"
            print(f"  [재료] 토스 채용 데이터 {len(_toss_cache)}건 읽음")
        except Exception as e:
            print(f"  [재료] 토스 채용 데이터 읽기 실패: {e}")
    t = _toss_cache.get(m.group(1), "")
    t = re.sub(r"!\[[^\]]*\]\s*\([^)]*\)", "", t)          # 이미지 마크다운 제거
    return t.strip()[:20000] if len(t) >= 300 else ""


def get_material(job):
    if (job.get("detail") or "").strip():
        return job["detail"].strip()[:20000], "직접 붙여넣은 공고 원문"
    t = toss_jd(job.get("srcUrl", ""))
    if t:
        return t, f"토스 채용 페이지 원문 ({job['srcUrl']})"
    t = page_text(job.get("srcUrl", ""))
    if t:
        return t, f"원문 페이지 ({job['srcUrl']})"
    return "", ""


# ───────── 2. Claude 본문 작성 ─────────
SYSTEM = """너는 취업 정보 블로그 hiring03의 편집자야. 민간 기업 채용 공고 1건의 상세 글 내용을 JSON으로 쓴다.
규칙
- 사실만 쓴다. 담당업무·자격요건·우대사항·전형절차는 <재료>(또는 웹 검색으로 찾은 '이 공고'의 원문)에 있는 것만. 없으면 빈 배열.
- 연봉·인원·날짜·숫자는 재료에 있을 때만. 추측·일반론을 이 공고의 사실처럼 쓰지 않는다.
- 회사 소개는 누구나 아는 사실만 1~2문장 (숫자·순위·매출 금지).
- 공공기관 표현 금지: 공기업, 정년 보장, 블라인드, NCS, 필기시험.
- 말투: 해요체, 짧고 쉽게. 전문 용어는 풀어서 한 번만. 과장·감탄 금지.
- 출력은 JSON 하나만. 설명·마크다운 금지."""

SCHEMA = """아래 형식으로 출력해. 모르는 항목은 빈 문자열 또는 [].
{
 "summary": "인트로 2문장. 어떤 회사의 어떤 직무 채용인지 + 누구에게 맞는 자리인지",
 "company": "회사 소개 1~2문장",
 "role_intro": "이 직무가 하는 일 1~2문장 (재료 기준)",
 "tasks": ["담당 업무 한 줄씩, 최대 6개"],
 "required": ["자격 요건 한 줄씩, 최대 6개"],
 "preferred": ["우대 사항 한 줄씩, 최대 5개"],
 "process": ["전형 단계 이름 순서대로, 예: 서류 접수", "직무 인터뷰"],
 "process_note": "전형 관련 참고 1문장 (재료에 있을 때만)",
 "tips": [{"title": "합격 포인트 제목 (12자 이내)", "text": "1~2문장. 이 직무 기준의 실전 준비법"}],
 "faqs": [{"q": "질문", "a": "답 1~2문장"}],
 "sources": ["참고한 원문 주소 (있으면)"]
}
- tips는 2~3개. 재료 기준 직무에 맞춘 준비법 (일반적인 조언이면 '보통'처럼 일반론임을 드러내기)
- faqs는 정확히 4개: 신입 지원 가능 여부 / 학력 조건 / 담당 업무나 근무지 관련 / 지원 방법. 마감일 질문은 넣지 말 것 (코드가 넣음)"""


def call_claude(user, model=CLAUDE_MODEL, tools=True):
    body = {"model": model, "max_tokens": 4000, "system": SYSTEM, "messages": [{"role": "user", "content": user}]}
    if tools:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
    msgs = body["messages"]
    for _ in range(4):                                       # 웹 검색이 길면 pause_turn → 이어서 요청
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                     method="POST", headers={"x-api-key": os.environ["CLAUDE_API_KEY"],
                                                             "anthropic-version": "2023-06-01",
                                                             "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as res:
                d = json.loads(res.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code == 404 and model != FALLBACK_MODEL:
                print(f"  [warn] 모델 {model} 없음 → {FALLBACK_MODEL}")
                return call_claude(user, FALLBACK_MODEL, tools)
            if e.code == 400 and tools:
                print(f"  [warn] 웹 검색 사용 불가 → 검색 없이 작성 ({msg[:120]})")
                return call_claude(user, model, False)
            raise RuntimeError(f"Claude API {e.code}: {msg}")
        u = d.get("usage", {})
        pin, pout = PRICE.get(d.get("model", model), PRICE["default"])
        n_search = (u.get("server_tool_use") or {}).get("web_search_requests", 0)
        cost = u.get("input_tokens", 0) * pin / 1e6 + u.get("output_tokens", 0) * pout / 1e6 + n_search * 0.01
        print(f"  [Claude] 입력 {u.get('input_tokens', 0):,} / 출력 {u.get('output_tokens', 0):,} 토큰"
              + (f" / 검색 {n_search}회" if n_search else "") + f" (약 ${cost:.3f})")
        if d.get("stop_reason") == "pause_turn":
            msgs.append({"role": "assistant", "content": d["content"]})
            continue
        texts = [b.get("text", "") for b in d["content"] if b.get("type") == "text"]
        return "".join(texts)                               # 웹 검색 인용이 있으면 글이 여러 조각으로 옴
    raise RuntimeError("Claude 응답이 끝나지 않음")


def write_content(job, material, src_name):
    card = {
        "회사": clean_inst(job["instNm"]), "공고명": job["recrutPbancTtl"], "고용형태": job.get("hireTypeNmLst"),
        "경력": job.get("recrutSeNm"), "학력": job.get("acbgCondNmLst"), "근무지": job.get("workRgnNmLst"),
        "모집분야": job.get("ncsCdNmLst"), "마감": end_label(job) if is_always(job) else md(job["pbancEndYmd"]),
        "원문 공고": job.get("srcUrl"),
    }
    head = "[카드 정보 — 이미 확인된 사실]\n" + "\n".join(f"- {k}: {v}" for k, v in card.items() if v) + "\n\n" + SCHEMA
    if material:
        user = head + f"\n\n<재료 출처: {src_name}>\n{material}\n</재료>"
        use_tools = False
    else:
        user = (head + "\n\n재료가 없어. 웹 검색으로 '이 회사의 이 공고' 원문(회사 채용 페이지·사람인·잡코리아 등)을 찾아서 "
                "담당업무·자격요건·우대사항·전형절차를 확인해. 다른 회사나 다른 직무 공고 내용은 쓰지 마. "
                "못 찾으면 해당 항목은 빈 배열로 두고 sources도 비워.")
        use_tools = WEB_SEARCH
    raw = call_claude(user, tools=use_tools)
    m = re.search(r"\{.*\}", re.sub(r"```(json)?", "", raw), re.S)
    if not m:
        raise ValueError("JSON 없음")
    c = json.loads(m.group(0))
    for k in ("tasks", "required", "preferred", "process", "tips", "faqs", "sources"):
        c[k] = [x for x in (c.get(k) or []) if x][:8]
    for k in ("summary", "company", "role_intro", "process_note"):
        c[k] = str(c.get(k) or "").strip()
    bad = re.compile(r"공기업|정년\s*보장|블라인드|NCS|필기시험")
    for k in ("summary", "company", "role_intro", "process_note"):
        if bad.search(c[k]):
            c[k] = ""
    return c


# ───────── 3. HTML ─────────
def ul(items):
    lis = "".join(f'<li style="margin:0 0 8px; line-height:1.65;">{_e(x)}</li>' for x in items)
    return f'<ul style="font-size:17px; color:#333; padding-left:22px; margin:0 0 18px; word-break:keep-all;">{lis}</ul>'


def build_manual_html(job, src, c, related=None):
    inst, title = clean_inst(job["instNm"]), clean_title(job["recrutPbancTtl"])
    hs, hl = hire_short(job), hire_list(job)
    se = job.get("recrutSeNm") or ""
    acbg = (job.get("acbgCondNmLst") or "").replace(",", ", ")
    always, end, bg = is_always(job), job["pbancEndYmd"], job["pbancBgngYmd"]
    end_txt = end_label(job) if always else f"{md(end)} 마감"
    newbie = "신입" in se
    toc_items = [f"채용 개요: {inst} {title}", "담당 업무: 입사하면 하는 일", f"지원 자격: {acbg.split(', ')[0] or '자격 요건'} · {se or '경력 구분'}",
                 f"접수 일정: {end_txt}", "전형 절차", "합격 포인트: 이 직무 준비법", "함께 보면 좋은 공고: 전국 채용 더 보기"]
    tag = 'display:inline-block; background:#DBEAFE; color:#1E40AF; font-size:14px; font-weight:600; padding:6px 14px; border-radius:20px;'
    tag_dl = 'display:inline-block; background:#FEF3C7; color:#92400E; font-size:14px; font-weight:600; padding:6px 14px; border-radius:20px;'
    tags = (f'<span style="{tag}">✅ {_e(hs)}</span>' + (f' <span style="{tag}">✅ {_e(acbg.split(", ")[0])}</span>' if acbg else "")
            + (f' <span style="{tag}">✅ 신입 지원 가능</span>' if newbie else "")
            + f' <span style="{tag_dl}">⏰ {_e(end_txt)}</span>')
    intro = ('<div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:14px; padding:22px 20px; margin:10px 0 16px;">'
             f'<p style="font-size:20px; font-weight:bold; color:#1E3A8A; margin:0 0 12px; line-height:1.45; word-break:keep-all;">{_e(inst)} {_e(title)} 채용</p>'
             f'<p style="font-size:17px; color:#1e293b; margin:0; line-height:1.6; word-break:keep-all;">{_e(c["summary"] or f"{inst}이(가) {title} 포지션을 채용하고 있어요.")}</p></div>'
             f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px;">{tags}</div>')
    check = "원문 공고에서 확인하세요"

    s1 = (h2(1, toc_items[0])
          + (p(_e(c["company"])) if c["company"] else "")
          + table(["항목", "내용"], [["기업", _e(inst)], ["포지션", _e(title)], ["고용형태", _e(", ".join(hl))],
                                     ["경력구분", _e(se)], ["학력", _e(acbg) or check], ["모집분야", _e(job.get("ncsCdNmLst") or "")],
                                     ["근무지역", _e(region_text(job))], ["접수 마감", r(_e(end_txt))]], ["30%", "70%"])
          + p("같은 회사라도 포지션마다 요구 경험과 근무지가 달라요. 내가 지원할 포지션이 맞는지 원문에서 먼저 확인하세요.")
          + cta("포지션 상세 보기", src))
    s2 = (h2(2, toc_items[1])
          + (p(_e(c["role_intro"])) if c["role_intro"] else "")
          + (ul(c["tasks"]) if c["tasks"] else box("blue", "📌 담당 업무", f"세부 업무 내용은 기업 채용 페이지의 원문 공고에 정리돼 있어요. 지원 전에 {check}."))
          + p("업무 설명에 나온 단어를 자기소개서와 이력서에 그대로 연결하면 서류에서 훨씬 잘 읽혀요.")
          + cta("담당 업무 확인하기", src))
    s3 = (h2(3, toc_items[2])
          + p(f"카드 기준 학력 조건은 「{_e(acbg) or '공고 참조'}」, 경력 구분은 「{_e(se)}」이에요.")
          + ((p("<b>자격 요건</b>") + ul(c["required"])) if c["required"] else "")
          + ((p("<b>우대 사항</b>") + ul(c["preferred"])) if c["preferred"] else "")
          + (box("blue", "📌 핵심 포인트", "학력보다 실무 경험과 직무 이해도를 보는 포지션이에요. 관련 경험을 구체적인 결과 중심으로 정리해두세요.")
             if "무관" in acbg else box("blue", "📌 핵심 포인트", f"세부 자격 요건은 포지션마다 달라요. {check}."))
          + cta("지원 자격 보기", src))
    if always:
        sched = (p(f"이 공고는 {r(_e(end_label(job)))}이에요. 정해진 마감일 없이 접수를 받다가 채용이 끝나면 예고 없이 닫힐 수 있어요.")
                 + table(["구분", "일정"], [["접수", "접수 중"], ["접수 마감", r(_e(end_label(job)))]], ["35%", "65%"])
                 + box("red", "⚠️ 주의하세요", "상시채용은 적합한 지원자가 모이면 바로 닫히는 경우가 많아요. 미루지 말고 준비되는 대로 제출하세요."))
    else:
        sched = (p(f"접수 마감은 {r(md_w(end))}이에요.")
                 + table(["구분", "일정"], [["접수 마감", r(dot(end) + f"({WEEK[ymd(end).weekday()]})")],
                                           ["남은 기간", f'<span class="jm-dday" data-end="{end[:4]}-{end[4:6]}-{end[6:]}T23:59:59+09:00" {RED}>{md(end)} 마감</span>']], ["35%", "65%"])
                 + box("red", "⚠️ 주의하세요", "마감 시각은 회사마다 달라요. 마감 당일이 아니라 하루 전 제출을 목표로 하세요."))
    s4 = h2(4, toc_items[3]) + sched + cta("접수창 열기", src)
    if c["process"]:
        steps = '<div style="max-width:400px; margin:20px auto;">' + "".join(
            arrow_step(f"{i + 1}단계 — {_e(n)}" if i < len(c["process"]) - 1 else _e(n), "", i == len(c["process"]) - 1)
            for i, n in enumerate(c["process"])) + "</div>"
        s5_body = p("원문 공고에 적힌 전형 순서예요.") + steps + (box("green", "💡 알아두세요", _e(c["process_note"])) if c["process_note"] else "")
    else:
        s5_body = (p("기업 채용은 보통 서류, 직무 인터뷰, 문화 적합성 인터뷰 순서로 진행되고 포지션에 따라 과제나 테스트가 붙기도 해요.")
                   + box("green", "💡 알아두세요", f"위 흐름은 일반적인 순서예요. 이 포지션의 실제 전형은 {check}."))
    s5 = h2(5, toc_items[4]) + s5_body + cta("전형 절차 확인하기", src)
    tips = c["tips"] or [{"title": "경험을 숫자로", "text": "어떤 문제를 어떻게 풀었고 결과가 어땠는지 숫자로 정리하면 서류와 인터뷰 모두에서 설득력이 생겨요."}]
    s6 = (h2(6, toc_items[5])
          + "".join(box("blue", f"✔ {_e(t.get('title', ''))}", _e(t.get("text", ""))) for t in tips if isinstance(t, dict))
          + cta("지금 지원하러 가기", src))
    rel_rows = [[clean_inst(j["instNm"]), hire_short(j), "상시" if is_always(j) else dot(j["pbancEndYmd"])[5:]] for j in (related or [])[:3]]
    s7 = (h2(7, toc_items[6])
          + p(f"같은 {job.get('bizType') or '기업'} 채용에서 지금 접수 중인 공고도 함께 보세요.")
          + (table(["기업", "고용형태", "마감"], rel_rows, ["45%", "30%", "25%"]) if rel_rows else "")
          + p("전국에서 접수 중인 공고를 마감임박순으로 모아두었어요. 지역별로 걸러서 내 조건에 맞는 공고를 찾아보세요.")
          + cta("전국 공고 더 보기", HIRING))

    dl_faq = ((f"언제까지 접수할 수 있나요?", f"이 공고는 {r(_e(end_label(job)))}이라 정해진 마감일이 없어요. 채용이 끝나면 예고 없이 닫힐 수 있으니 준비되는 대로 지원하세요.")
              if always else ("마감 당일 몇 시까지 접수되나요?", f"마감일은 {r(md_w(end))}이에요. 마감 시각은 회사마다 달라서 원문 공고에서 꼭 확인하고, 하루 전 제출을 권해요."))
    faqs = [dl_faq] + [(_e(f.get("q", "")), _e(f.get("a", ""))) for f in c["faqs"] if isinstance(f, dict) and f.get("q")][:4]

    secs = [s1, s2, s3, s4, s5, s6, s7]
    body = (AD + toc(toc_items) + intro + AD + cta("채용공고 바로가기", src)   # 광고 - 목차 - 후킹박스 - 광고 - 버튼
            + "".join(sec if i == 0 else AD + sec for i, sec in enumerate(secs))
            + AD
            + '<h2 style="background:#F0F7FF; border-left:5px solid #3B82F6; border-radius:0 10px 10px 0; color:#1e293b; font-size:22px; font-weight:bold; margin:40px 0 18px; padding:14px 18px;">자주 묻는 질문</h2>'
            + faq(faqs)
            + p(f"이번 {_e(inst)} {_e(title)} 공고는 {r(_e(end_label(job)) if always else md_w(end) + ' 마감')}이에요. 관심 있다면 원문부터 열어두세요.")
            + cta("지금 바로 지원하기", src)
            + AD
            + '<div style="background:#F3F4F6; border-radius:10px; padding:16px 18px; margin:30px 0 10px; font-size:14px; color:#6B7280; line-height:1.65; word-break:keep-all;">'
              '본 글은 기업 채용 공고를 바탕으로 작성되었어요. 모집 분야, 자격 요건, 일정은 기업 사정에 따라 바뀔 수 있으니 지원 전 반드시 원문 공고를 확인하세요. '
              '본 페이지는 채용 기업과 관계가 없는 정보 안내 페이지예요.</div>'
            + ('' if always else '<script>(function(){var e=document.querySelectorAll(".jm-dday");for(var i=0;i<e.length;i++){var d=Math.ceil((new Date(e[i].getAttribute("data-end"))-new Date())/86400000)-1;e[i].textContent=d>0?("D-"+d+" (마감까지 "+d+"일)"):(d===0?"D-DAY (오늘 마감)":"접수 마감");}})();</script>'))
    return body


# ───────── 4. 실행 ─────────
def publish_one(job, sn, cur, jobs, now, dry, state):
    """글 1개 작성·발행. 반환: 발행(또는 미리보기)했으면 1, 아니면 0"""
    material, src_name = get_material(job)
    print(f"  재료: {src_name or ('없음 → 웹 검색' if WEB_SEARCH else '없음 → 카드 정보만')}" + (f" ({len(material):,}자)" if material else ""))
    c = write_content(job, material, src_name)
    print(f"  작성: 업무 {len(c['tasks'])} / 자격 {len(c['required'])} / 우대 {len(c['preferred'])} / 전형 {len(c['process'])}"
          + (f" / 출처 {c['sources'][0]}" if c["sources"] else ""))
    src = job.get("srcUrl") or HIRING
    page = build_manual_html(job, src, c, related_jobs(job, jobs, now))
    if dry:
        os.makedirs("preview", exist_ok=True)
        open(f"preview/{slug_for(job)}.html", "w", encoding="utf-8").write(page)
        json.dump(c, open(f"preview/{slug_for(job)}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  [미리보기] preview/{slug_for(job)}.html | {make_title(job)}")
        return 1
    if state["token"] is None:
        state["token"] = access_token()
    token = state["token"]
    if cur.get("postId"):                                       # force: Claude 작성 글 다시 쓰기 (같은 주소)
        if not api("PATCH", f"posts/{cur['postId']}", token, {"content": page}):
            print("  실패: Blogger 수정 오류"); return 0
        state["mapping"][sn] = dict(cur, rewritten=now.strftime("%Y-%m-%d %H:%M"))
        state["changed"].add(sn)
        print(f"  ✅ 다시 작성 → {cur.get('url', '')}")
        return 1
    slug = slug_for(job)
    post = api("POST", "posts?isDraft=false", token,
               {"kind": "blogger#post", "title": slug.replace("-", " "), "content": page, "labels": make_labels(job)})
    if not post or not post.get("id"):
        print("  실패: Blogger 발행 오류"); return 0
    title = make_title(job)
    state["mapping"][sn] = {"postId": post["id"], "url": post.get("url", ""), "title": slug.replace("-", " "),
                            "instNm": job["instNm"], "slug": slug, "published": now.strftime("%Y-%m-%d %H:%M"), "manual": "claude"}
    state["changed"].add(sn)
    state["save"]()                                             # 발행 직후 바로 기록 (아래 제목 수정이 실패해도 중복 발행 방지)
    if api("PATCH", f"posts/{post['id']}", token, {"title": title}):
        state["mapping"][sn]["title"] = title
    print(f"  ✅ 발행 → {post.get('url', '')}")
    time.sleep(3)
    return 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ids = set(args or [x.strip() for x in re.split(r"[,\s]+", os.environ.get("MANUAL_IDS", "")) if x.strip()])
    dry = "--dry-run" in sys.argv or os.environ.get("MANUAL_DRY_RUN") == "true"
    force = "--force" in sys.argv or os.environ.get("MANUAL_FORCE") == "true"
    now = datetime.now(KST)

    data = json.load(open(JOBS_FILE, encoding="utf-8"))
    manual = sync_cards(data, live_manual(now.strftime("%Y%m%d")))
    if not dry:
        json.dump(data, open(JOBS_FILE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    jobs = data["result"]
    mapping = json.load(open(MAPPING_FILE, encoding="utf-8")) if os.path.exists(MAPPING_FILE) else {}
    state = {"token": None, "mapping": mapping, "changed": set()}

    def save():
        if dry:
            return
        json.dump(mapping, open(MAPPING_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(sorted(state["changed"]), open(CHANGED_FILE, "w", encoding="utf-8"))
    state["save"] = save

    done = 0
    try:
        for job in manual:
            sn = str(job["recrutPblntSn"])
            if ids and sn not in ids:
                continue
            cur = mapping.get(sn) or {}
            # ① 직접 쓴 본문 → 주소만 연결 (postId는 직접 준 값만 — 예전 Claude 글 번호를 남기지 않음)
            if job.get("post_url"):
                if cur.get("url") != job["post_url"] or cur.get("manual") != "user":
                    mapping[sn] = {"postId": job.get("post_id") or "", "url": job["post_url"],
                                   "title": make_title(job), "instNm": job["instNm"], "slug": "",
                                   "published": cur.get("published") or now.strftime("%Y-%m-%d %H:%M"), "manual": "user"}
                    state["changed"].add(sn); save()
                    print(f"[연결] {sn} 직접 쓴 본문 → {job['post_url']}")
                continue
            if job.get("manual_post"):
                print(f"[건너뜀] {sn} 직접 쓸 예정 (manual_post)"); continue
            if cur.get("manual") == "user":
                print(f"[건너뜀] {sn} 직접 쓴 본문이 연결돼 있어요"); continue
            if cur and not (force and ids):
                continue                                           # 이미 발행됨
            if cur and cur.get("manual") != "claude":
                print(f"[건너뜀] {sn} Claude가 쓴 글이 아니라 다시 쓰지 않아요"); continue
            print(f"\n[{sn}] {clean_inst(job['instNm'])} / {job['recrutPbancTtl']}")
            try:
                done += publish_one(job, sn, cur, jobs, now, dry, state)
            except RuntimeError as e:
                if "발행 한도" in str(e):
                    raise                                          # Blogger 한도·권한 문제 → 전체 중단
                print(f"  실패: {str(e)[:200]}")
            except Exception as e:
                print(f"  실패: {type(e).__name__}: {str(e)[:200]}")   # 이 공고만 건너뛰고 계속
    except RuntimeError as e:
        print(f"[중단] {e}")
    finally:
        save()
        print(f"\n[완료] 이번 {done}개 {'미리보기' if dry else '발행'}")


if __name__ == "__main__":
    main()
