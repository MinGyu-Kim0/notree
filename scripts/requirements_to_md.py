"""요구사항 정의서 시트('요구사항 목록' A1:P100의 values API 응답 JSON)를 docs/requirements/*.md로 만든다.

사용: python3 scripts/requirements_to_md.py sheet.json
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "requirements"
SHEET_ID = "1J7mkV8Ujdx-TgMfHclk2F0S-W5Cms609ruvDC8v8WCI"

# 기능(SFR)은 대분류로, 나머지는 ID 접두어로 파일을 나눈다.
SFR_FILES = {
    "강의 학습": ("sfr-lecture.md", "기능: 강의 학습 (녹음·전사·노트 생성)"),
    "학습 노트": ("sfr-notes.md", "기능: 학습 노트"),
    "질의응답": ("sfr-qa.md", "기능: 질의응답"),
    "학습자 상태": ("sfr-learner.md", "기능: 학습자 상태"),
    "개인맞춤 복습": ("sfr-review.md", "기능: 개인맞춤 복습"),
    "계정": ("sfr-account.md", "기능: 계정"),
}
PREFIX_FILES = {
    "DAR": ("data.md", "데이터 요구사항"),
    "SER": ("security.md", "보안 요구사항"),
    "QUR": ("quality.md", "품질 요구사항"),
    "PER": ("performance.md", "성능 요구사항"),
    "SIR": ("interface.md", "인터페이스 요구사항"),
    "COR": ("constraints.md", "제약사항"),
}
COLS = ["id", "kind", "major", "minor", "name", "desc", "accept", "priority",
        "requester", "date", "owner", "status", "related", "note"]


def target(r):
    if r["id"].startswith("SFR-"):
        return SFR_FILES[r["major"]]
    return PREFIX_FILES[r["id"][:3]]


def scope(note):
    m = re.match(r"\[(MVP|후속)\]", note)
    return m.group(1) if m else "-"


def related(r):
    return ", ".join(x.strip() for x in r["related"].replace("\n", "").split(",") if x.strip())


def render(r):
    lines = [
        f"## {r['id']} {r['name']}",
        "",
        f"{r['major']} > {r['minor']} · {r['priority']} · 담당 {r['owner']} · {r['status']}"
        + (f" · 관련 {related(r)}" if related(r) else ""),
        "",
        r["desc"],
        "",
        "**수용 기준**",
        "",
        r["accept"],
    ]
    if r["note"]:
        lines += ["", f"**비고**: {r['note']}"]
    return "\n".join(lines)


def main(path):
    values = json.loads(Path(path).read_text(encoding="utf-8"))["values"]
    version = values[1][0] if len(values) > 1 and values[1] else ""
    rows = [dict(zip(COLS, v + [""] * (len(COLS) - len(v)))) for v in values[4:] if v and v[0]]
    assert rows and all(re.fullmatch(r"[A-Z]{3}-\d{3}", r["id"]) for r in rows), "ID 형식이 다른 행이 있다"
    assert len({r["id"] for r in rows}) == len(rows), "중복 ID"

    groups = defaultdict(list)
    for r in rows:
        groups[target(r)].append(r)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    header = f"<!-- 생성 파일: scripts/requirements_to_md.py로 시트에서 만든다. 직접 고치지 말 것. -->\n"
    for (fname, title), rs in groups.items():
        body = "\n\n".join(render(r) for r in rs)
        (OUT / fname).write_text(f"{header}\n# {title}\n\n{body}\n", encoding="utf-8")

    index = [
        header,
        "# 요구사항 정의서",
        "",
        f"원본은 Google Sheet `{SHEET_ID}`의 '요구사항 목록' 시트다. {version}",
        "",
        "- 이 폴더는 시트에서 생성한 읽기용 사본이다. 요구사항을 바꿀 때는 시트를 고치고 다시 생성한다.",
        "- 이 색인으로 필요한 ID를 찾은 뒤 해당 파일만 연다. 한 파일에 같은 영역의 요구사항이 모여 있다.",
        "- 비고의 [MVP]/[후속]은 출시 범위, '초기값'은 측정 전 정책 기준이다. '변경 제안(승인 대기)'는 미반영이다.",
        "- 요청자(전부 김민규 / 1조)와 요청일 열은 생략했다.",
        "",
        "| ID | 요구사항명 | 우선순위 | 범위 | 담당 | 파일 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        f = target(r)[0]
        index.append(f"| {r['id']} | {r['name']} | {r['priority']} | {scope(r['note'])} | {r['owner']} | [{f}]({f}) |")
    (OUT / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{len(rows)}건 → {len(groups)}개 파일 + README.md")


if __name__ == "__main__":
    main(sys.argv[1])
