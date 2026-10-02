"""DART 사업보고서 → 기업별 직원 평균 연봉·평균 근속연수 → dart_salary.json
─────────────────────────────────────────────
DART는 해외 IP를 막기 때문에 GitHub Actions가 아니라 내 PC(한국)에서 1년에 1번 실행한다.
(사업보고서는 매년 3월 말까지 제출 → 4월 이후 실행 권장)

실행:  python dart_salary.py
       → 인증키 입력 → 몇 분 뒤 dart_salary.json 생성 → 저장소에 업로드

대상: ① 상장사 전체  ② jobs.json(공채속보) 회사 중 DART에 있는 비상장사
값:   직원 1인 평균 급여(만원) · 평균 근속연수(년) · 기준 연도
원칙: 숫자가 이상하면(2,000만원 미만 / 3억 초과) 버린다 — 틀린 연봉보다 없는 게 낫다
"""
import io, json, os, re, sys, time, zipfile, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

API = "https://opendart.fss.or.kr/api"
OUT = "dart_salary.json"
JOBS_URL = "https://teukgasniper.github.io/job-compass/jobs.json"
SLEEP = 0.15            # 분당 1,000회 제한 여유 있게


# ───────── 회사명 정규화 (공채속보 한글 표기 ↔ DART 영문 표기) ─────────
LATIN = [  # 긴 것부터 바꾼다
    ("에이치에스", "HS"), ("엔에이치엔", "NHN"), ("에이치디", "HD"), ("에이치엘", "HL"),
    ("에이치엠엠", "HMM"), ("에스케이", "SK"), ("엘지", "LG"), ("씨제이", "CJ"), ("디비", "DB"),
    ("엔에이치", "NH"), ("지에스", "GS"), ("엘에스", "LS"), ("케이티", "KT"), ("케이비", "KB"),
    ("케이씨", "KC"), ("케이지", "KG"), ("비지에프", "BGF"), ("에스엠", "SM"), ("에스디", "SD"),
    ("오씨아이", "OCI"), ("에쓰오일", "S-OIL"), ("제이티", "JT"), ("이랜드", "이랜드"),
]

def norm(name):
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\s", "", name or "")
    return n.upper()

def latin(name):
    n = norm(name)
    for ko, en in LATIN:
        if n.startswith(ko):
            return en + n[len(ko):]
    return n


# ───────── HTTP ─────────
def get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data.decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3)


# ───────── 숫자 해석 ─────────
def num(v):
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None

def to_manwon(v):
    """1인 평균 급여 → 만원. 회사마다 원/천원/백만원 단위가 섞여 있어서 크기로 판단"""
    x = num(v)
    if not x or x <= 0:
        return None
    if x >= 1e7:            # 원  (예: 98,000,000)
        won = x
    elif x >= 1e4:          # 천원 (예: 98,000)
        won = x * 1e3
    else:                   # 백만원 (예: 98)
        won = x * 1e6
    m = round(won / 1e4)
    return m if 2000 <= m <= 30000 else None

def to_years(v):
    s = str(v or "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*년\s*(?:(\d+)\s*개?월)?", s)
    if m:
        return round(float(m.group(1)) + (int(m.group(2)) / 12 if m.group(2) else 0), 1)
    x = num(s)
    return round(x, 1) if x and 0 < x < 50 else None


def emp_status(key, corp_code):
    """사업보고서 직원현황 → (평균급여 만원, 평균근속 년, 연도). 최근 연도부터 시도"""
    this_year = datetime.now().year
    for year in (this_year - 1, this_year - 2):
        q = urllib.parse.urlencode({"crtfc_key": key, "corp_code": corp_code,
                                    "bsns_year": year, "reprt_code": "11011"})
        d = get(f"{API}/empSttus.json?{q}")
        time.sleep(SLEEP)
        st = d.get("status")
        if st == "020":
            sys.exit("[중단] 일일 조회 한도 초과 — 내일 다시 실행하세요.")
        if st != "000" or not d.get("list"):
            continue
        rows = d["list"]
        total = [r for r in rows if "합계" in (r.get("sexdstn") or "") or "합계" in (r.get("fo_bbm") or "")]
        if total:
            sal = to_manwon(total[0].get("jan_salary_am"))
            ten = to_years(total[0].get("avrg_cnwk_sdytrn"))
        else:   # 성별·부문별로만 나오면 인원 가중 평균
            pairs = [(to_manwon(r.get("jan_salary_am")), num(r.get("sm")), to_years(r.get("avrg_cnwk_sdytrn")))
                     for r in rows]
            pairs = [p for p in pairs if p[0] and p[1]]
            if not pairs:
                continue
            people = sum(p[1] for p in pairs)
            sal = round(sum(p[0] * p[1] for p in pairs) / people)
            tens = [(p[2], p[1]) for p in pairs if p[2]]
            ten = round(sum(t * w for t, w in tens) / sum(w for _, w in tens), 1) if tens else None
        if sal:
            return sal, ten, year
    return None, None, None


