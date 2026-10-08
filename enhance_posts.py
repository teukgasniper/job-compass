"""hiring03 본문 보강 (조회수 50회 돌파 글)
─────────────────────────────────────────────
공고번호 → 원문 공고문(PDF·HWP·HWPX·이미지) 텍스트 추출
  [2026-10-08] 알리오 + 클린아이·나라일터(상세페이지 첨부) + 공채속보(기업 채용 페이지를 브라우저로 열어 읽음) → Claude(Sonnet)로 핵심 정보 JSON 추출
→ post_template.build_html(enh=...)로 본문 재생성 → Blogger 글을 같은 주소 그대로 수정

보강 내용 (디자인: 한국남부발전 보강본 kospo-v2-enhanced.html 기준)
  ① 모집 분야별 세부 인원 표 (H2 sec1b, 합계는 코드가 직접 계산)
  ② 전형 단계별 날짜 화살표 (중간 발표는 점선 박스)
  ③ 어학 기준 박스
  ④ 필기 과목·문항 수 표 (H2 sec5b)
  ※ 보강 섹션에는 광고를 추가하지 않음 (하위 섹션)

실행
  python enhance_posts.py 304839 305413          # 지정한 공고 보강
  python enhance_posts.py 304839 --dry-run       # 발행 안 하고 preview/ 에 HTML + JSON 저장
  python enhance_posts.py 304839 --force         # 이미 보강한 글도 다시
  ENHANCE_IDS="304839,305413" python enhance_posts.py   (GitHub Actions 입력용)

필요한 Secrets: CLAUDE_API_KEY, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID
필요한 패키지: pypdf, pyhwp, pypdfium2, pillow, olefile(pyhwp와 함께 설치됨)
[2026-10-08] 공고문이 이미지(jpg·png)면 조각내서 Claude가 읽음 / hwp5html 변환 실패 시 HWP 본문을 직접 읽는 방식으로 재시도
기록: enhanced_posts.json (공고번호 → 보강 시각·추출 데이터)
"""
import json, os, re, sys, io, time, html, zipfile, tempfile, subprocess, urllib.request, urllib.parse, urllib.error
from datetime import datetime
from post_template import build_html, clean_inst, crew_rows, KST
from publish_to_blogger import access_token, api, related_jobs, enrich_gojobs, enrich_work24, is_gojobs, is_work24

JOBS_FILE, MAPPING_FILE, STATE_FILE = "jobs.json", "job_posts.json", "enhanced_posts.json"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5"
FALLBACK_MODEL = "claude-sonnet-4-6"
MAX_DOC_CHARS = 60000        # 공고문 텍스트 상한 (Sonnet 5 기준 글 1개 약 $0.1)
# 100만 토큰당 달러 (입력, 출력) — 공식 가격표 2026-09 기준, 로그 표시용
PRICE = {"claude-sonnet-5": (2, 10), "claude-sonnet-5-5": (2, 10), "claude-sonnet-4-6": (3, 15), "default": (3, 15)}
UA = {"User-Agent": "Mozilla/5.0 (job-compass enhance)"}


