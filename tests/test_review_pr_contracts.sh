#!/bin/bash
# review-pr skill の手順書契約を固定する検査
#
# 実行: bash tests/test_review_pr_contracts.sh
#
# 手順書は実行されないので、壊れても誰も気付かない。レビューで見つかった
# 「書いてあるが動かない」箇所を静的に固定し、復活を検知する:
#   1. fix-stable 収束判定は RESOLVED_KEYS (前巡まで) と比較し、本巡分の追加は判定の後
#   2. legacy 用プロンプト (Reviewer / Fact-checker) の本文が references に実在する
#   3. --depth の値検証と未知フラグの中断がある
#   4. BROWSER_TEST_DONE / convergence_key が未定義の記号 (... / category / evidence) を使わない
#   5. review-only の BEHIND は compare API のみ (local fetch + rev-list を使わない)
#   6. silent-reject の agreement==1 条件は legacy 限定と明記されている

set -u

# ROOT は tests/ の他の検査と同じく --git-common-dir から導出する = worktree から実行しても
# **メイン checkout の手順書** を検査する (ブランチの手順書を検査したいときはメインで checkout する)
ROOT="$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
if [ -n "$ROOT" ]; then ROOT="$(dirname "$ROOT")"; else ROOT="$(cd "$(dirname "$0")/.." && pwd)"; fi
SKILL="$ROOT/skills/global/review-pr/SKILL.md"
PROMPTS="$ROOT/skills/global/review-pr/references/reviewer-prompts.md"
FIX_STEPS="$ROOT/skills/global/review-pr/references/fix-steps.md"

FAIL=0
pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAIL=1; }

# 1. 収束判定の順序: Step 6 内で「new_defect_keys ... - RESOLVED_KEYS」の行が
#    「RESOLVED_KEYS |= FIXED_KEYS_THIS_ROUND」より前にあり、fix-steps は RESOLVED_KEYS に直接足さない
CMP_LINE=$(grep -n '} - RESOLVED_KEYS' "$SKILL" | head -1 | cut -d: -f1)
# 「本巡分の追加は判定の後」= 追加行の **全出現** が判定行より後 (先頭出現で判定)
ADD_FIRST=$(grep -n 'RESOLVED_KEYS |= FIXED_KEYS_THIS_ROUND' "$SKILL" | head -1 | cut -d: -f1)
ADD_COUNT=$(grep -c 'RESOLVED_KEYS |= FIXED_KEYS_THIS_ROUND' "$SKILL")
if [ -n "$CMP_LINE" ] && [ -n "$ADD_FIRST" ] && [ "$CMP_LINE" -lt "$ADD_FIRST" ]; then
    pass "収束判定 (行 $CMP_LINE) が本巡分の RESOLVED_KEYS 追加 (先頭 行 $ADD_FIRST、$ADD_COUNT 箇所) より前にある"
else
    fail "収束判定と RESOLVED_KEYS 追加の順序が崩れている (cmp=$CMP_LINE add_first=$ADD_FIRST)"
fi
# fix-steps Step 4 節を抜き出し、「足さない」と書いた行以外で RESOLVED_KEYS に足す記述が無いこと
STEP4=$(awk '/^## Step 4: 修正実行/{f=1} /^## Step 4\.5/{f=0} f' "$FIX_STEPS")
if echo "$STEP4" | grep -q 'FIXED_KEYS_THIS_ROUND` に集める' \
   && echo "$STEP4" | grep -q 'RESOLVED_KEYS` にはここでは足さない' \
   && ! echo "$STEP4" | grep -v '足さない' | grep -qE 'RESOLVED_KEYS`? *(に追加|に足す|\|=)'; then
    pass "fix-steps Step 4 は FIXED_KEYS_THIS_ROUND に集め、RESOLVED_KEYS には直接足さない"
else
    fail "fix-steps Step 4 が RESOLVED_KEYS に直接足している (または「足さない」の明記が無い)"
fi
if grep -q 'if MODE == "fix" and iteration >= 2:' "$SKILL"; then
    pass "収束判定は 2 巡目以降のみ"
else
    fail "収束判定の巡条件が iteration >= 2 でない"
fi

