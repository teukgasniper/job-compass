"""채용공고 1건 → 상세 글 HTML (지침서 2번 페이지 / 거미줄 v3.6 규격)
원칙: 과장은 OK, 거짓은 NO — 데이터에 없는 사실(연봉·전형 확정·어학 기준)은 쓰지 않는다.

v2 변경사항:
- 인트로 후킹박스 (파란 배경, 연봉 인라인, 셀링포인트 태그)
- 첫 번째 CTA: "채용공고 바로가기"로 변경 (나머지 CTA는 기존 유지)
- 연봉 테이블을 H2-1(채용 개요) 안으로 병합 → 별도 H2 삭제
- NCS 분류 태그 (H2-1 안)
- 전형절차 화살표 ▼ (테이블 → 화살표 교체)
- 정규직이면 고용형태 섹션 생략 (H2 6개), 비정규직이면 고용형태 설명 추가 (H2 7개)
- 광고: 정규직 10개, 비정규직 11개 (소제목 위마다 1개)
"""
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

# ───────── v2 신규 부품 ─────────

def intro_box(inst, total_count, hire_type, starting_salary, avg_salary, inst_desc, selling_point, offered=""):
    """인트로 후킹 박스 — 목차 아래, 첫 CTA 위에 1회만"""
    salary_line = ""
    if starting_salary and avg_salary:
        salary_line = (f'<p style="font-size:17px; color:#1e293b; margin:0 0 8px; line-height:1.6; word-break:keep-all;">'
                       f'신입 초봉 약 <span style="color:#EF4444; font-weight:bold;">{starting_salary:,}만원</span>, '
                       f'직원 평균 연봉 <span style="color:#EF4444; font-weight:bold;">{avg_salary:,}만원</span> 수준{inst_desc}.</p>')
    elif avg_salary:
        salary_line = (f'<p style="font-size:17px; color:#1e293b; margin:0 0 8px; line-height:1.6; word-break:keep-all;">'
                       f'직원 평균 연봉 <span style="color:#EF4444; font-weight:bold;">{avg_salary:,}만원</span> 수준{inst_desc}.</p>')
    elif offered:
        salary_line = (f'<p style="font-size:17px; color:#1e293b; margin:0 0 8px; line-height:1.6; word-break:keep-all;">'
                       f'공고 제시 연봉은 <span style="color:#EF4444; font-weight:bold;">{offered}</span>이에요.</p>')

    sp_line = ""
    if selling_point:
        sp_line = f'<p style="font-size:17px; color:#1e293b; margin:0 0 8px; line-height:1.6; word-break:keep-all;">{selling_point}</p>'

    count_text = f'<span style="color:#EF4444; font-weight:bold;">{total_count}명</span> ' if total_count > 0 else ""

    return (f'<div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:14px; padding:22px 20px; margin:10px 0 24px;">'
            f'<p style="font-size:20px; font-weight:bold; color:#1E3A8A; margin:0 0 12px; line-height:1.45; word-break:keep-all;">'
            f'{inst}이(가) {count_text}{hire_type} 채용을 시작했습니다.</p>'
            f'{salary_line}{sp_line}'
            f'<p style="font-size:16px; color:#374151; margin:12px 0 0; line-height:1.6; word-break:keep-all;">'
            f'아래에서 모집 분야, 전형 일정, 시험 과목까지 한 번에 확인하세요.</p>'
            f'</div>')

def selling_tags(hire_type, total_count, edu_label, deadline_short):
    """셀링포인트 태그 (인트로 박스 아래)"""
    tag_style = 'display:inline-block; background:#DBEAFE; color:#1E40AF; font-size:14px; font-weight:600; padding:6px 14px; border-radius:20px;'
    deadline_style = 'display:inline-block; background:#FEF3C7; color:#92400E; font-size:14px; font-weight:600; padding:6px 14px; border-radius:20px;'
    tags = f'<span style="{tag_style}">✅ {hire_type} {total_count}명</span>' if total_count > 0 else f'<span style="{tag_style}">✅ {hire_type}</span>'
    tags += f' <span style="{tag_style}">✅ {edu_label}</span>'
    tags += f' <span style="{tag_style}">✅ 블라인드 채용</span>'
    tags += f' <span style="{deadline_style}">⏰ {deadline_short} 마감</span>'
    return f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px;">{tags}</div>'

# ───────── 클린아이 제시 연봉 / 전형방법 ─────────
SOURCE_NAME = {"alio": "잡알리오", "cleaneye": "클린아이", "gojobs": "나라일터"}

def offered_salary(job):
    """클린아이 YEARINCOME → '4,000만원 이상'. 값이 없거나 숫자가 없으면 ''."""
    v = (job.get("yearIncome") or "").strip()
    if not v or v == "-" or not re.search(r"\d", v):
        return ""
    return re.sub(r"\d{4,}", lambda m: f"{int(m.group()):,}", v)