# ───────── 1. 원문 공고문 가져오기 ─────────
def http_get(url, timeout=40, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Disposition", "")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 + i * 3)


def alio_notice_files(sn):
    """알리오 채용 상세페이지의 '공고문' 칸 첨부 [(url, 파일명)]"""
    page, _ = http_get(f"https://job.alio.go.kr/recruitview.do?idx={sn}", timeout=20)
    t = page.decode("utf-8", "ignore")
    m = re.search(r"<th>\s*공고문\s*</th>\s*<td>(.*?)</td>", t, re.S)
    if not m:
        return []
    return [(u, html.unescape(n).strip()) for u, n in
            re.findall(r'href="(https?://[^"]*download\.json\?fileNo=\d+)"[^>]*>([^<]+)</a>', m.group(1))]


def _clean(text):
    text = re.sub(r"[ \t\u3000]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def text_from_pdf(data):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join(f"[p{i + 1}] " + (pg.extract_text() or "") for i, pg in enumerate(r.pages))


MAX_TILES = 20          # 이미지 조각 상한 (조각 1개 약 1,900토큰 → 20개면 약 $0.08)
TILE_W, TILE_H = 1300, 1100


def _tiles_from_pil(im, tiles):
    """가로 1300px 이미지를 세로로 잘라 JPEG base64로 tiles에 추가 (60px 겹치게)"""
    import base64
    y = 0
    while y < im.height and len(tiles) < MAX_TILES:
        part = im.crop((0, y, im.width, min(im.height, y + TILE_H)))
        if part.height > 80:
            buf = io.BytesIO()
            part.save(buf, "JPEG", quality=85)
            tiles.append(base64.b64encode(buf.getvalue()).decode())
        y += TILE_H - 60
    return tiles


def images_from_pdf(data):
    """글자가 없는 PDF(포스터·스캔)를 가로 1300px로 렌더링해 세로로 잘라 JPEG base64 목록으로.
    통째로 보내면 자동 축소돼 글씨가 뭉개지므로 잘라서 보낸다 (60px 겹치게)"""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    tiles = []
    for pg in pdf:
        w, _ = pg.get_size()
        _tiles_from_pil(pg.render(scale=TILE_W / w).to_pil().convert("RGB"), tiles)
        if len(tiles) >= MAX_TILES:
            print(f"  [공고문] 이미지 조각 상한 {MAX_TILES}개에서 자름")
            break
    return tiles


IMG_EXT = ("jpg", "jpeg", "png", "gif", "bmp", "webp")


def is_image_file(name, data):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in IMG_EXT or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def images_from_image(data):
    """[2026-10-08] 공고문이 통째로 이미지(jpg·png)인 경우 — 가로 1300px로 맞춰 세로로 자름"""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width != TILE_W:
        im = im.resize((TILE_W, max(1, round(im.height * TILE_W / im.width))))
    tiles = _tiles_from_pil(im, [])
    if len(tiles) >= MAX_TILES:
        print(f"  [공고문] 이미지 조각 상한 {MAX_TILES}개에서 자름")
    return tiles


def text_from_hwp_raw(data):
    """[2026-10-08] hwp5html 변환이 실패하는 HWP용 — 본문 문단 글자를 직접 읽음 (표는 칸마다 한 줄)"""
    import olefile, zlib, struct
    o = olefile.OleFileIO(io.BytesIO(data))
    flags = struct.unpack("<I", o.openstream("FileHeader").read()[36:40])[0]
    if flags & 4:
        raise ValueError("배포용(암호화) HWP라 글자를 읽을 수 없음")
    secs = sorted([e for e in o.listdir() if e[0] == "BodyText"], key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
    out = []
    for e in secs:
        raw = o.openstream(e).read()
        if flags & 1:
            raw = zlib.decompress(raw, -15)
        i = 0
        while i + 4 <= len(raw):
            h = struct.unpack("<I", raw[i:i + 4])[0]; i += 4
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            if size == 0xFFF:
                size = struct.unpack("<I", raw[i:i + 4])[0]; i += 4
            if tag == 67:                                   # 문단 글자
                b, s, k = raw[i:i + size], [], 0
                while k + 2 <= len(b):
                    c = struct.unpack("<H", b[k:k + 2])[0]
                    if c in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23):
                        if c == 9:
                            s.append(" ")
                        k += 16; continue                   # 확장 컨트롤 문자 (8글자 분량)
                    if c in (10, 13):
                        s.append("\n")
                    elif c >= 32:
                        s.append(chr(c))
                    k += 2
                out.append("".join(s))
            i += size
    return "\n".join(out)


def text_from_hwp(data):
    """hwp5html로 변환 (hwp5txt는 표를 빼먹어서 인원·일정이 사라짐) → 실패하면 직접 읽기"""
    try:
        return text_from_hwp_html(data)
    except Exception as e:
        print(f"  [공고문] hwp5html 변환 실패 → 직접 읽기로 재시도 ({str(e)[:80]})")
        return text_from_hwp_raw(data)


def text_from_hwp_html(data):
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "a.hwp"), os.path.join(d, "out")
        open(src, "wb").write(data)
        subprocess.run(["hwp5html", "--output", out, src], check=True, capture_output=True, timeout=120)
        t = open(os.path.join(out, "index.xhtml"), encoding="utf-8").read()
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<(td|th)[^>]*>", " | ", t)
    t = re.sub(r"</tr>|<p[^>]*>|<br\s*/?>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def text_from_hwpx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n))
    out = []
    for n in parts:
        x = z.read(n).decode("utf-8", "ignore")
        x = re.sub(r"</hp:p>|</hp:tr>", "\n", x)
        x = re.sub(r"<hp:tc[^>]*>", " | ", x)
        out.append(html.unescape(re.sub(r"<[^>]+>", "", x)))
    return "\n".join(out)


def text_from_file(name, data):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf" or data[:4] == b"%PDF":
        return text_from_pdf(data)
    if ext == "hwpx":
        return text_from_hwpx(data)
    if ext == "hwp":
        return text_from_hwp(data)
    if ext == "zip":   # 압축 안의 첫 공고문
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            if n.lower().endswith((".pdf", ".hwp", ".hwpx")):
                return text_from_file(n, z.read(n))
    return ""


def http_post(url, form, timeout=60, tries=3):
    data = urllib.parse.urlencode(form).encode()
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA, method="POST"), timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 + i * 3)