# 2. legacy プロンプト本文: 見出しの後にコードフェンスがあり、本文が 10 行以上ある
body_lines() {  # $1=file $2=見出しの接頭辞
    awk -v h="$2" '
        index($0, h)==1 {f=1; next}
        f && /^```/ {fence=!fence; next}
        f && fence {n++; next}
        f && /^## / {exit}
        END {print n+0}' "$1"
}
for h in "## LEGACY_REVIEWER_PROMPT" "## LEGACY_FACTCHECK_PROMPT"; do
    n=$(body_lines "$PROMPTS" "$h")
    if [ "$n" -ge 10 ]; then pass "$h の本文が $n 行ある"; else fail "$h の本文が無いか短い ($n 行)"; fi
done
if grep -q 'LEGACY_FACTCHECK_PROMPT' "$SKILL"; then
    pass "SKILL.md が legacy Fact-checker を LEGACY_FACTCHECK_PROMPT で参照している"
else
    fail "SKILL.md が legacy Fact-checker プロンプトを参照していない"
fi
if grep -q '旧 FACTCHECK_PROMPT' "$SKILL"; then fail "削除済みの旧 FACTCHECK_PROMPT への参照が残っている"; else pass "旧 FACTCHECK_PROMPT への参照が無い"; fi

# 3. --depth 検証と未知フラグ
grep -q 'if tok not in ("lightweight", "full"):' "$SKILL" && pass "--depth の値を検証している" || fail "--depth の値検証が無い"
grep -q 'elif tok starts with "-":' "$SKILL" && pass "未知の - 始まりフラグで中断する" || fail "未知フラグの中断が無い"
grep -q 'モードフラグが重複しています' "$SKILL" && grep -q 'PR 番号が複数あります' "$SKILL" && pass "フラグ / PR 番号の重複で中断する" || fail "重複指定の中断が無い"
grep -q '\-\-depth に値がありません' "$SKILL" && pass "--depth の値なしで中断する" || fail "--depth 値なしの中断が無い"

# 4. 未定義記号 (否定形は対象消失で緑になるので、肯定形と対にする)
if grep -qF "BROWSER_TEST_DONE = (grep -qF '## ブラウザテスト'" "$SKILL" && ! grep -q 'BROWSER_TEST_DONE = \.\.\.' "$SKILL"; then
    pass "BROWSER_TEST_DONE に grep の判定式がある"
else
    fail "BROWSER_TEST_DONE の判定式が無いか未定義 (...) のまま"
fi
if grep -q 'file + kind + normalize(content)' "$SKILL" && ! grep -q 'category + normalize(evidence)' "$SKILL"; then
    pass "convergence_key は実在フィールド (file + kind + content) で定義"
else
    fail "convergence_key の定義が無いかパース結果に無いフィールドを使っている"
fi
grep -qE '(^|[^_A-Z])REVIEWER_PROMPT 末尾' "$SKILL" && fail "廃止した REVIEWER_PROMPT 変数への言及が残っている" || pass "REVIEWER_PROMPT 変数への言及が無い (LEGACY_REVIEWER_PROMPT は対象外)"
grep -q 'f\.classification' "$SKILL" && ! grep -q '`classification` フィールド' "$SKILL" && fail "classification フィールドの定義が無い" || pass "classification フィールドが定義されている (または未使用)"

# 5. review-only BEHIND: compare API の肯定形 + local rev-list の否定形
if grep -qF 'compare/$BASE...$HEAD_REF" -q .behind_by' "$SKILL" && ! grep -q 'git rev-list --count "origin/\$HEAD_REF..origin/\$BASE"' "$SKILL"; then
    pass "review-only の BEHIND は compare API のみ"
else
    fail "review-only の BEHIND が compare API でないか local rev-list が戻っている"
fi

# 6. silent-reject の agreement==1 条件
grep -q 'legacy (Reviewer A/B) のみ\*\*: `agreement == 1`' "$SKILL" && pass "agreement==1 の silent-reject は legacy 限定" || fail "agreement==1 の silent-reject 条件が legacy 限定になっていない"

echo "==================================="
if [ "$FAIL" -eq 0 ]; then echo "ALL TESTS PASSED"; exit 0; else echo "SOME TESTS FAILED"; exit 1; fi
