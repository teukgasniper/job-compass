"""클린아이(지방공기업) 공고 학력 확인 [2026-10-12]
─────────────────────────────────────────────
클린아이 API에는 학력 항목이 없음 → 상세페이지 공고문(PDF·HWP·이미지)을 Sonnet이 읽어 학력 조건만 뽑음
  - 쓰레드 자동발행(publish_to_threads.py): 클린아이 공고를 고르면 발행 직전에 확인 (공고 1건당 약 10~20원)
  - 본문 보강(enhance_posts.py): 보강 때 같이 뽑아서 본문 '학력' 칸을 채움
  - 본문 발행(publish_to_blogger.py): 저장된 값이 있으면 처음부터 채움 (Claude 호출 없음)

저장: threads_state/edu_cache.json  {공고번호: {"label": "학력무관", "text": "...", "open": true, "source": "...", "at": "..."}}
      (확인 실패도 {"label": ""}로 저장해서 같은 공고를 반복해서 읽지 않음 — 7일 뒤 재시도)
"""
import json, os, re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
EDU_CACHE = os.path.join("threads_state", "edu_cache.json")
ENHANCED = "enhanced_posts.json"
RETRY_DAYS = 7

EDU_SYSTEM = """너는 한국 채용공고문에서 '학력 조건'만 찾아 JSON으로 정리하는 편집자야.
반드시 공고문에 적힌 사실만 쓴다. 추측·일반론 금지. JSON 하나만 출력한다."""

EDU_SCHEMA = """공고문에서 신입 지원자 기준 학력 조건을 찾아 아래 형식으로 출력해.

{"label": "학력무관", "text": "학력 제한 없음 (응시자격 1번)", "open": true}

- label: 카드·표에 넣을 짧은 값. 아래 중 하나 그대로:
  "학력무관" / "고졸 이상" / "전문대졸 이상" / "대졸 이상" / "석사 이상" / "박사" / "면허·자격 필수"
  · 학력 제한 없음·학력 무관·블라인드라 학력 미기재가 '명시'돼 있으면 "학력무관"
  · 학력 대신 간호사 면허·자격증 등이 필수 조건이면 "면허·자격 필수"
  · 분야마다 다르면 가장 인원이 많은 분야 기준
  · [중요] 정규직·무기계약직과 계약직·기간제를 같이 뽑는 공고면 반드시 정규직·무기계약직 분야의 학력 조건만 쓸 것.
    공고문에 계약직·기간제 분야 요건만 있고 정규직 분야 학력이 안 보이면 null
  · 위 '고용형태'에 맞는 분야 기준으로 쓸 것
- text: 공고문 근거를 40자 이내로 (예: "학력·연령·성별 제한 없음", "간호사 면허 소지자")
- open: label이 "학력무관"일 때만 true
- 공고문에서 학력 조건을 찾을 수 없으면 {"label": null, "text": null, "open": false}"""

LABELS = ("학력무관", "고졸 이상", "전문대졸 이상", "대졸 이상", "석사 이상", "박사", "면허·자격 필수")


def is_cleaneye(job: dict) -> bool:
    return job.get("_source") == "cleaneye" or str(job.get("recrutPblntSn", "")).startswith("CE-")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_cache() -> dict:
    return _load(EDU_CACHE)


def save_cache(cache: dict):
    os.makedirs(os.path.dirname(EDU_CACHE), exist_ok=True)
    with open(EDU_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def cached_edu(sn) -> dict:
    """저장된 학력 (쓰레드 확인값 → 본문 보강값 순). 없으면 {}"""
    sn = str(sn)
    hit = load_cache().get(sn) or {}
    if hit.get("label") and not _wrong_track(hit.get("text")):   # 계약직 요건으로 저장된 옛 값은 무시 → 다시 확인
        return hit
    enh = ((_load(ENHANCED).get(sn) or {}).get("data") or {}).get("edu") or {}
    if enh.get("label") in LABELS and not _wrong_track(enh.get("text")):
        return {**enh, "source": "본문 보강"}
    return {}


def apply_edu(job: dict) -> dict:
    """학력 칸이 빈 클린아이 공고에 저장된 학력을 채워서 돌려줌 (원본은 안 바꿈, Claude 호출 없음)"""
    if not is_cleaneye(job) or (job.get("acbgCondNmLst") or "").strip():
        return job
    e = cached_edu(job["recrutPblntSn"])
    if not e:
        return job
    job = dict(job)
    job["acbgCondNmLst"] = e["label"]
    job["_edu_text"] = e.get("text") or ""
    return job


def _wrong_track(text: str) -> bool:
    """[2026-10-12] 계약직·기간제 분야 요건을 가져온 경우 (예: 경북테크노파크 '(계약직 자격요건)') — 쓰지 않고 다시 확인"""
    return bool(re.search(r"(?<!무기)계약직|기간제|단시간|대체인력", text or ""))


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", re.sub(r"```(json)?", "", raw or ""), re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {}
    label = (d.get("label") or "").strip()
    if label not in LABELS or _wrong_track(d.get("text")):
        return {}
    return {"label": label, "text": (d.get("text") or "").strip()[:60], "open": label == "학력무관"}


def lookup_edu(job: dict, save: bool = True) -> dict:
    """공고문을 Sonnet으로 읽어 학력 확인 (저장값 있으면 그대로). 실패하면 {}"""
    sn = str(job["recrutPblntSn"])
    hit = cached_edu(sn)
    if hit:
        return hit
    cache = load_cache()
    old = cache.get(sn) or {}
    if old and not old.get("label"):                       # 최근에 못 찾은 공고는 7일 동안 다시 안 읽음
        try:
            if datetime.now(KST) - datetime.strptime(old["at"], "%Y-%m-%d %H:%M").replace(tzinfo=KST) < timedelta(days=RETRY_DAYS):
                return {}
        except Exception:
            pass
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    result, src, failed = {}, "", False
    try:
        import enhance_posts as ep                          # 공고문 내려받기·읽기는 본문 보강과 같은 코드 사용
        doc, tiles, src = ep.get_notice(job)
        if doc or tiles:
            head = (f"기관: {job.get('instNm')}\n공고명: {job.get('recrutPbancTtl')}\n"
                    f"고용형태: {job.get('hireTypeNmLst')} / 신입·경력: {job.get('recrutSeNm')}\n\n{EDU_SCHEMA}\n\n")
            if tiles:
                user = [{"type": "text", "text": head + f"공고문은 이미지라 {len(tiles)}조각으로 보내. 이미지에서 읽히는 내용만 써."}]
                user += [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": t}} for t in tiles]
            else:
                user = head + f"<공고문>\n{doc[:40000]}\n</공고문>"
            saved = ep.SYSTEM
            try:
                ep.SYSTEM = EDU_SYSTEM
                result = _parse(ep.call_claude(user))
            finally:
                ep.SYSTEM = saved
    except Exception as e:                                  # 접속 오류·API 오류 = 일시적 실패 → 저장 안 하고 다음 회차에 다시
        failed = True
        print(f"  [학력 확인] 실패: {e}")
    print(f"  [학력 확인] {job.get('instNm')} → {result.get('label') or '확인 안 됨'}"
          + (f" ({result.get('text')})" if result.get("text") else "") + (f" / {src}" if src else ""))
    if save and not failed:                                 # 정상적으로 읽었는데 못 찾은 경우만 '못 찾음'으로 저장 (7일 뒤 재시도)
        cache[sn] = {**(result or {"label": ""}), "source": src, "at": now}
        save_cache(cache)
    return result