def _js_args(s):
    return [html.unescape(x) for x in re.findall(r"'([^']*)'", s)]


def cleaneye_notice_files(sn):
    """[2026-10-08] 클린아이 상세페이지 첨부 [(파일명, 받기함수)] — fn_FileDown(저장명, 원래이름, 경로)"""
    idx = str(sn).replace("CE-", "")
    page, _ = http_get(f"https://job.cleaneye.go.kr/user/ypCareersData.do?idx={idx}", timeout=25)
    out = []
    for call in re.findall(r"fn_FileDown\(((?:\s*'[^']*'\s*,?)+)\)", page.decode("utf-8", "ignore")):   # 파일명 속 괄호 대응
        a = _js_args(call)
        if len(a) >= 3:
            form = {"UPLOAD_FILENAME": a[0], "ORIGINAL_FILENAME": a[1], "FILE_PATH": a[2]}
            out.append((a[1], lambda f=form: http_post("https://job.cleaneye.go.kr/file/FileDownload.do", f)))
    return out


def gojobs_notice_files(sn):
    """[2026-10-08] 나라일터 상세페이지 첨부 [(파일명, 받기함수)] — gfn_fileDown(파일명, uuid, 저장경로)"""
    idx = str(sn).replace("GJ-", "")
    page, _ = http_get(f"https://www.gojobs.go.kr/apmView.do?empmnsn={idx}", timeout=25)
    out = []
    for call in re.findall(r"gfn_fileDown\(((?:\s*'[^']*'\s*,?)+)\)", page.decode("utf-8", "ignore")):   # 파일명 속 괄호 대응
        a = _js_args(call)
        if len(a) >= 3:
            form = {"filenm": a[0], "uuid": a[1], "saveGbn": a[2], "empmnsn": idx}
            out.append((a[0], lambda f=form: http_post("https://www.gojobs.go.kr/downFile.do", f)))
    return out


FORM_WORDS = ("서식", "지원서", "양식", "제출", "동의서", "검토기준", "확인서", "서약서", "자기소개", "경력기술", "제안서", "체크리스트")


def _file_rank(name, title):
    """공고문을 먼저, 제출 서식은 나중에. 공고명과 겹치는 단어가 많을수록 먼저"""
    n = name.replace(" ", "")
    r = 0
    if "공고" in n:
        r -= 10
    if "직무기술" in n:
        r += 3
    if any(w in n for w in FORM_WORDS):
        r += 20
    words = [w for w in re.split(r"[\s()\[\],·/]+", title or "") if len(w) >= 2]
    r -= sum(1 for w in words if w in name)
    return r


