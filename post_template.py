"""채용공고 1건 → 상세 글 HTML (지침서 2번 페이지 / 거미줄 v3.6 규격)
원칙: 과장은 OK, 거짓은 NO — 데이터에 없는 사실(연봉·전형 확정·어학 기준)은 쓰지 않는다.
v2: 인트로 후킹 강화 / 섹션4 보수 수준 교체 / 인트로CTA-H2#1 광고 제거 / 정년보장 분기 / 결론 강화"""
from datetime import datetime, timezone, timedelta
import re, json, os

# 연봉 데이터 로딩
_SALARY_PATH = os.path.join(os.path.dirname(__file__), "salary_data.json")
try:
    with open(_SALARY_PATH, encoding="utf-8") as _f:
        SALARY_DB = json.load(_f)
except Exception:
    SALARY_DB = {}

def _find_salary(inst_name):
    """기관명으로 연봉 데이터 찾기 (부분 일치)"""
    clean = re.sub(r"\(주\)|\(재\)|\(사\)|주식회사", "", inst_name).strip()
    if clean in SALARY_DB:
        return SALARY_DB[clean]
    for k, v in SALARY_DB.items():
        if k.startswith("_"):
            continue
        if clean in k or k in clean:
            return v
    return None

KST = timezone(timedelta(hours=9))
AD_CLIENT = "ca-pub-1043776171226680"
AD_SLOT = "5492035216"
HIRING = "https://hiring.ddolbestory.com"

AD = ('<div style="margin:28px 0;">'
      '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1043776171226680"'
      ' crossorigin="anonymous"></script>'
      '<ins class="adsbygoogle"'
      ' style="display:block"'
      f' data-ad-client="{AD_CLIENT}"'
      f' data-ad-slot="{AD_SLOT}"'
      ' data-ad-format="auto"'
      ' data-full-width-responsive="true"></ins>'
      '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
      '</div>')

RED = 'style="color:#EF4444; font-weight:bold;"'
P = 'style="font-size:18px; line-height:1.7; word-break:keep-all; margin:0 0 16px; color:#333;"'

# ───────── 공통 부품 ─────────
def p(t): return f'<p {P}>{t}</p>'
def r(t): return f'<span {RED}>{t}</span>'

def cta(label, href):
    return ('<div style="max-width:360px; width:92%; margin:25px auto;">'
            f'<a href="{href}" style="display:block; width:100%; box-sizing:border-box; '
            'background:linear-gradient(135deg,#DC2626,#B91C1C); color:#fff; padding:20px 18px; '
            'border-radius:14px; font-weight:bold; font-size:24px; text-decoration:none; white-space:nowrap; '
            f'text-align:center; box-shadow:0 4px 12px rgba(220,38,38,0.35);">👉 {label}</a></div>')

def h2(i, t):
    idattr = f' id="sec{i}"' if i else ''
    return (f'<h2{idattr} style="background:#F0F7FF; border-left:5px solid #3B82F6; border-radius:0 10px 10px 0; '
            'color:#1e293b; font-size:22px; font-weight:bold; margin:40px 0 18px; padding:14px 18px; line-height:1.45;">'
            f'{t}</h2>')

def table(head, rows, widths):
    th = ''.join(f'<th style="background:#F1F5F9; color:#1e293b; padding:12px 10px; border:1px solid #E2E8F0; '
                 f'font-size:15px; text-align:center; width:{w};">{h}</th>' for h, w in zip(head, widths))
    trs = ''.join('<tr>' + ''.join(
        '<td style="padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; line-height:1.55; '
        f'word-break:keep-all; vertical-align:middle;">{c}</td>' for c in row) + '</tr>' for row in rows)
    return ('<div style="overflow-x:auto; margin:18px 0 22px;"><table style="width:100%; border-collapse:collapse; '
            f'table-layout:fixed; background:#fff;"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')

def box(kind, title, body):
    bg, bd = {"blue": ("#EFF6FF", "#3B82F6"), "red": ("#FEF2F2", "#EF4444"), "green": ("#F0FDF4", "#22C55E")}[kind]
    return (f'<div style="background:{bg}; border-left:5px solid {bd}; border-radius:0 10px 10px 0; padding:16px 18px; margin:20px 0;">'
            f'<p style="font-size:17px; font-weight:bold; margin:0 0 8px; color:#1e293b;">{title}</p>'
            f'<p style="font-size:16px; line-height:1.65; margin:0; color:#374151; word-break:keep-all;">{body}</p></div>')

