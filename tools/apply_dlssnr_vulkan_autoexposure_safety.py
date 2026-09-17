from pathlib import Path
import re

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

# The main Vulkan patch runs after the generic menu/anchor patches. Keep the Vulkan status selection
# local to each Trim block and rewrite both calls to the final five-argument Base White Point form.
# This deliberately runs last so later release-time patch ordering cannot leave an out-of-scope `vk`
# variable or accidentally drop the slider Trim argument.
menu_path = ROOT / "OptiScaler/dlssnr/DlssNr_Menu.cpp"
menu = menu_path.read_text(encoding="utf-8-sig")

old_game_status = (
    "            const auto gameStatus = vk ? DlssNr::GameExposureStatusVk() : DlssNr::GameExposureStatus();\n"
)
new_game_status = (
    "            const auto gameStatus = DlssNr::IsRunningVk() ? DlssNr::GameExposureStatusVk()\n"
    "                                                            : DlssNr::GameExposureStatus();\n"
)
if menu.count(old_game_status) != 1:
    raise RuntimeError(f"Vulkan game menu status: expected exactly one match, got {menu.count(old_game_status)}")
menu = menu.replace(old_game_status, new_game_status, 1)

old_auto_status = (
    "            const auto autoStatus = vk ? DlssNr::AutoExposureStatusVk() : DlssNr::AutoExposureStatus();\n"
)
new_auto_status = (
    "            const auto autoStatus = DlssNr::IsRunningVk() ? DlssNr::AutoExposureStatusVk()\n"
    "                                                            : DlssNr::AutoExposureStatus();\n"
)
if menu.count(old_auto_status) != 1:
    raise RuntimeError(f"Vulkan auto menu status: expected exactly one match, got {menu.count(old_auto_status)}")
menu = menu.replace(old_auto_status, new_auto_status, 1)

game_pattern = re.compile(
    r"            RenderExposureTrimAnchorControls\(config->DlssNrGameExposureTrimAnchors,\n"
    r"[\s\S]*?\"gameExposureTrim\"\);\n"
)
game_replacement = (
    "            RenderExposureTrimAnchorControls(config->DlssNrGameExposureTrimAnchors,\n"
    "                                             config->DlssNrGameExposureTrimPreview,\n"
    "                                             gameStatus.exposure > 1e-8f\n"
    "                                                 ? gameStatus.preExposure / gameStatus.exposure\n"
    "                                                 : 0.0f,\n"
    "                                             gameTrim, \"gameExposureTrim\");\n"
)
menu, game_count = game_pattern.subn(game_replacement, menu, count=1)
if game_count != 1:
    raise RuntimeError(f"Vulkan game anchor controls: expected exactly one match, got {game_count}")

auto_pattern = re.compile(
    r"            RenderExposureTrimAnchorControls\(config->DlssNrAutoExposureTrimAnchors,\n"
    r"[\s\S]*?\"automaticExposureTrim\"\);\n"
)
auto_replacement = (
    "            RenderExposureTrimAnchorControls(config->DlssNrAutoExposureTrimAnchors,\n"
    "                                             config->DlssNrAutoExposureTrimPreview,\n"
    "                                             autoStatus.exposure > 1e-8f\n"
    "                                                 ? autoStatus.preExposure / autoStatus.exposure\n"
    "                                                 : 0.0f,\n"
    "                                             autoTrim, \"automaticExposureTrim\");\n"
)
menu, auto_count = auto_pattern.subn(auto_replacement, menu, count=1)
if auto_count != 1:
    raise RuntimeError(f"Vulkan automatic anchor controls: expected exactly one match, got {auto_count}")

# Tooltip text is matched by the unique HelpMarker prefix rather than by the full old wording.
# Earlier release-time patches may legitimately reflow or update the body while leaving the control
# unchanged, so exact whole-block matching is unnecessarily brittle.
game_help_pattern = re.compile(
    r"            HelpMarker\(\"Multiplier on the white point derived from the game's own ExposureTexture\.\"\n"
    r"[\s\S]*?\);\n"
)
new_game_help = (
    "            HelpMarker(\"Multiplier on the white point derived from the game's own ExposureTexture.\"\n"
    "                       \"\\n\\n1.00x uses the game's value unchanged. Range: 0.25x to 50.00x.\"\n"
    "                       \"\\n\\nTip: Try to set this to the highest value that subjectively looks best. \"\n"
    "                       \"Excessive values will degrade image quality. If you notice differences in how \"\n"
    "                       \"dark and bright scenes appear, you can use anchor points to set different Trim \"\n"
    "                       \"values for each.\"\n"
    "                       \"\\n\\nIf the game does not supply ExposureTexture, the status above reports that \"\n"
    "                       \"this source is unavailable.\");\n"
)
menu, game_help_count = game_help_pattern.subn(lambda _: new_game_help, menu, count=1)
if game_help_count != 1:
    raise RuntimeError(f"game Trim help text: expected exactly one HelpMarker block, got {game_help_count}")

auto_help_pattern = re.compile(
    r"            HelpMarker\(\"OptiScaler calculates exposure itself from the ORIGINAL linear-HDR frame\.?\"\n"
    r"[\s\S]*?\);\n"
)
new_auto_help = (
    "            HelpMarker(\"OptiScaler calculates exposure itself from the ORIGINAL linear-HDR frame.\"\n"
    "                       \"\\nThe game's ExposureTexture is ignored even when present.\"\n"
    "                       \"\\n\\n1.00x uses the calculated value unchanged. Range: 0.25x to 50.00x.\"\n"
    "                       \"\\n\\nTip: Try to set this to the highest value that subjectively looks best. \"\n"
    "                       \"Excessive values will degrade image quality. If you notice differences in how \"\n"
    "                       \"dark and bright scenes appear, you can use anchor points to set different Trim \"\n"
    "                       \"values for each.\");\n"
)
menu, auto_help_count = auto_help_pattern.subn(lambda _: new_auto_help, menu, count=1)
if auto_help_count != 1:
    raise RuntimeError(f"automatic Trim help text: expected exactly one HelpMarker block, got {auto_help_count}")

menu_path.write_text(menu, encoding="utf-8", newline="\n")

print("DLSS-NR Vulkan automatic exposure safety adjustments applied")