def page_material(url):
    """[2026-10-08] 민간(공채속보) 공고 — 기업 채용 페이지를 실제 브라우저로 열어 글자를 읽고,
    글자가 적으면(이미지로 된 공고) 큰 이미지들을 잘라서 넘김. 반환: (텍스트, 이미지조각, 설명)"""
    if not url:
        return "", [], "원문 링크 없음"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "", [], "브라우저(playwright) 없음"
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": TILE_W, "height": 1000}, user_agent=UA["User-Agent"])
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(8000)
            text = _clean(pg.evaluate("() => document.body.innerText") or "")
            if len(text) >= 800:
                return text[:MAX_DOC_CHARS], [], f"기업 채용 페이지 ({url})"
            tiles = []
            srcs = pg.evaluate("() => [...document.images].filter(i => i.naturalWidth >= 500 && i.naturalHeight >= 500)"
                               ".map(i => i.currentSrc || i.src)")
            for u in list(dict.fromkeys(srcs))[:8]:          # 이미지로 된 공고 본문 — 원본 파일을 받아서 자름
                try:
                    res = pg.request.get(u, timeout=30000)
                    if res.ok:
                        tiles += images_from_image(res.body())
                except Exception as e:
                    print(f"  [공고문] 페이지 이미지 받기 실패: {str(e)[:60]}")
                if len(tiles) >= MAX_TILES:
                    tiles = tiles[:MAX_TILES]
                    break
            if tiles:
                return (text[:3000] if text else ""), tiles, f"기업 채용 페이지 이미지 {len(tiles)}조각 ({url})"
            return "", [], f"기업 채용 페이지에 읽을 내용 없음 (글자 {len(text)}자)"
        except Exception as e:
            return "", [], f"기업 채용 페이지 열기 실패: {str(e)[:80]}"
        finally:
            b.close()


def get_notice(job):
    """반환: (텍스트, 이미지조각목록, 파일명 또는 실패사유)
    글자를 뽑을 수 있으면 텍스트, 글자 없는 PDF(포스터·스캔)·이미지 공고문이면 이미지 조각
    [2026-10-08] 알리오 + 클린아이·나라일터(상세페이지 첨부) + 공채속보(기업 채용 페이지)"""
    sn, src = str(job["recrutPblntSn"]), job.get("_source", "alio")
    if job.get("_manual") or sn.startswith("MN-"):
        return "", [], "수동 공고는 보강 안 함"
    if src == "work24" or sn.startswith("WK-"):
        return page_material(job.get("srcUrl", ""))
    if src == "cleaneye" or sn.startswith("CE-"):
        files = cleaneye_notice_files(sn)
    elif src == "gojobs" or sn.startswith("GJ-"):
        files = gojobs_notice_files(sn)
    else:
        files = [(name, lambda u=url: http_get(u)[0]) for url, name in alio_notice_files(sn)]
    if not files:
        return "", [], "공고문 첨부 없음"
    files.sort(key=lambda f: _file_rank(f[0], job.get("recrutPbancTtl", "")))
    image_pdf = image_file = None
    for name, fetch in files:
        if any(w in name.replace(" ", "") for w in FORM_WORDS) and "공고" not in name:
            continue                                       # 제출 서식은 읽지 않음
        try:
            data = fetch()
            if is_image_file(name, data):                  # [2026-10-08] 이미지 공고문은 아래에서 조각내서 읽음
                if image_file is None:
                    image_file = (name, data)
                if "공고" in name:
                    break
                continue
            text = _clean(text_from_file(name, data))
        except Exception as e:
            print(f"  [공고문] {name} 읽기 실패: {e}")
            continue
        if len(text) >= 500:
            return text[:MAX_DOC_CHARS], [], name
        if data[:4] == b"%PDF" and image_pdf is None:
            image_pdf = (name, data)
            if "공고" in name:
                break                                      # 공고문이 글자 없는 PDF면 직무기술서보다 공고문 이미지를 읽음
    if image_file and not image_pdf:
        try:
            tiles = images_from_image(image_file[1])
            if tiles:
                return "", tiles, f"{image_file[0]} (이미지 공고문 → {len(tiles)}조각)"
        except Exception as e:
            print(f"  [공고문] 이미지 읽기 실패: {e}")
    if image_pdf:
        try:
            tiles = images_from_pdf(image_pdf[1])
            if tiles:
                return "", tiles, f"{image_pdf[0]} (글자 없는 PDF → 이미지 {len(tiles)}조각)"
        except Exception as e:
            print(f"  [공고문] 이미지 변환 실패: {e}")
    return "", [], f"공고문 텍스트 추출 실패 ({', '.join(n for n, _ in files)})"


