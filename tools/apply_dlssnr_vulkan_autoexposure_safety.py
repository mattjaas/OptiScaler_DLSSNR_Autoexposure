from pathlib import Path

HERE = Path(__file__).resolve()
_candidates = [Path.cwd(), HERE.parent]
if len(HERE.parents) >= 3:
    _candidates.append(HERE.parents[2])
ROOT = next((p for p in _candidates if (p / "OptiScaler").is_dir()), None)
if ROOT is None:
    raise RuntimeError("Run this script from the repository root (the directory containing OptiScaler).")


def replace_once(path, old, new, label):
    s = path.read_text(encoding="utf-8-sig")
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    path.write_text(s.replace(old, new, 1), encoding="utf-8", newline="\n")


# Automatic exposure adds two extra compute dispatches before Encode. Give the Vulkan descriptor/
# constant ring explicit headroom for auto meter + reduce + encode + resolve + optional debug passes.
replace_once(
    ROOT / "OptiScaler/shaders/dlssnr/DlssNr_Vk.h",
    "    static constexpr uint32_t kSlotsPerFrame = 6;\n",
    "    static constexpr uint32_t kSlotsPerFrame = 8;\n",
    "Vulkan compute slot headroom",
)

# Preserve the existing Vulkan behaviour for the game's ExposureTexture. Only the OptiScaler-owned
# automatic-exposure image is newly handed to the NR model; this avoids changing ownership/layout
# assumptions for a foreign game image as a side effect of adding automatic exposure.
replace_once(
    ROOT / "OptiScaler/dlssnr/DlssNrFeature_Vk.cpp",
    "    NVSDK_NGX_Resource_VK* modelExposure = nullptr;\n"
    "    if (usingAutoExposure)\n"
    "        modelExposure = &g_vk.autoExposure.ngx;\n"
    "    else if (requestedWhitePointSource == 1 && exposure != nullptr)\n"
    "        modelExposure = exposure;\n",
    "    NVSDK_NGX_Resource_VK* modelExposure = usingAutoExposure ? &g_vk.autoExposure.ngx : nullptr;\n",
    "Vulkan automatic-only model exposure",
)

print("DLSS-NR Vulkan automatic exposure safety adjustments applied")