def toc(items):
    lis = ''
    for i, t in enumerate(items, 1):
        sep = '' if i == len(items) else ' border-bottom:1px dashed #D1D5DB;'
        lis += (f'<li style="display:flex; align-items:center; gap:12px; padding:12px 4px;{sep}">'
                '<span style="flex:0 0 30px; width:30px; height:30px; border-radius:50%; background:#1E3A8A; color:#fff; '
                f'font-size:14px; font-weight:bold; display:flex; align-items:center; justify-content:center;">{i}</span>'
                f'<a href="#sec{i}" style="font-size:17px; color:#374151; text-decoration:none; line-height:1.45; word-break:keep-all;">{t}</a></li>')
    return ('<div style="border:1px solid #E5E7EB; border-radius:14px; overflow:hidden; margin:10px 0 20px;">'
            '<div style="background:linear-gradient(90deg,#7C3AED,#EC4899); color:#fff; font-size:18px; font-weight:bold; padding:14px 18px;">목차</div>'
            f'<ul style="list-style:none; margin:0; padding:6px 16px 8px;">{lis}</ul></div>')

def faq(items):
    out = ''
    for i, (q, a) in enumerate(items, 1):
        out += ('<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; padding:20px; margin:0 0 14px;">'
                f'<p style="font-size:17px; font-weight:bold; color:#1e293b; margin:0 0 8px; line-height:1.5;">Q{i}. {q}</p>'
                f'<p style="font-size:16px; color:#374151; margin:0; line-height:1.65; word-break:keep-all;">{a}</p></div>')
    return out

# ───────── 데이터 가공 ─────────
def ymd(d): return datetime.strptime(d, "%Y%m%d").replace(tzinfo=KST)
def dot(d): return f"{d[:4]}.{d[4:6]}.{d[6:]}"
def md(d): return f"{int(d[4:6])}월 {int(d[6:])}일"
WEEK = "월화수목금토일"
def md_w(d): return f"{md(d)}({WEEK[ymd(d).weekday()]})"

def days_left(job, now=None):
    now = now or datetime.now(KST)
    return (ymd(job["pbancEndYmd"]).date() - now.date()).days

def clean_inst(n): return re.sub(r"\(주\)|\(재\)|\(사\)|주식회사", "", n or "").strip()