# ───────── 2. Claude로 핵심 정보 추출 ─────────
SYSTEM = """너는 한국 채용공고문(공공기관·민간 기업)에서 정보를 뽑아 JSON으로 정리하는 편집자야.
반드시 공고문에 적힌 사실만 쓴다. 공고문에 없으면 null 또는 빈 배열. 추측·일반론·계산 금지.
숫자(인원·점수·문항수·배수)와 날짜는 공고문 그대로. 요일은 공고문에 적혀 있을 때만 붙인다.
JSON 하나만 출력한다. 설명·마크다운 금지."""

SCHEMA = """아래 형식으로 출력해. 해당 정보가 공고문에 없으면 그 항목은 null (steps는 []).

{
 "crew": {                                   // 모집 분야별 인원. 분야가 1개뿐이면 null
   "summary": "대졸수준 64명, 고졸수준 8명, 별정직 4명을 뽑아요.",   // 1문장, 해요체
   "columns": ["사무", "ICT", "기계"],          // 분야(열) 최대 8개. 많으면 공고문의 큰 분류로 묶기
   "rows": [{"label": "대졸(일반)", "values": [10, null, 15]}],   // 행 최대 10개, 값 순서=columns, 없는 칸 null. 총계·합계·소계 행은 넣지 말 것 (코드가 계산)
   "note": "별정직 4명(기술담당원 1, 후생담당원 2, 보건관리원 1) 별도"   // 표에 못 넣은 인원 설명, 없으면 null
 },
 "restriction": "취업지원대상자(보훈) 또는 장애인만 지원할 수 있어요.",   // 공고 전체가 특정 대상만 지원 가능할 때만 1문장 해요체 (보훈·장애 전용, 지역인재 전용, 고졸 전용 등). 일부 분야만 제한이거나 제한 없으면 null
 "steps": [                                  // 전형 순서대로. 중간 발표일은 notice로 단계 사이에 끼움
   {"type": "step", "title": "1단계 — 서류심사", "date": null, "desc": "외국어성적(50점) + 자격증 가점(최대 50점)", "note": "30배수 선발"},
   {"type": "notice", "label": "필기 대상자 발표", "date": "10월 7일(수)"},
   {"type": "step", "title": "2단계 — 필기전형", "date": "10월 18일(일)", "desc": "인성검사 + K-JAT(70문항) + 전공기초(50문항)", "note": "3배수 선발"},
   {"type": "final", "title": "최종 합격자 발표", "date": "12월 11일(금)", "desc": "신체검사·신원조사 후 임용"}
 ],
 "language": {                               // 어학 기준. 요구 없음이 명시돼 있으면 그 사실을, 언급 자체가 없으면 null
   "title": "어학 기준 (대졸수준)",
   "text": "토익 700점 이상(토익스피킹·OPIc 환산 인정), 850점 이상은 만점 처리. 장애·보훈 전형은 면제예요.",
   "highlight": "700점 이상"                   // text 안에 그대로 있는 강조 구절 1개
 },
 "written": {                                // 필기시험. 필기가 없으면 null
   "summary": "필기는 인성검사 + 직무능력평가 + 전공기초로 봐요. 총 120문항이에요.",
   "highlight": "120문항",
   "subjects": [{"name": "직무능력평가(K-JAT)", "count": "70문항", "scope": "의사소통, 수리, 문제해결, 자원관리, 직업윤리", "note": "5문항은 AI 리터러시로 대체", "ncs": true}],
   "callout": {"title": "🤖 신설 항목: AI 리터러시", "text": "..."}   // 올해 새로 바뀐 점이 공고문에 있을 때만, 없으면 null
 }
}

작성 규칙
- desc 40자 이내, note 30자 이내, 단계 title은 "N단계 — 이름" 형식 (마지막은 type final)
- 날짜 형식: "10월 18일(일)" / 기간이면 "11월 2일~4일"
- summary·text·callout.text는 해요체 1~2문장
- 여러 전형(대졸·고졸·별정직)이 있으면 가장 인원이 많은 전형 기준으로 steps·written을 쓰고, 다른 전형 차이는 note에 짧게
- 신입이 아닌 경력직만의 조건은 넣지 않는다
- subjects의 ncs: 공고문이 그 과목을 NCS·직업기초능력·NCS 기반이라고 명시했을 때만 true, 아니면 false.
  과목 이름이 달라도(K-JAT, 직무능력검사 등) 공고문에 NCS 근거가 있으면 true. 인성검사·전공시험은 명시 없으면 false"""