# (정규식, 단계명, 설명) — 전형방법 문장에서 등장 순서대로 뽑는다
_STAGES = [
    (r"서류", "서류전형", "입사지원서·자기소개서 + 자격 요건 확인"),
    (r"필기", "필기전형", "필기시험 (과목은 원문 공고 확인)"),
    (r"인적성|인성", "인성검사", "인성·적성 검사"),
    (r"실기", "실기전형", "실기 평가 (종목은 원문 공고 확인)"),
    (r"체력", "체력검사", "체력 검사"),
    (r"블라인드\s*면접", "블라인드 면접", "학교·가족 등 인적 정보 없이 보는 면접"),
    (r"면접", "면접전형", "직무 역량·인성 면접"),
    (r"신체검사|채용검진|건강검진", "채용 신체검사", "임용 전 신체검사"),
    (r"결격", "결격사유 조회", "임용 결격사유 확인"),
]

def parse_judge(text):
    """전형방법 문장 → [(단계명, 설명), ...]. 2단계 미만이면 [] (일반 흐름으로 대체)."""
    t = (text or "").strip()
    if not t or t == "-" or "http" in t:
        return []
    hits = []  # (위치, 차수, 단계명, 설명)
    taken = []
    for pat, name, desc in _STAGES:
        for m in re.finditer(pat, t):
            if any(a <= m.start() < b for a, b in taken):
                continue  # '블라인드면접'을 '면접'으로 또 잡지 않기
            taken.append((m.start(), m.end()))
            num = re.search(r"(\d)\s*차\s*$", t[max(0, m.start() - 4):m.start()])
            hits.append((m.start(), int(num.group(1)) if num else None, name, desc))
    if not hits:
        return []
    numbered = [h for h in hits if h[1] is not None]
    # 'N차 ○○' 표기가 서류까지 포함해 2개 이상이면 그 순서를 믿는다 (가점 설명 속 '필기' 등 잡음 제거)
    if len(numbered) >= 2 and any(h[2] == "서류전형" for h in numbered):
        hits = sorted(numbered, key=lambda h: h[1])
    else:
        hits = sorted(hits, key=lambda h: h[0])
    stages, seen = [], set()
    for _, num, name, desc in hits:
        key = (name, num) if name == "실기전형" else name
        if key in seen:
            continue
        seen.add(key)
        stages.append((f"{num}차 {name}" if name == "실기전형" and num else name, desc))
    return stages if len(stages) >= 2 else []

def judge_chain(stages):
    short = {"서류전형": "서류", "필기전형": "필기", "면접전형": "면접", "채용 신체검사": "신체검사"}
    return " → ".join(short.get(n, n) for n, _ in stages)

def arrow_steps_from_judge(stages, bgn_date, end_date):
    """클린아이 전형방법 기준 화살표 블록"""
    steps = [("접수 기간", f"{bgn_date} ~ {end_date}")]
    for i, (name, desc) in enumerate(stages, 1):
        steps.append((f"{i}단계 — {name}", desc))
    steps.append(("최종 합격", "세부 임용 절차는 원문 공고 기준"))
    html = '<div style="max-width:400px; margin:20px auto;">'
    for i, (title, desc) in enumerate(steps):
        html += arrow_step(title, desc, is_last=(i == len(steps) - 1))
    html += '</div>'
    html += '<p style="font-size:14px; color:#9CA3AF; margin:12px 0 0; text-align:center;">※ 단계별 세부 일정은 원문 공고에서 확인하세요.</p>'
    return html

def offered_salary_table(offered):
    """알리오 연봉 데이터가 없을 때 — 클린아이 공고 제시 연봉"""
    if not offered:
        return ""
    th_s = 'background:#F1F5F9; color:#1e293b; padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; text-align:center;'
    td_s = 'padding:12px 10px; border:1px solid #E2E8F0; font-size:18px; line-height:1.55; word-break:keep-all; vertical-align:middle; text-align:center;'
    return (f'<div style="overflow-x:auto; margin:18px 0 22px;">'
            f'<table style="width:100%; border-collapse:collapse; background:#fff;">'
            f'<thead><tr><th style="{th_s}">공고 제시 연봉</th></tr></thead>'
            f'<tbody><tr><td style="{td_s}"><span style="color:#EF4444; font-weight:bold;">{offered}</span></td></tr></tbody></table></div>'
            f'<p style="font-size:13px; color:#9CA3AF; margin:0 0 16px; text-align:right;">출처: 클린아이 지방공공기관 채용정보 (기관 등록값)</p>')

# ───────── 보강 블록 (조회수 50회 돌파 → enhance_posts.py가 enh 데이터를 넘김) ─────────
# 디자인 기준: 02번 채팅 한국남부발전 보강본 (kospo-v2-enhanced.html)
import html as _html
_TH = 'background:#F1F5F9; color:#1e293b; padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; text-align:center;'
_TD = 'padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; line-height:1.55; word-break:keep-all; vertical-align:middle;'
_RED = 'color:#EF4444; font-weight:bold;'

