"""PostgreSQL 카탈로그를 ERDCloud 스냅샷 JSON으로 바꾼다.

논리명은 COMMENT ON TABLE/COLUMN에서, 물리명·타입·NULL·기본값·FK는 카탈로그에서 가져온다.

    docker exec -i <컨테이너> psql -U postgres -Atq -c "$(python3 scripts/erdcloud_snapshot.py --query)" \
      | python3 scripts/erdcloud_snapshot.py > docs/schema-mvp.erdcloud.json
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

# 테이블 하나가 JSON 한 줄. 생성 순서(oid)대로.
QUERY = r"""
SELECT json_build_object(
  'name', c.relname,
  'comment', obj_description(c.oid, 'pg_class'),
  'pk', (SELECT array_agg(a.attname ORDER BY k.ord)
         FROM pg_constraint p, unnest(p.conkey) WITH ORDINALITY k(attnum, ord)
         JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
         WHERE p.conrelid = c.oid AND p.contype = 'p'),
  'columns', (SELECT json_agg(json_build_object(
                'name', a.attname,
                'type', format_type(a.atttypid, a.atttypmod),
                'notnull', a.attnotnull,
                'default', pg_get_expr(d.adbin, d.adrelid),
                'comment', col_description(c.oid, a.attnum)) ORDER BY a.attnum)
              FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
              WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
  'fks', (SELECT json_agg(json_build_object(
            'cols', (SELECT array_agg(attname ORDER BY array_position(f.conkey, attnum))
                     FROM pg_attribute WHERE attrelid = f.conrelid AND attnum = ANY(f.conkey)),
            'ref_table', f.confrelid::regclass::text,
            'ref_cols', (SELECT array_agg(attname ORDER BY array_position(f.confkey, attnum))
                         FROM pg_attribute WHERE attrelid = f.confrelid AND attnum = ANY(f.confkey))))
          FROM pg_constraint f WHERE f.conrelid = c.oid AND f.contype = 'f'))
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
ORDER BY c.oid;
"""

# 샘플 스냅샷의 다이어그램 ID. 가져올 때 ERDCloud가 현재 다이어그램으로 바꾼다고 보고 그대로 쓴다.
DIAGRAM_ID = "YpQYSpgDtsy95cT3D"

# 화면 배치: 열마다 영역 하나, 위에서 아래로. 없는 테이블은 마지막 열 아래에 붙는다.
COLUMNS = [
    (["users", "sessions", "jobs", "usage_ledger"], "rgba(10, 10, 10, 0.5)"),
    (["courses", "lectures", "recordings", "segments"], "rgba(10, 10, 10, 0.5)"),
    (["notes", "note_blocks", "block_revisions"], "rgba(178, 27, 0, 0.5)"),
    (["conversations", "messages", "note_changes"], "rgba(178, 27, 0, 0.5)"),
    (["concepts", "review_cards", "attempts", "observations"], "rgba(0, 172, 178, 0.5)"),
]
X0, X_STEP, Y0, ROW_H, HEADER_H, GAP = 100, 670, 100, 32, 100, 70

TYPE_NAMES = {"integer": "int", "timestamp with time zone": "timestamptz"}
ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz"   # ERDCloud(Meteor) ID 문자


def make_id(*parts):
    """같은 이름이면 같은 ID. 다시 만들어도 diff가 작다."""
    n = int.from_bytes(hashlib.sha256("/".join(parts).encode()).digest(), "big")
    out = []
    for _ in range(17):
        n, r = divmod(n, len(ID_ALPHABET))
        out.append(ID_ALPHABET[r])
    return "".join(out)


def default_value(expr):
    if expr is None:
        return ""
    return re.sub(r"::[a-z ]+(\[\])?$", "", expr)   # 'active'::text → 'active'


def build(tables):
    placed = {name: (i, color) for i, (names, color) in enumerate(COLUMNS) for name in names}
    entity_id = {t["name"]: make_id(t["name"]) for t in tables}

    def field_id(table, col):
        return make_id(table, col)

    y_next = {i: Y0 for i in range(len(COLUMNS))}
    entities = []
    for t in tables:
        col_index, color = placed.get(t["name"], (len(COLUMNS) - 1, COLUMNS[-1][1]))
        fk_of = {}
        for fk in t["fks"] or []:
            if len(fk["cols"]) == 1:   # ERDCloud 필드 하나에 관계 하나. 복합 FK는 선을 긋지 않는다
                fk_of[fk["cols"][0]] = (fk["ref_table"], fk["ref_cols"][0])

        def field(c):
            ref = fk_of.get(c["name"])
            return {
                "_id": field_id(t["name"], c["name"]),
                "name": c["comment"] or c["name"],
                "pName": c["name"],
                "domain": "",
                "type": TYPE_NAMES.get(c["type"], c["type"]),
                "defaultValue": default_value(c["default"]),
                "isAllowNull": not c["notnull"],
                "comment": "",
                "relEntity": entity_id[ref[0]] if ref else None,
                "relFieldId": field_id(ref[0], ref[1]) if ref else None,
                "relType": "ZERO_OR_ONE_OR_MANY" if ref else None,
            }

        pk = set(t["pk"] or [])
        entities.append({
            "_id": entity_id[t["name"]],
            "_diagramId": DIAGRAM_ID,
            "pName": t["name"],
            "name": t["comment"] or t["name"],
            "position": {"x": X0 + col_index * X_STEP, "y": y_next[col_index]},
            "keys": {"pks": [field(c) for c in t["columns"] if c["name"] in pk], "fks": []},
            "fields": [field(c) for c in t["columns"] if c["name"] not in pk],
            "color": color,
        })
        y_next[col_index] += HEADER_H + ROW_H * len(t["columns"]) + GAP

    assert all(f["relEntity"] in entity_id.values()
               for e in entities for f in e["fields"] if f["relEntity"]), "부모 테이블 없는 관계"
    return {
        "entityData": entities,
        "memoData": [],
        "shapeData": [],
        "connectorData": [],
        "domainData": [],
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "creatorName": "",
        "creatorThumb": "",
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["--query"]:
        print(QUERY)
    else:
        tables = [json.loads(line) for line in sys.stdin if line.strip()]
        json.dump(build(tables), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