def call_claude(user, model=CLAUDE_MODEL):
    body = json.dumps({"model": model, "max_tokens": 4000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": os.environ["CLAUDE_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and model != FALLBACK_MODEL:
            print(f"  [warn] 모델 {model} 없음 → {FALLBACK_MODEL}")
            return call_claude(user, FALLBACK_MODEL)
        raise RuntimeError(f"Claude API {e.code}: {e.read().decode()[:300]}")
    u = d.get("usage", {})
    pin, pout = PRICE.get(d.get("model", model), PRICE["default"])
    cost = u.get("input_tokens", 0) * pin / 1e6 + u.get("output_tokens", 0) * pout / 1e6
    print(f"  [Claude] 입력 {u.get('input_tokens', 0):,} / 출력 {u.get('output_tokens', 0):,} 토큰 (약 ${cost:.3f})")
    return "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")


def extract(job, doc, tiles=None):
    head = (f"기관: {clean_inst(job['instNm'])}\n공고명: {job['recrutPbancTtl']}\n"
            f"API 모집인원: {job.get('recrutNope')}명 / 고용형태: {job.get('hireTypeNmLst')}\n\n{SCHEMA}\n\n")
    if tiles:
        if doc:
            head += f"<페이지 글자 (참고)>\n{doc}\n</페이지 글자>\n\n"
        user = [{"type": "text", "text": head + f"공고문은 이미지라 위에서 아래 순서로 {len(tiles)}조각으로 잘라 보내. "
                 "조각 경계에서 표가 이어질 수 있고, 위아래가 조금 겹쳐 있으니 중복으로 세지 마. 이미지에서 읽히는 내용만 써."}]
        user += [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": t}} for t in tiles]
    else:
        user = head + f"<공고문>\n{doc}\n</공고문>"
    raw = call_claude(user)
    m = re.search(r"\{.*\}", re.sub(r"```(json)?", "", raw), re.S)
    if not m:
        raise ValueError("JSON 없음")
    data = json.loads(m.group(0))
    # 최소 검증: 쓸 만한 정보가 하나라도 있어야 함
    useful = [k for k in ("crew", "language", "written", "restriction") if data.get(k)]
    if len([s for s in data.get("steps") or [] if s.get("type") != "notice"]) >= 2:
        useful.append("steps")
    if not useful:
        raise ValueError("추출된 정보 없음")
    crew = data.get("crew") or {}
    total = sum(v for x in crew_rows(crew) for v in (x.get("values") or []) if isinstance(v, int))
    if total and job.get("recrutNope") and total != job["recrutNope"]:
        print(f"  [참고] 표 합계 {total}명 ≠ API 모집인원 {job['recrutNope']}명 (별정직·별도 전형일 수 있음)")
    return data, useful


# ───────── 3. 실행 ─────────
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ids = args or [x.strip() for x in re.split(r"[,\s]+", os.environ.get("ENHANCE_IDS", "")) if x.strip()]
    dry = "--dry-run" in sys.argv or os.environ.get("ENHANCE_DRY_RUN") == "true"
    force = "--force" in sys.argv or os.environ.get("ENHANCE_FORCE") == "true"
    if not ids:
        print("보강할 공고번호가 없어요. 예: python enhance_posts.py 304839")
        return

    now = datetime.now(KST)
    jobs = json.load(open(JOBS_FILE, encoding="utf-8"))["result"]
    by_id = {str(j["recrutPblntSn"]): j for j in jobs}
    mapping = json.load(open(MAPPING_FILE, encoding="utf-8"))
    state = json.load(open(STATE_FILE, encoding="utf-8")) if os.path.exists(STATE_FILE) else {}
    token = None
    done = 0

    for sn in ids:
        sn = str(sn)
        print(f"\n[{sn}]")
        post, job = mapping.get(sn), by_id.get(sn)
        if sn.startswith("MN-") or (job or {}).get("_manual") or (post or {}).get("manual"):   # [2026-10-08]
            print("  건너뜀: 수동 공고 글은 보강하지 않아요 (직접 쓴 본문·Claude 작성 본문 보호)"); continue
        if not post:
            print("  건너뜀: hiring03에 발행된 글이 없어요"); continue
        if not job:
            print("  건너뜀: jobs.json에 없는 공고예요 (마감돼서 빠졌을 수 있음)"); continue
        if sn in state and not force:
            print(f"  건너뜀: {state[sn]['at']}에 이미 보강했어요 (--force로 다시 가능)"); continue
        print(f"  {clean_inst(job['instNm'])} | {post.get('url', '')}")
        # [2026-10-08] 발행 때와 같은 상세 보충을 다시 해야 기존 본문 내용(지원 자격 상세·접수 방법 등)이 안 빠짐
        job = dict(job)
        if is_gojobs(job):
            job = enrich_gojobs(job)
            if "_gojobs_contents" not in job:
                print("  건너뜀: 나라일터 상세 보충 실패 (본문이 원래보다 빈약해질 수 있어 수정 안 함)"); continue
        if is_work24(job):
            job = enrich_work24(job)
            if not job.get("_work24"):
                print("  건너뜀: 공채속보 상세 보충 실패 (본문이 원래보다 빈약해질 수 있어 수정 안 함)"); continue
        try:
            doc, tiles, src_name = get_notice(job)
            if not doc and not tiles:
                print(f"  건너뜀: {src_name}"); continue
            print(f"  공고문: {src_name}" + (f" ({len(doc):,}자)" if doc else ""))
            data, useful = extract(job, doc, tiles)
            print(f"  추출: {', '.join(useful)}")
        except Exception as e:
            print(f"  실패: {e}"); continue

        page = build_html(job, job.get("srcUrl", ""), related_jobs(job, jobs, now), enh=data)
        if dry:
            os.makedirs("preview", exist_ok=True)
            open(f"preview/enhanced-{sn}.html", "w", encoding="utf-8").write(page)
            json.dump(data, open(f"preview/enhanced-{sn}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"  [미리보기] preview/enhanced-{sn}.html")
            continue
        if token is None:
            token = access_token()
        res = api("PATCH", f"posts/{post['postId']}", token, {"content": page})
        if not res:
            print("  실패: Blogger 수정 오류"); continue
        state[sn] = {"at": now.strftime("%Y-%m-%d %H:%M"), "url": post.get("url", ""), "source": src_name,
                     "parts": useful, "data": data}
        done += 1
        print(f"  ✅ 보강 완료 → {post.get('url', '')}")
        time.sleep(3)

    if not dry:
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[완료] 이번 {done}개 보강 / 누적 {len(state)}개")


if __name__ == "__main__":
    main()
