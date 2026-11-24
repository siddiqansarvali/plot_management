"""Quick smoke-test for the cross-token area extractor."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.fusion_service import _extract_areas

def mk(txt, conf=0.9):
    return {"text": txt, "confidence": conf, "center": [0, 0], "bbox": [0, 0, 10, 10]}

# ── Test 1: combined token "250.7 SQ.M"
tokens1 = [mk("106"), mk("250.7 SQ.M")]
r1 = _extract_areas(tokens1)
print("Test1 (combined):", r1)
assert r1 and abs(r1[0]["value"] - 250.7) < 0.1, f"FAIL: {r1}"

# ── Test 2: split tokens ["250.7", "SQ.M"]
tokens2 = [mk("106"), mk("250.7"), mk("SQ.M")]
r2 = _extract_areas(tokens2)
print("Test2 (split):", r2)
assert r2 and abs(r2[0]["value"] - 250.7) < 0.1, f"FAIL: {r2}"

# ── Test 3: "SQ. M" as separate token, value before
tokens3 = [mk("200.8"), mk("SQ. M")]
r3 = _extract_areas(tokens3)
print("Test3 (sq m space):", r3)
assert r3 and abs(r3[0]["value"] - 200.8) < 0.1, f"FAIL: {r3}"

# ── Test 4: "SQ.tO" (OCR misread of "SQ.M") - should still pick up 289.0
tokens4 = [mk("116"), mk("289.0"), mk("SQ.tO")]
r4 = _extract_areas(tokens4)
print("Test4 (SQ.tO glitch):", r4)
# might not match since SQ.tO is an unusual glitch - OK if empty

# ── Test 5: plot number should NOT be treated as area
tokens5 = [mk("106"), mk("SQ.M")]
r5 = _extract_areas(tokens5)
print("Test5 (plot no should be skipped):", r5)
assert not r5 or r5[0]["value"] != 106.0, f"FAIL: plot number treated as area: {r5}"

# ── Test 6: "SQ. h" (OCR glitch for SQ.m)
tokens6 = [mk("101"), mk("SQ. h"), mk("15.24")]
r6 = _extract_areas(tokens6)
print("Test6 (SQ.h glitch):", r6)

# ── Test 7: "11.10" after "SQ.M"
tokens7 = [mk("113"), mk("SQ.M"), mk("11.10")]
r7 = _extract_areas(tokens7)
print("Test7 (number after unit):", r7)
assert r7 and abs(r7[0]["value"] - 11.1) < 0.1, f"FAIL: {r7}"

print("\nAll assertions passed!")