def main():
    key = os.environ.get("DART_API_KEY") or input("DART 인증키 입력: ").strip()

    print("[1/4] 회사 고유번호 목록 내려받는 중...")
    z = zipfile.ZipFile(io.BytesIO(get(f"{API}/corpCode.xml?crtfc_key={key}", binary=True)))
    root = ET.fromstring(z.read(z.namelist()[0]))
    corps = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall("list")]
    print(f"      전체 {len(corps):,}개 회사")

    # 같은 이름이 여러 개면 상장사 > 최근 수정 순으로 1개만
    by_name = {}
    for c in corps:
        k = norm(c["corp_name"])
        old = by_name.get(k)
        if (not old or (c.get("stock_code") and not old.get("stock_code"))
                or (bool(c.get("stock_code")) == bool(old.get("stock_code")) and c.get("modify_date", "") > old.get("modify_date", ""))):
            by_name[k] = c

    print("[2/4] 대상 회사 고르는 중...")
    targets = {c["corp_code"]: c for c in by_name.values() if c.get("stock_code")}   # 상장사 전체
    try:
        jobs = get(JOBS_URL).get("result", [])
        names = {j["instNm"] for j in jobs if j.get("_source") == "work24"}
    except Exception:
        names = set()
    # 공채속보가 아직 jobs.json에 없을 때: 같은 폴더의 gongchae_companies.txt(회사명 한 줄씩) 사용
    if os.path.exists("gongchae_companies.txt"):
        with open("gongchae_companies.txt", encoding="utf-8") as f:
            names |= {l.strip() for l in f if l.strip()}
    matched = 0
    for n in names:
        c = by_name.get(norm(n)) or by_name.get(latin(n))
        if c:
            targets[c["corp_code"]] = c
            matched += 1
    print(f"      상장사 {sum(1 for c in targets.values() if c.get('stock_code')):,}개 + 공채속보 회사 {matched}/{len(names)}개 매칭")

    print(f"[3/4] 직원현황 조회 중... (약 {len(targets) * 2 * SLEEP / 60:.0f}~{len(targets) * 3 * SLEEP / 60:.0f}분)")
    # 이전 실행 결과가 있으면 이어서 (이미 연봉을 받은 회사는 다시 조회하지 않음)
    out = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                out = json.load(f).get("companies", {})
            print(f"      이전 결과 {len(out):,}개 불러옴 → 나머지만 조회")
        except Exception:
            out = {}
    todo = [c for c in targets.values() if norm(c["corp_name"]) not in out]
    if len(todo) < len(targets):
        print(f"      조회할 회사 {len(todo):,}개")
    for i, c in enumerate(todo, 1):
        try:
            sal, ten, year = emp_status(key, c["corp_code"])
        except SystemExit:
            raise
        except Exception as e:
            print(f"      {c['corp_name']} 실패: {e}")
            continue
        if sal:
            out[norm(c["corp_name"])] = {"name": c["corp_name"], "avg": sal, "tenure": ten, "year": year,
                                         "listed": bool(c.get("stock_code"))}
        if i % 200 == 0:
            print(f"      {i:,}/{len(todo):,} 진행 · 연봉 확보 {len(out):,}개")

    print("[4/4] 저장 중...")
    data = {"_meta": {"source": "DART 사업보고서 직원현황", "updated": datetime.now().strftime("%Y-%m-%d"),
                      "count": len(out)}, "companies": out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    hit = [n for n in names if norm(n) in out or latin(n) in out]
    print(f"\n완료: {len(out):,}개 회사 연봉 저장 → {OUT}")
    print(f"지금 공채속보 회사 {len(names)}개 중 연봉 있는 곳: {len(hit)}개")
    for n in sorted(hit)[:30]:
        v = out.get(norm(n)) or out.get(latin(n))
        print(f"  {n} → {v['name']} 평균 {v['avg']:,}만원 · 근속 {v['tenure']}년 ({v['year']})")


if __name__ == "__main__":
    main()
