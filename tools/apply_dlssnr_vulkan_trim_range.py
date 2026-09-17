from pathlib import Path

HERE = Path(__file__).resolve()
_candidates = [Path.cwd(), HERE.parent]
if len(HERE.parents) >= 3:
    _candidates.append(HERE.parents[2])
ROOT = next((p for p in _candidates if (p / "OptiScaler").is_dir()), None)
if ROOT is None:
    raise RuntimeError("Run this script from the repository root (the directory containing OptiScaler).")

rel = "OptiScaler/dlssnr/DlssNrFeature_Vk.cpp"
path = ROOT / rel
s = path.read_text(encoding="utf-8-sig")
old = "std::clamp(cfg.DlssNrWhitePointTrim.value_or_default(), 0.25f, 10.0f)"
new = "std::clamp(cfg.DlssNrWhitePointTrim.value_or_default(), 0.25f, 50.0f)"
count = s.count(old)
if count != 1:
    raise RuntimeError(f"Vulkan game Trim range: expected exactly one 10x clamp, got {count}")
s = s.replace(old, new, 1)
path.write_text(s, encoding="utf-8", newline="\n")
print("DLSS-NR Vulkan game Trim range extended to 50x")