def _e(v):
    """Claude가 준 문자열은 항상 이스케이프해서 넣는다"""
    return _html.escape(str(v if v is not None else "").strip())

def _num(v):
    try:
        return int(str(v).replace(",", "").replace("명", "").strip())
    except Exception:
        return None

def _hl(text, highlight):
    """문장 안의 강조 구절 1곳만 빨간색 (이스케이프 후 치환)"""
    t = _e(text)
    h = _e(highlight) if highlight else ""
    return t.replace(h, f'<span style="{_RED}">{h}</span>', 1) if h and h in t else t

_TOTAL_LABEL = re.compile(r"^(총\s*계|합\s*계|소\s*계|계|전\s*체|총\s*원|총\s*인원)$")

def crew_rows(crew):
    """합계·총계 행은 빼고 반환 (합계는 코드가 직접 계산하므로 중복 방지)"""
    return [x for x in (crew.get("rows") or [])
            if x.get("label") and not _TOTAL_LABEL.match(re.sub(r"[()\[\]\s]", "", str(x["label"])))]

def enh_crew_section(crew):
    """H2 sec1b — 모집 분야별 세부 인원 (광고 없음: 하위 섹션)"""
    cols = [c for c in (crew.get("columns") or []) if str(c).strip()][:8]
    rows = crew_rows(crew)[:10]
    if not cols or not rows:
        return ""
    wide = len(cols) >= 4
    first_w = 20 if wide else 40
    other_w = (100 - first_w) // len(cols)
    head = f'<th style="{_TH} width:{first_w}%;">구분</th>' + "".join(
        f'<th style="{_TH} width:{other_w}%;">{_e(c)}</th>' for c in cols)
    body = ""
    for x in rows:
        vals = (list(x.get("values") or []) + [None] * len(cols))[:len(cols)]
        cells = "".join(f'<td style="{_TD} text-align:center;">{_e(v) if v not in (None, "", 0, "0") else "-"}</td>' for v in vals)
        body += f'<tr><td style="{_TD} font-weight:bold;">{_e(x["label"])}</td>{cells}</tr>'
    # 합계 줄: 행이 2개 이상이고 숫자로 더할 수 있으면 자동 계산 (Claude 계산을 믿지 않음)
    if len(rows) >= 2:
        sums = []
        for i in range(len(cols)):
            nums = [_num((list(x.get("values") or []) + [None] * len(cols))[i]) for x in rows]
            sums.append(sum(n for n in nums if n) if any(nums) else None)
        if any(sums):
            cells = "".join(f'<td style="{_TD} text-align:center; font-weight:bold;">{s if s else "-"}</td>' for s in sums)
            body += f'<tr style="background:#F8FAFC;"><td style="{_TD} font-weight:bold;">합계</td>{cells}</tr>'
    out = (h2("1b", "모집 분야별 세부 인원")
           + (p(_e(crew["summary"])) if crew.get("summary") else "")
           + f'<div style="overflow-x:auto; margin:18px 0 22px;"><table style="width:100%; border-collapse:collapse; background:#fff;{" min-width:500px;" if len(cols) >= 6 else ""}">'
           + f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    if crew.get("note"):
        out += f'<p style="font-size:14px; color:#6B7280; margin:0 0 16px;">※ {_e(crew["note"])}</p>'
    return out

def enh_arrow_steps(steps):
    """날짜가 들어간 전형 화살표 — step / notice(중간 발표, 점선 박스) / final"""
    items = [s for s in (steps or []) if s.get("title") or s.get("label")]
    if len([s for s in items if s.get("type") != "notice"]) < 2:
        return ""
    out = '<div style="max-width:400px; margin:20px auto;">'
    for i, s in enumerate(items):
        kind = s.get("type") or "step"
        is_last = i == len(items) - 1
        if kind == "notice":
            out += ('<div style="background:#FFF7ED; border:1px dashed #F97316; border-radius:8px; padding:8px 14px; text-align:center; margin:0 auto; max-width:280px;">'
                    f'<p style="margin:0; font-size:13px; color:#9A3412;">📋 {_e(s.get("label"))}: <b>{_e(s.get("date"))}</b></p></div>')
        else:
            final = kind == "final"
            bg, bd, tc = ("#F0FDF4", "#22C55E", "#166534") if final else ("#EFF6FF", "#3B82F6", "#1E3A8A")
            title = ("🎉 " if final else "") + _e(s.get("title"))
            out += f'<div style="background:{bg}; border:2px solid {bd}; border-radius:12px; padding:16px 18px; text-align:center;">'
            out += f'<p style="margin:0; font-size:16px; font-weight:bold; color:{tc};">{title}</p>'
            if s.get("date"):
                out += f'<p style="margin:4px 0 0; font-size:14px; color:#EF4444; font-weight:bold;">📅 {_e(s["date"])}</p>'
            if s.get("desc"):
                out += f'<p style="margin:4px 0 0; font-size:14px; color:#374151;">{_e(s["desc"])}</p>'
            if s.get("note"):
                out += f'<p style="margin:4px 0 0; font-size:13px; color:#6B7280;">{_e(s["note"])}</p>'
            out += '</div>'
        if not is_last:
            nxt = items[i + 1].get("type")
            color = "#22C55E" if nxt == "final" else "#3B82F6"
            pad = "4px" if kind == "notice" or nxt == "notice" else "6px"
            out += f'<div style="text-align:center; padding:{pad} 0;"><span style="font-size:24px; color:{color}; font-weight:bold;">▼</span></div>'
    return out + '</div>'

def enh_language_box(lang):
    if not lang or not lang.get("text"):
        return ""
    return box("blue", "📋 " + _e(lang.get("title") or "어학 기준"), _hl(lang["text"], lang.get("highlight")))

def enh_written_section(w):
    """H2 sec5b — 필기전형 과목·문항수 상세"""
    subs = [s for s in (w.get("subjects") or []) if s.get("name")][:8]
    if not subs:
        return ""
    body = ""
    for s in subs:
        cnt = _e(s.get("count")) if s.get("count") not in (None, "", 0) else "-"
        cnt_html = f'<span style="{_RED}">{cnt}</span>' if cnt != "-" else "-"
        scope = _e(s.get("scope") or "-")
        if s.get("note"):
            scope += f'<br><span style="color:#7C3AED; font-weight:bold;">★ {_e(s["note"])}</span>'
        ncs_badge = ('<br><span style="display:inline-block; margin-top:4px; background:#DCFCE7; color:#166534; '
                     'font-size:12px; font-weight:bold; padding:2px 8px; border-radius:10px;">NCS</span>') if s.get("ncs") is True else ""
        body += (f'<tr><td style="{_TD} font-weight:bold;">{_e(s["name"]).replace("(", "<br>(", 1)}{ncs_badge}</td>'
                 f'<td style="{_TD} text-align:center;">{cnt_html}</td><td style="{_TD}">{scope}</td></tr>')
    out = (h2("5b", "필기전형 과목·문항수 상세")
           + (p(_hl(w["summary"], w.get("highlight"))) if w.get("summary") else "")
           + '<div style="overflow-x:auto; margin:18px 0 22px;"><table style="width:100%; border-collapse:collapse; background:#fff;">'
           + f'<thead><tr><th style="{_TH} width:30%;">과목</th><th style="{_TH} width:15%;">문항수</th><th style="{_TH} width:55%;">출제 범위</th></tr></thead>'
           + f'<tbody>{body}</tbody></table></div>')
    tip = w.get("callout") or {}
    if tip.get("text"):
        out += box("blue", _e(tip.get("title") or "💡 참고하세요"), _e(tip["text"]))
    return out

def salary_table(sal):
    """연봉 테이블 (H2-1 안에 삽입)"""
    if not sal:
        return ""
    th_s = 'background:#F1F5F9; color:#1e293b; padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; text-align:center;'
    td_s = 'padding:12px 10px; border:1px solid #E2E8F0; font-size:15px; line-height:1.55; word-break:keep-all; vertical-align:middle; text-align:center;'
    entry_val = sal.get("entry", 0)
    avg_val = sal.get("avg", 0)
    if not avg_val:
        return ""
    entry = f'약 {entry_val:,}만원' if entry_val and entry_val > 0 else "공개 데이터 확인 중"
    avg = f'약 {avg_val:,}만원'
    return (f'<div style="overflow-x:auto; margin:18px 0 22px;">'
            f'<table style="width:100%; border-collapse:collapse; background:#fff;">'
            f'<thead><tr><th style="{th_s} width:50%;">신입 초봉</th><th style="{th_s} width:50%;">직원 평균 연봉</th></tr></thead>'
            f'<tbody><tr>'
            f'<td style="{td_s} font-size:18px;"><span style="color:#EF4444; font-weight:bold;">{entry}</span></td>'
            f'<td style="{td_s} font-size:18px;"><span style="color:#EF4444; font-weight:bold;">{avg}</span></td>'
            f'</tr></tbody></table></div>'
            f'<p style="font-size:13px; color:#9CA3AF; margin:0 0 16px; text-align:right;">출처: 알리오 공공기관 경영공시</p>')

def ncs_tags(ncs_items):
    """NCS 분류 태그 (H2-1 안에 삽입)"""
    if not ncs_items:
        return ""
    tags = ''.join(
        f'<span style="display:inline-block; background:#F3F4F6; color:#374151; font-size:13px; padding:5px 12px; '
        f'border-radius:6px; border:1px solid #E5E7EB;">{ncs}</span>' for ncs in ncs_items)
    return (f'<div style="margin:16px 0 20px;">'
            f'<p style="font-size:14px; color:#6B7280; margin:0 0 8px; font-weight:600;">NCS 표준직무 분류</p>'
            f'<div style="display:flex; flex-wrap:wrap; gap:6px;">{tags}</div></div>')

def arrow_step(title, desc, is_last=False):
    """전형절차 화살표 단일 스텝"""
    bg = "#F0FDF4" if is_last else "#EFF6FF"
    border_color = "#22C55E" if is_last else "#3B82F6"
    text_color = "#166534" if is_last else "#1E3A8A"
    arrow_color = "#22C55E" if is_last else "#3B82F6"
    block = (f'<div style="background:{bg}; border:2px solid {border_color}; border-radius:12px; padding:16px 18px; text-align:center;">'
             f'<p style="margin:0; font-size:16px; font-weight:bold; color:{text_color};">{title}</p>'
             f'<p style="margin:4px 0 0; font-size:14px; color:#374151;">{desc}</p></div>')
    if not is_last:
        block += f'\n<div style="text-align:center; padding:6px 0;"><span style="font-size:24px; color:{arrow_color}; font-weight:bold;">▼</span></div>'
    return block

def arrow_steps_html(bgn_date, end_date):
    """전형절차 화살표 블록 (기본 자동발행용)"""
    steps = [
        ("접수 기간", f"{bgn_date} ~ {end_date}"),
        ("1단계 — 서류전형", "입사지원서·자기소개서 + 자격 요건 확인"),
        ("2단계 — 필기전형", "NCS 직업기초능력 + 전공(공고마다 다름)"),
        ("3단계 — 면접전형", "직무 역량·인성 면접 (1~2회)"),
        ("최종 합격", "신원조회 · 채용 신체검사 후 임용"),
    ]
    html = '<div style="max-width:400px; margin:20px auto;">'
    for i, (title, desc) in enumerate(steps):
        html += arrow_step(title, desc, is_last=(i == len(steps) - 1))
    html += '</div>'
    html += '<p style="font-size:14px; color:#9CA3AF; margin:12px 0 0; text-align:center;">※ 단계별 세부 일정은 원문 공고에서 확인하세요.</p>'
    return html

def hire_type_section(sec_num, hl):
    """고용형태 설명 섹션 (비정규직일 때만 표시)"""
    main_type = hl[0] if hl else ""

    if "무기계약직" in main_type:
        desc = ("무기계약직은 계약 기간의 정함이 없는 근로계약이에요. 정규직과 마찬가지로 정년까지 근무할 수 있고, "
                "호봉제가 적용되는 기관도 많아요. 다만 승진 체계나 일부 복리후생은 정규직과 다를 수 있어요.")
        tip = "정년 보장 + 호봉제 적용이 핵심이에요. 처우는 기관마다 다르니 원문 공고에서 확인하세요."
    elif "채용형" in main_type or "인턴" in main_type:
        desc = ("채용형 인턴은 일정 기간 인턴으로 근무한 뒤 평가를 거쳐 정규직으로 전환되는 채용 방식이에요. "
                "전환율은 기관마다 다르지만, 최근 공공기관의 정규직 전환율은 높은 편이에요.")
        tip = "인턴 기간과 정규직 전환 평가 기준이 핵심이에요. 원문 공고에서 전환율도 확인하세요."
    elif "공무직" in main_type:
        desc = ("공무직은 국가기관이나 지자체에서 무기계약 형태로 채용하는 직원이에요. 정년이 보장되고, "
                "공무원은 아니지만 공무원에 준하는 복리후생을 받는 경우가 많아요.")
        tip = "정년 보장 + 공무원 준하는 복리후생이 핵심이에요. 공무원과의 차이는 신분과 승진 체계예요."
    elif "기간제" in main_type or "계약" in main_type:
        desc = ("기간제 근로계약으로, 계약 기간이 정해져 있어요. 기간 만료 후 재계약하거나 종료될 수 있고, "
                "2년 이상 근무 시 무기계약직으로 전환되는 경우도 있어요.")
        tip = "계약 기간과 연장·전환 가능성이 핵심이에요. 원문 공고에서 계약 조건을 확인하세요."
    else:
        desc = f"이 공고의 고용형태는 「{main_type}」이에요. 고용 조건과 계약 기간은 원문 공고에서 확인하세요."
        tip = "고용형태에 따라 계약 기간, 전환 가능성, 복리후생이 달라져요."

    return (h2(sec_num, f"고용형태 알아보기: {main_type}")
            + p(desc)
            + box("blue", "📌 핵심 포인트", tip)
            + p("고용형태가 정규직이 아니라고 포기하지 마세요. 무기계약직과 채용형 인턴은 정년 보장이나 정규직 전환이 가능한 경우가 많아요.")
            + p("이 공고의 정확한 고용 조건은 원문 공고에서 확인하세요."))


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
def build_html(job, src, related=None, enh=None):
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

    # ★ 정규직 여부 판단
    is_regular = any(h in ("정규직",) for h in hl)

    # ★ 연봉 데이터
    sal = _find_salary(inst)
    starting = sal.get("entry", 0) if sal else 0
    avg = sal.get("avg", 0) if sal else 0
    inst_desc = ""  # 기관 설명 (향후 확장 가능)
    offered = "" if avg else offered_salary(job)          # 알리오 연봉 없을 때만 클린아이 제시 연봉
    stages = parse_judge(job.get("judgeMethod"))          # 클린아이 전형방법 (없으면 [])
    has_written = any("필기" in n for n, _ in stages)
    step_toc = f"전형 절차: {judge_chain(stages)}" if stages else "전형 절차: 공공기관 채용 흐름 한눈에 보기"
    source_name = SOURCE_NAME.get(job.get("_source"), "잡알리오")

    # ★ 셀링포인트
    points = []
    if "학력무관" in acbg:
        points.append("학력무관")
    if nope >= 50:
        points.append("대규모 공채")
    if len(regions(job)) >= 10:
        points.append("전국 배치")
    restriction = (enh or {}).get("restriction") or ""       # 보강 데이터: 지원 대상 제한 (보훈·장애 전용 등)
    if restriction:
        selling_point = (", ".join(points) + f" — 단, {_e(restriction)}") if points else f"단, {_e(restriction)}"
    else:
        selling_point = ", ".join(points) + " — 누구나 지원 가능합니다." if points else ""

    # ★ 목차 구성 (정규직 H2 6개 / 비정규직 H2 7개)
    if is_regular:
        toc_items = [
            f"채용 개요: {inst} {hs} {nope_text(job)} 모집",
            f"접수 일정: {md(end)} 마감",
            f"지원 자격: {acbg.split(', ')[0]} · {se}",
            step_toc,
            f"선배들이 말하는 합격 포인트: {ncs_main or '공공기관'} 직무 준비법",
            "함께 보면 좋은 공고: 전국 채용 더 보기",
        ]
    else:
        toc_items = [
            f"채용 개요: {inst} {hs} {nope_text(job)} 모집",
            f"접수 일정: {md(end)} 마감",
            f"지원 자격: {acbg.split(', ')[0]} · {se}",
            f"고용형태 알아보기: {hs}",
            step_toc,
            f"선배들이 말하는 합격 포인트: {ncs_main or '공공기관'} 직무 준비법",
            "함께 보면 좋은 공고: 전국 채용 더 보기",
        ]

    # ★ 인트로 박스 + 셀링포인트 태그
    edu_label = "학력무관" if "학력무관" in acbg else acbg.split(", ")[0]
    deadline_short = f"{int(end[4:6])}/{int(end[6:])}"
    intro = intro_box(inst, nope, hs, starting if starting > 0 else None, avg if avg > 0 else None, inst_desc, selling_point, offered)
    intro += selling_tags(hs, nope, edu_label, deadline_short)

    # ★ H2-1 채용 개요 (+ 연봉 테이블 + NCS 태그 병합)
    sec_n = 1
    s1 = (h2(sec_n, toc_items[sec_n - 1])
          + p(f"이번 공고는 {inst}의 「{title}」이에요. 핵심 정보를 표로 정리했어요.")
          + (salary_table(sal) if sal else offered_salary_table(offered))
          + table(["항목", "내용"], [
              ["기관", inst], ["공고명", title], ["고용형태", ", ".join(hl) or "공고 참조"],
              ["모집인원", r(nope_text(job)) if nope else nope_text(job)], ["경력구분", se],
              ["직무분야", ncs_text(job)], ["근무지역", region_text(job)],
              ["대체인력 여부", "대체인력 채용" if repl else "해당 없음"]], ["30%", "70%"])
          + ncs_tags(nl)
          + p("그런데 가장 중요한 건 모집 분야별 세부 인원이에요. 분야마다 뽑는 인원과 근무지가 나뉘어 있어서, 내가 지원할 분야를 먼저 골라야 해요.")
          + p("생각보다 선택지가 많아서 놀라시는 분이 많아요. 모집 분야부터 확인해보세요.")
          + cta("모집 분야 보기", src)
          + (enh_crew_section(enh["crew"]) if enh and enh.get("crew") else ""))

    # H2-2 접수 일정
    sec_n += 1
    total = (ymd(end) - ymd(bg)).days
    s2 = (h2(sec_n, toc_items[sec_n - 1])
          + p(f"접수는 {md(bg)}에 시작해서 {md_w(end)}에 끝나요. 전체 접수 기간은 {total}일이에요.")
          + table(["구분", "일정"], [
              ["접수 시작", dot(bg)], ["접수 마감", r(dot(end) + f"({WEEK[ymd(end).weekday()]})")],
              ["남은 기간", f'<span class="jm-dday" data-end="{end[:4]}-{end[4:6]}-{end[6:]}T23:59:59+09:00" {RED}>{md(end)} 마감</span>']],
              ["35%", "65%"])
          + box("red", "⚠️ 주의하세요", "마감 시각은 기관마다 달라요. 오후 6시에 닫는 곳도 많으니 마감 당일이 아니라 하루 전 제출을 목표로 하세요.")
          + p("그런데 가장 중요한 건 지원서 작성 시간이에요. 자기소개서 문항과 증빙 서류를 챙기다 보면 생각보다 오래 걸려요.")
          + p("신청 안 하면 그대로 지나가는 기회예요. 접수창부터 미리 열어두세요.")
          + cta("접수창 열기", src))

    # H2-3 지원 자격
    sec_n += 1
    s3 = (h2(sec_n, toc_items[sec_n - 1])
          + p(f"공고 데이터 기준으로 학력 조건은 「{acbg}」, 경력 구분은 「{se}」이에요.")
          + table(["항목", "기준"], [
              ["학력", acbg], ["경력", se],
              ["직무분야", ncs_text(job)], ["대체인력", "예(휴직자 등 공석 대체)" if repl else "아니오"]], ["35%", "65%"])
          + (box("red", "⚠️ 지원 대상 제한", _e(restriction)) if restriction else "")
          + (box("blue", "📌 핵심 포인트", "학력무관 공고라도 자격증·면허·어학 같은 필수 요건이 따로 붙을 수 있어요. 지원 전에 원문 공고의 응시 자격 칸을 꼭 확인하세요.")
             if "학력무관" in acbg else
             box("blue", "📌 핵심 포인트", "학력 요건이 있는 공고예요. 졸업 예정자 인정 여부와 전공 제한이 있는지 원문 공고에서 확인하세요."))
          + p("그런데 가장 중요한 건 우대사항과 결격사유예요. 가산점을 받을 수 있는 조건은 원문 공고에만 자세히 나와 있어요.")
          + p("이 조건 보고 포기하시는 분 많은데, 막상 원문을 보면 해당되는 경우가 훨씬 많아요.")
          + cta("지원 자격 보기", src))

    # ★ H2-4 고용형태 (비정규직일 때만)
    s4 = ""
    if not is_regular:
        sec_n += 1
        s4 = hire_type_section(sec_n, hl)

    # ★ H2 전형 절차 (화살표 ▼)
    sec_n += 1
    if stages:
        s5_head = (p(f"이번 {inst} 공고는 {judge_chain(stages)} 순서로 진행돼요. 기관이 등록한 전형방법 기준이에요.")
                   + arrow_steps_from_judge(stages, dot(bg), dot(end))
                   + box("green", "💡 알아두세요", "위 단계는 기관이 채용정보에 등록한 전형방법 기준이에요. 단계별 날짜와 배점은 원문 공고가 기준이에요.")
                   + (p("이 공고는 필기가 있어요. 과목과 출제 범위에 따라 준비 기간이 완전히 달라져요.") if has_written else
                      p("등록된 전형방법에는 필기가 없어요. 그만큼 서류와 면접에서 갈리니 자기소개서와 면접 준비가 핵심이에요.")))
    else:
        s5_head = (p("공공기관 채용은 보통 서류, 필기, 면접 순서로 진행돼요. 다만 직무와 고용형태에 따라 필기 없이 서류와 면접만 보는 공고도 있어요.")
                   + arrow_steps_html(dot(bg), dot(end))
                   + box("green", "💡 알아두세요", "위 흐름은 공공기관 채용의 일반적인 절차예요. 이 공고의 실제 전형 단계와 배점은 원문 공고가 기준이에요.")
                   + p("그런데 가장 중요한 건 이 공고에 필기가 있느냐예요. 필기 유무에 따라 준비 기간이 완전히 달라져요."))
    enh_steps = enh_arrow_steps(enh.get("steps")) if enh else ""
    if enh_steps:
        s5_head = (p(f"원문 공고문 기준으로 {inst} 이번 채용의 전형 단계와 일정을 정리했어요.")
                   + enh_steps
                   + box("green", "💡 알아두세요", "일정과 배점은 원문 공고문 기준이에요. 기관 사정에 따라 바뀔 수 있으니 채용 홈페이지 공지를 함께 확인하세요."))
    if enh:
        s5_head += enh_language_box(enh.get("language")) + (enh_written_section(enh["written"]) if enh.get("written") else "")
    s5 = (h2(sec_n, toc_items[sec_n - 1])
          + s5_head
          + p("전형은 보통 3~4단계인데, 첫 단계에서 가장 많이 떨어져요. 전형 절차부터 확인해보세요.")
          + cta("전형 절차 보기", src))

    # H2 선배 합격 포인트
    sec_n += 1
    tip = NCS_TIPS.get(ncs_main, DEFAULT_TIP)
    s6 = (h2(sec_n, toc_items[sec_n - 1])
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

    # H2 함께 보면 좋은 공고
    sec_n += 1
    rel_rows = [[clean_inst(j["instNm"]), hire_short(j), dot(j["pbancEndYmd"])[5:]] for j in (related or [])[:3]]
    s7 = (h2(sec_n, toc_items[sec_n - 1])
          + p(f"같은 {ncs_main or '분야'} 분야에서 지금 접수 중인 공고도 함께 보세요. 여러 곳을 같이 준비하면 자기소개서와 필기 준비를 겹쳐 쓸 수 있어요.")
          + (table(["기관", "고용형태", "마감"], rel_rows, ["45%", "30%", "25%"]) if rel_rows else "")
          + p("전국에서 접수 중인 공고를 마감임박순으로 모아두었어요. 지역별로 걸러서 내 조건에 맞는 공고를 찾아보세요.")
          + cta("전국 공고 더 보기", HIRING))

    # FAQ
    if hl and hl[0] == "정규직":
        q3 = (("연봉은 얼마나 되나요?", f"기관이 등록한 제시 연봉은 {r(offered)}이에요. 직급·경력에 따라 달라지니 정확한 보수는 원문 공고에서 확인하세요.")
              if offered else
              ("초봉이 얼마나 되나요?", f"공개 데이터 기준으로 공기업 정규직 초봉은 기관마다 달라요. {inst}의 정확한 처우는 원문 공고와 채용 안내에서 확인하세요."))
    elif hl and ("채용형" in hl[0] or "인턴" in hl[0]):
        q3 = ("채용형 인턴은 정규직 전환이 되나요?", "대부분의 공공기관 채용형 인턴은 정규직 전환을 전제로 해요. 전환율과 평가 기준은 원문 공고를 확인하세요.")
    elif hl and "무기계약직" in hl[0]:
        q3 = ("무기계약직은 정년 보장이 되나요?", "무기계약직은 계약 기간의 정함이 없어서 정년까지 근무할 수 있어요. 다만 승진 체계는 정규직과 다를 수 있어요.")
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

    # ★ body 조립
    # 광고 배치: 목차 위 + 목차 아래 + 각 H2 위 + FAQ 위 + 면책 위
    sections = [s1, s2, s3]
    if not is_regular:
        sections.append(s4)  # 고용형태 (비정규직만)
    sections.extend([s5, s6, s7])

    # H2 섹션들 사이에 광고 삽입
    sections_with_ads = ""
    for sec in sections:
        sections_with_ads += AD + sec

    tenure = ""
    if any(h in ("정규직", "무기계약직") for h in hl):
        tenure = "정년 보장 "
    elif any("채용형" in h for h in hl):
        tenure = "정규직 전환 "

    body = (AD + toc(toc_items) + AD
            + intro
            + cta("채용공고 바로가기", src)  # ★ 첫 번째 CTA만 변경
            + sections_with_ads
            + AD
            + '<h2 style="background:#F0F7FF; border-left:5px solid #3B82F6; border-radius:0 10px 10px 0; color:#1e293b; font-size:22px; font-weight:bold; margin:40px 0 18px; padding:14px 18px;">자주 묻는 질문</h2>'
            + faq(faqs)
            + p(f"이번 {inst} 공고는 {r(md_w(end))}에 접수가 끝나요. {tenure}{hs} {nope_text(job)} — 이런 공채는 자주 안 열려요.")
            + cta("지금 바로 지원하기", src)
            + AD
            + '<div style="background:#F3F4F6; border-radius:10px; padding:16px 18px; margin:30px 0 10px; font-size:14px; color:#6B7280; line-height:1.65; word-break:keep-all;">'
              '본 글은 공공기관 채용정보(' + source_name + ') 공개 데이터를 바탕으로 작성되었어요. 모집 분야, 자격 요건, 일정은 기관 사정에 따라 바뀔 수 있으니 지원 전 반드시 원문 공고를 확인하세요. 본 페이지는 채용 기관과 관계가 없는 정보 안내 페이지예요.</div>'
            + '<script>(function(){var e=document.querySelectorAll(".jm-dday");for(var i=0;i<e.length;i++){var d=Math.ceil((new Date(e[i].getAttribute("data-end"))-new Date())/86400000)-1;e[i].textContent=d>0?("D-"+d+" (마감까지 "+d+"일)"):(d===0?"D-DAY (오늘 마감)":"접수 마감");}})();</script>')

    return ('<div style="max-width:720px; margin:0 auto; font-family:\'Pretendard\',\'Noto Sans KR\',-apple-system,sans-serif; color:#333;">'
            + body + '</div>')