def clean_title(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t

def hire_list(job): return [h.strip() for h in (job.get("hireTypeNmLst") or "").split(",") if h.strip()]
def ncs_list(job): return [h.strip() for h in (job.get("ncsCdNmLst") or "").split(",") if h.strip()]
def regions(job): return [h.strip() for h in (job.get("workRgnNmLst") or "").split(",") if h.strip()]

def region_text(job):
    rg = regions(job)
    if len(rg) >= 10:
        extra = " + 해외" if "해외" in rg else ""
        return f"전국 {len([x for x in rg if x != '해외'])}개 시·도{extra}"
    return ", ".join(rg) or "공고 참조"

def nope_text(job):
    n = job.get("recrutNope") or 0
    return f"{n}명" if n > 0 else "공고 참조"

def hire_short(job):
    hl = hire_list(job)
    if not hl: return "채용"
    return hl[0] if len(hl) == 1 else f"{hl[0]} 외"

def ncs_text(job):
    return ", ".join(x.replace(".", "·") for x in ncs_list(job)) or "공고 참조"

# ───────── 고정 문단 (사실만) ─────────
NCS_TIPS = {
    "보건·의료": "간호사·임상병리사처럼 면허가 있어야 지원할 수 있는 직종이 많아요. 지원 전에 면허와 자격증 요건부터 확인하세요.",
    "경영·회계·사무": "사무 직무는 NCS 직업기초능력(의사소통, 수리, 문제해결 등)을 보는 필기가 붙는 경우가 많아요. 기출 유형을 미리 풀어두면 유리해요.",
    "정보통신": "정보처리기사 같은 관련 자격증을 우대하거나 가점을 주는 기관이 많아요. 보유 자격증을 먼저 정리해두세요.",
    "전기·전자": "전기기사 등 관련 기사 자격증을 지원 자격이나 가점으로 두는 경우가 많아요. 자격 요건 칸을 꼭 확인하세요.",
    "기계": "일반기계기사 등 관련 자격증이 가점 대상인 경우가 많아요. 전공 필기가 있는지도 함께 확인하세요.",
    "건설": "토목·건축 관련 기사 자격증을 요구하거나 우대하는 경우가 많아요. 현장 근무 여부도 확인하세요.",
    "연구": "연구직은 석사·박사 학위와 연구 실적을 따로 평가하는 경우가 많아요. 제출 서류 목록을 미리 챙기세요.",
    "사업관리": "사업관리 직무는 기획서·보고서 작성 역량을 묻는 경우가 많아요. 관련 경험을 수치로 정리해두면 좋아요.",
    "환경·에너지·안전": "안전·환경 분야는 산업안전기사 등 자격증을 요건이나 가점으로 두는 경우가 많아요.",
    "경비·청소": "현장 직무는 서류와 면접 위주로 선발하는 경우가 많아요. 근무 시간과 교대 여부를 꼭 확인하세요.",
    "운전·운송": "운전 직무는 운전면허 종류와 경력 요건이 핵심이에요. 필요한 면허 등급을 먼저 확인하세요.",
    "사회복지·종교": "사회복지사 자격증을 요건으로 두는 경우가 많아요. 자격 등급 조건을 확인하세요.",
}
DEFAULT_TIP = "직무기술서에 적힌 필요 지식과 기술을 내 경험과 하나씩 연결해보면 자기소개서 방향이 잡혀요."

# ───────── 메타정보 ─────────
def make_title(job):
    inst = clean_inst(job["instNm"])
    t = clean_title(job["recrutPbancTtl"])
    base = t if inst in t else f"{inst} {t}"
    return f"{base} | {hire_short(job)} {nope_text(job)}, {md(job['pbancEndYmd'])} 마감"

def make_labels(job):
    labels = ["채용정보", clean_inst(job["instNm"])]
    labels += [h for h in hire_list(job)][:2]
    rg = regions(job)
    labels.append("전국" if len(rg) >= 10 else (rg[0] if rg else ""))
    nl = ncs_list(job)
    if nl: labels.append(nl[0].replace(".", ""))
    seen, out = set(), []
    for l in labels:
        if l and l not in seen:
            seen.add(l); out.append(l)
    return out[:6]

# ───────── 본문 ─────────
def build_html(job, src, related=None):
    inst = clean_inst(job["instNm"])
    title = clean_title(job["recrutPbancTtl"])
    hl = hire_list(job)
    hs = hire_short(job)
    end, bg = job["pbancEndYmd"], job["pbancBgngYmd"]
    se = job.get("recrutSeNm") or "공고 참조"
    acbg = (job.get("acbgCondNmLst") or "공고 참조").replace(",", ", ")
    repl = job.get("replmprYn") == "Y"
    nl = [x.replace(".", "·") for x in ncs_list(job)]
    ncs_main = nl[0] if nl else ""
    nope = job.get("recrutNope") or 0

    # ★ 정년보장 분기
    if any(h in ("정규직", "무기계약직") for h in hl):
        tenure = "정년 보장 "
    elif any("채용형" in h for h in hl):
        tenure = "정규직 전환 "
    else:
        tenure = ""

    toc_items = [
        f"채용 개요: {inst} {hs} {nope_text(job)} 모집",
        f"접수 일정: {md(end)} 마감",
        f"지원 자격: {acbg.split(', ')[0]} · {se}",
        "이 기관의 보수 수준: 초봉부터 평균연봉까지",
        "전형 절차: 공공기관 채용 흐름 한눈에 보기",
        f"선배들이 말하는 합격 포인트: {ncs_main or '공공기관'} 직무 준비법",
        "함께 보면 좋은 공고: 전국 채용 더 보기",
    ]

    # ★ 인트로 — 긴급형 후킹
    headline = f"{tenure}{hs} {r(str(nope) + '명')}" if nope > 0 else f"{tenure}{hs}"
    acbg_hook = "학력 안 보고, " if "학력무관" in acbg else ""
    region_hook = "전국 배치에, " if len(regions(job)) >= 10 else ""
    intro = (p(f"{acbg_hook}{region_hook}{headline} — 이 조건이 동시에 되는 공기업 공채가 떴어요.")
             + p(f"접수는 {r(md_w(end))}에 닫혀요. 이번 공고 놓치면 다음 공채까지 최소 6개월이에요.")
             + p("지원 자격부터 빠르게 확인해보세요."))

    # H2 1 개요
    s1 = (h2(1, toc_items[0])
          + p(f"이번 공고는 {inst}의 「{title}」이에요. 핵심 정보를 표로 정리했어요.")
          + table(["항목", "내용"], [
              ["기관", inst], ["공고명", title], ["고용형태", ", ".join(hl) or "공고 참조"],
              ["모집인원", r(nope_text(job)) if nope else nope_text(job)], ["경력구분", se],
              ["직무분야", ncs_text(job)], ["근무지역", region_text(job)],
              ["대체인력 여부", "대체인력 채용" if repl else "해당 없음"]], ["30%", "70%"])
          + p("그런데 가장 중요한 건 모집 분야별 세부 인원이에요. 분야마다 뽑는 인원과 근무지가 나뉘어 있어서, 내가 지원할 분야를 먼저 골라야 해요.")
          + p("생각보다 선택지가 많아서 놀라시는 분이 많아요. 모집 분야부터 확인해보세요.")
          + cta("모집 분야 보기", src))

    # H2 2 일정
    total = (ymd(end) - ymd(bg)).days
    s2 = (h2(2, toc_items[1])
          + p(f"접수는 {md(bg)}에 시작해서 {md_w(end)}에 끝나요. 전체 접수 기간은 {total}일이에요.")
          + table(["구분", "일정"], [
              ["접수 시작", dot(bg)], ["접수 마감", r(dot(end) + f"({WEEK[ymd(end).weekday()]})")],
              ["남은 기간", f'<span class="jm-dday" data-end="{end[:4]}-{end[4:6]}-{end[6:]}T23:59:59+09:00" {RED}>{md(end)} 마감</span>']],
              ["35%", "65%"])
          + box("red", "⚠️ 주의하세요", "마감 시각은 기관마다 달라요. 오후 6시에 닫는 곳도 많으니 마감 당일이 아니라 하루 전 제출을 목표로 하세요.")
          + p("그런데 가장 중요한 건 지원서 작성 시간이에요. 자기소개서 문항과 증빙 서류를 챙기다 보면 생각보다 오래 걸려요.")
          + p("신청 안 하면 그대로 지나가는 기회예요. 접수창부터 미리 열어두세요.")
          + cta("접수창 열기", src))

    # H2 3 자격
    s3 = (h2(3, toc_items[2])
          + p(f"공고 데이터 기준으로 학력 조건은 「{acbg}」, 경력 구분은 「{se}」이에요.")
          + table(["항목", "기준"], [
              ["학력", acbg], ["경력", se],
              ["직무분야", ncs_text(job)], ["대체인력", "예(휴직자 등 공석 대체)" if repl else "아니오"]], ["35%", "65%"])
          + (box("blue", "📌 핵심 포인트", "학력무관 공고라도 자격증·면허·어학 같은 필수 요건이 따로 붙을 수 있어요. 지원 전에 원문 공고의 응시 자격 칸을 꼭 확인하세요.")
             if "학력무관" in acbg else
             box("blue", "📌 핵심 포인트", "학력 요건이 있는 공고예요. 졸업 예정자 인정 여부와 전공 제한이 있는지 원문 공고에서 확인하세요."))
          + p("그런데 가장 중요한 건 우대사항과 결격사유예요. 가산점을 받을 수 있는 조건은 원문 공고에만 자세히 나와 있어요.")
          + p("이 조건 보고 포기하시는 분 많은데, 막상 원문을 보면 해당되는 경우가 훨씬 많아요.")
          + cta("지원 자격 보기", src))

    # ★ H2 4 보수 수준 (연봉 JSON 연동)
    sal = _find_salary(inst)
    if sal:
        avg_val = f"약 {sal['avg']:,}만원"
        sal_rows = [["직원 평균보수", r(avg_val)]]
        if sal.get("entry") and sal["entry"] > 0:
            sal_rows.append(["신입 초봉 (추정)", f"약 {sal['entry']:,}만원"])
        sal_intro = f"{inst}의 알리오 공개 데이터 기준 보수 수준을 정리했어요."
    else:
        sal_rows = [["직원 평균보수", "공개 데이터 확인 중"]]
        sal_intro = f"{inst}의 보수 수준은 아직 공개 데이터에서 확인하지 못했어요."
    s4 = (h2(4, toc_items[3])
          + p(sal_intro)
          + table(["구분", "금액"], sal_rows, ["40%", "60%"])
          + box("blue", "📌 참고하세요", "위 금액은 공개 데이터 기준 전 직원 평균이에요. 신입 초봉과는 차이가 있으며, 실제 보수는 직급·직무·성과에 따라 달라져요.")
          + p("그런데 가장 중요한 건 실제 수령액이에요. 기본급 외에 성과급·수당·복리후생이 더해지면 체감 연봉이 달라져요.")
          + p("생각보다 금액이 커서 놀라시는 분이 많아요. 실제 처우부터 확인해보세요.")
          + cta("처우 확인하기", src))

    # H2 5 전형
    s5 = (h2(5, toc_items[4])
          + p("공공기관 채용은 보통 서류, 필기, 면접 순서로 진행돼요. 다만 직무와 고용형태에 따라 필기 없이 서류와 면접만 보는 공고도 있어요.")
          + table(["단계", "일반적인 내용"], [
              ["서류전형", "입사지원서·자기소개서, 자격 요건 확인"],
              ["필기전형", "NCS 직업기초능력·직무수행능력 등 (공고마다 다름)"],
              ["면접전형", "직무 역량·인성 면접 (1~2회)"],
              ["최종 합격", "신원 조회·채용 신체검사 후 임용"]], ["30%", "70%"])
          + box("green", "💡 알아두세요", "위 표는 공공기관 채용의 일반적인 흐름이에요. 이 공고의 실제 전형 단계와 배점은 원문 공고가 기준이에요.")
          + p("그런데 가장 중요한 건 이 공고에 필기가 있느냐예요. 필기 유무에 따라 준비 기간이 완전히 달라져요.")
          + p("전형은 보통 3~4단계인데, 첫 단계에서 가장 많이 떨어져요. 전형 절차부터 확인해보세요.")
          + cta("전형 절차 보기", src))

    # H2 6 선배 포인트
    tip = NCS_TIPS.get(ncs_main, DEFAULT_TIP)
    s6 = (h2(6, toc_items[5])
          + p("공공기관에 합격한 선배들이 공통으로 꼽는 준비 포인트가 있어요. 특정 기관의 비법이라기보다 어느 공고에나 통하는 기본기예요.")
          + p(f"첫째, 직무에 맞는 준비가 먼저예요. {tip}")
          + p("둘째, 블라인드 채용 규칙을 지켜야 해요. 공공기관은 출신 학교나 가족관계 같은 인적 정보를 요구하지 않는 블라인드 채용을 운영해요. 자기소개서에 학교명 등을 적으면 불이익을 받을 수 있어요.")
          + p("셋째, 직무기술서를 꼭 읽어요. 공고에 첨부된 직무기술서에 필요한 지식·기술·태도가 정리돼 있어서 자기소개서와 면접의 기준이 돼요.")
          + table(["자주 하는 실수", "대처법"], [
              ["자격증·어학 유효기간 확인 누락", "마감일 기준으로 유효한지 다시 확인"],
              ["자소서에 학교명·지역 노출", "활동명·기관명까지 블라인드 기준으로 점검"],
              ["마감 당일 제출", "사이트 접속이 몰리니 하루 전 제출"]], ["45%", "55%"])
          + p("그런데 가장 중요한 건 이번 공고의 자기소개서 문항이에요. 문항과 글자 수는 접수 사이트에서만 확인할 수 있어요.")
          + p("'나도 준비가 될까' 싶으셨나요? 문항부터 한 번 확인하면 준비할 분량이 바로 보여요.")
          + cta("지원서 준비하기", src))

    # H2 7 함께 보면 좋은 공고
    rel_rows = [[clean_inst(j["instNm"]), hire_short(j), dot(j["pbancEndYmd"])[5:]] for j in (related or [])[:3]]
    s7 = (h2(7, toc_items[6])
          + p(f"같은 {ncs_main or '분야'} 분야에서 지금 접수 중인 공고도 함께 보세요. 여러 곳을 같이 준비하면 자기소개서와 필기 준비를 겹쳐 쓸 수 있어요.")
          + (table(["기관", "고용형태", "마감"], rel_rows, ["45%", "30%", "25%"]) if rel_rows else "")
          + p("전국에서 접수 중인 공고를 마감임박순으로 모아두었어요. 지역별로 걸러서 내 조건에 맞는 공고를 찾아보세요.")
          + cta("전국 공고 더 보기", HIRING))

    # FAQ
    if hl and hl[0] == "정규직":
        q3 = ("초봉이 얼마나 되나요?", f"공개 데이터 기준으로 공기업 정규직 초봉은 기관마다 달라요. {inst}의 정확한 처우는 원문 공고와 채용 안내에서 확인하세요.")
    elif hl and hl[0].startswith("청년인턴"):
        q3 = ("청년인턴은 누가 지원할 수 있나요?", "청년인턴은 보통 청년 연령 기준을 두고 선발해요. 연령 기준과 인턴 기간은 원문 공고를 확인하세요.")
    else:
        q3 = ("계약 기간이 끝나면 어떻게 되나요?", "기관 사정과 평가에 따라 재계약하거나 종료돼요. 연장·전환 가능 여부는 원문 공고에 적힌 기준을 확인하세요.")
    faqs = [
        ("마감 당일 몇 시까지 접수되나요?", f"마감일은 {r(md_w(end))}이에요. 마감 시각은 기관마다 달라서 원문 공고에서 꼭 확인하고, 하루 전 제출을 권해요."),
        ("학력 조건이 어떻게 되나요?", f"공고 데이터 기준 학력 조건은 「{acbg}」이에요. 전공이나 졸업 예정자 인정 여부는 원문 공고를 확인하세요."),
        q3,
        ("다른 공공기관과 중복 지원할 수 있나요?", "공공기관은 같은 날 필기를 치르는 경우가 많고, 일부 기관은 중복 지원을 제한해요. 원문 공고의 유의사항을 확인하세요."),
        ("경력이 없어도 지원할 수 있나요?", "신입 모집이면 경력 없이 지원할 수 있어요. 경력 모집은 인정 경력 기준이 따로 있으니 원문 공고를 확인하세요." if "신입" in se
         else "이 공고는 경력 모집이에요. 인정되는 경력의 범위와 기간은 원문 공고에서 확인하세요."),
    ]

    # ★ body 조립 — 인트로CTA와 H2#1 사이 광고 제거
    body = (AD + toc(toc_items) + AD
            + intro + cta("지금 지원하기", src)
            + s1 + AD + s2 + AD + s3 + AD + s4 + AD + s5 + AD + s6 + AD + s7
            + AD
            + '<h2 style="background:#F0F7FF; border-left:5px solid #3B82F6; border-radius:0 10px 10px 0; color:#1e293b; font-size:22px; font-weight:bold; margin:40px 0 18px; padding:14px 18px;">자주 묻는 질문</h2>'
            + faq(faqs)
            # ★ 결론 멘트 강화
            + p(f"이번 {inst} 공고는 {r(md_w(end))}에 접수가 끝나요. {tenure}{hs} {nope_text(job)} — 이런 공채는 자주 안 열려요.")
            + cta("지금 바로 지원하기", src)
            + AD
            + '<div style="background:#F3F4F6; border-radius:10px; padding:16px 18px; margin:30px 0 10px; font-size:14px; color:#6B7280; line-height:1.65; word-break:keep-all;">'
              '본 글은 공공기관 채용정보(잡알리오) 공개 데이터를 바탕으로 작성되었어요. 모집 분야, 자격 요건, 일정은 기관 사정에 따라 바뀔 수 있으니 지원 전 반드시 원문 공고를 확인하세요. 본 페이지는 채용 기관과 관계가 없는 정보 안내 페이지예요.</div>'
            + '<script>(function(){var e=document.querySelectorAll(".jm-dday");for(var i=0;i<e.length;i++){var d=Math.ceil((new Date(e[i].getAttribute("data-end"))-new Date())/86400000)-1;e[i].textContent=d>0?("D-"+d+" (마감까지 "+d+"일)"):(d===0?"D-DAY (오늘 마감)":"접수 마감");}})();</script>')

    return ('<div style="max-width:720px; margin:0 auto; font-family:\'Pretendard\',\'Noto Sans KR\',-apple-system,sans-serif; color:#333;">'
            + body + '</div>')
