from pathlib import Path

HERE = Path(__file__).resolve()
_candidates = [Path.cwd(), HERE.parent]
if len(HERE.parents) >= 3:
    _candidates.append(HERE.parents[2])
ROOT = next((p for p in _candidates if (p / "OptiScaler").is_dir()), None)
if ROOT is None:
    raise RuntimeError("Run this script from the repository root (the directory containing OptiScaler).")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def write(rel, text):
    (ROOT / rel).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# Runs after the Auto Exposure, Trim-anchor, FXC-compatibility and Base White Point patches.
# The default Automatic exposure meter becomes highlight-protected: it works on the existing
# 64x64 tile means, meters log-luminance, trims the distribution, and increases highlight
# rejection when a small part of the frame sits several stops above the median. A persisted
# emergency checkbox restores the exact simple arithmetic-average meter used previously.

# -----------------------------------------------------------------------------
# Config: persisted emergency fallback switch.
# -----------------------------------------------------------------------------
rel = "OptiScaler/Config.h"
s = read(rel)
s = replace_once(
    s,
    "    CustomOptional<float> DlssNrAutoExposureTrim { 1.0f };\n\n"
    "    // Base-white-point-dependent Trim calibration tables, serialized as baseWhitePoint:trim pairs.\n",
    "    CustomOptional<float> DlssNrAutoExposureTrim { 1.0f };\n"
    "    CustomOptional<bool> DlssNrAutoExposureSimpleAverageFallback { false };\n\n"
    "    // Base-white-point-dependent Trim calibration tables, serialized as baseWhitePoint:trim pairs.\n",
    "auto exposure fallback config field",
)
write(rel, s)

rel = "OptiScaler/Config.cpp"
s = read(rel)
s = replace_once(
    s,
    "            DlssNrAutoExposureTrim.set_from_config(readFloat(\"DlssNr\", \"AutoExposureTrim\"));\n"
    "            DlssNrGameExposureTrimAnchors.set_from_config(readString(\"DlssNr\", \"GameExposureTrimAnchors\"));\n",
    "            DlssNrAutoExposureTrim.set_from_config(readFloat(\"DlssNr\", \"AutoExposureTrim\"));\n"
    "            DlssNrAutoExposureSimpleAverageFallback.set_from_config(\n"
    "                readBool(\"DlssNr\", \"AutoExposureSimpleAverageFallback\"));\n"
    "            DlssNrGameExposureTrimAnchors.set_from_config(readString(\"DlssNr\", \"GameExposureTrimAnchors\"));\n",
    "read auto exposure fallback",
)
s = replace_once(
    s,
    "    ini.SetValue(\"DlssNr\", \"AutoExposureTrim\",\n"
    "                 GetFloatValue(Instance()->DlssNrAutoExposureTrim.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"GameExposureTrimAnchors\",\n",
    "    ini.SetValue(\"DlssNr\", \"AutoExposureTrim\",\n"
    "                 GetFloatValue(Instance()->DlssNrAutoExposureTrim.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"AutoExposureSimpleAverageFallback\",\n"
    "                 GetBoolValue(Instance()->DlssNrAutoExposureSimpleAverageFallback.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"GameExposureTrimAnchors\",\n",
    "write auto exposure fallback",
)
write(rel, s)

# -----------------------------------------------------------------------------
# Menu: emergency fallback checkbox + Trim range 0.25x..50x for game and auto.
# -----------------------------------------------------------------------------
rel = "OptiScaler/dlssnr/DlssNr_Menu.cpp"
s = read(rel)
s = replace_once(
    s,
    "            const auto autoStatus = DlssNr::AutoExposureStatus();\n"
    "            RenderExposureTrimAnchorControls(config->DlssNrAutoExposureTrimAnchors,\n",
    "            bool simpleAverageFallback =\n"
    "                config->DlssNrAutoExposureSimpleAverageFallback.value_or_default();\n"
    "            if (ImGui::Checkbox(\"Calculate the exposure using simple average (emergency fallback)\",\n"
    "                                &simpleAverageFallback))\n"
    "                config->DlssNrAutoExposureSimpleAverageFallback = simpleAverageFallback;\n\n"
    "            HelpMarker(\"Normally Automatic exposure uses highlight-protected log-luminance metering.\"\n"
    "                       \"\\nIt measures the existing 64x64 tile grid, trims the luminance distribution,\"\n"
    "                       \"\\nand suppresses small very-bright regions several stops above the scene median.\"\n"
    "                       \"\\n\\nEnable this only as an emergency compatibility fallback. It restores the\"\n"
    "                       \"\\nprevious arithmetic mean of the whole frame, where small HDR highlights can\"\n"
    "                       \"\\ndominate the exposure.\");\n\n"
    "            ImGui::TextDisabled(simpleAverageFallback\n"
    "                                    ? \"Metering: simple arithmetic average (emergency fallback).\"\n"
    "                                    : \"Metering: highlight-protected log-luminance trimmed mean.\");\n\n"
    "            const auto autoStatus = DlssNr::AutoExposureStatus();\n"
    "            RenderExposureTrimAnchorControls(config->DlssNrAutoExposureTrimAnchors,\n",
    "automatic exposure fallback checkbox",
)

range_count = s.count("0.25f, 10.0f")
if range_count != 8:
    raise RuntimeError(f"menu Trim range: expected 8 occurrences, got {range_count}")
s = s.replace("0.25f, 10.0f", "0.25f, 50.0f")
help_count = s.count("Range: 0.25x to 10.00x.")
if help_count != 2:
    raise RuntimeError(f"menu Trim help range: expected 2 occurrences, got {help_count}")
s = s.replace("Range: 0.25x to 10.00x.", "Range: 0.25x to 50.00x.")
write(rel, s)

# -----------------------------------------------------------------------------
# Constant-buffer switch, C++ dispatch value and 50x runtime Trim range.
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/DlssNr_Common.h"
s = read(rel)
s = replace_once(
    s,
    "    float ExposureTrimAnchorExposure7;\n"
    "    float ExposureTrimAnchorTrim7;\n"
    "};\n",
    "    float ExposureTrimAnchorExposure7;\n"
    "    float ExposureTrimAnchorTrim7;\n"
    "    uint32_t AutoExposureSimpleAverageFallback;\n"
    "};\n",
    "automatic exposure fallback constant",
)
write(rel, s)

rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp"
s = read(rel)
s = replace_once(
    s,
    "        exposureParams.PreExposure = frame.PreExposure;\n"
    "        const D3D12_RESOURCE_DESC exposureSourceDesc = source->GetDesc();\n",
    "        exposureParams.PreExposure = frame.PreExposure;\n"
    "        exposureParams.AutoExposureSimpleAverageFallback =\n"
    "            cfg.DlssNrAutoExposureSimpleAverageFallback.value_or_default() ? 1u : 0u;\n"
    "        const D3D12_RESOURCE_DESC exposureSourceDesc = source->GetDesc();\n",
    "automatic exposure fallback dispatch constant",
)
runtime_range_count = s.count("0.25f, 10.0f")
if runtime_range_count != 4:
    raise RuntimeError(f"runtime Trim range: expected 4 occurrences, got {runtime_range_count}")
s = s.replace("0.25f, 10.0f", "0.25f, 50.0f")
write(rel, s)

# -----------------------------------------------------------------------------
# HLSL: default highlight-protected tile meter. The fallback branch preserves
# the previous arithmetic-average result exactly (same weighted tile sum and formula).
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/precompile/dlssnr.hlsl"
s = read(rel)
s = replace_once(
    s,
    "    float gExposureTrimAnchorExposure7;\n"
    "    float gExposureTrimAnchorTrim7;\n"
    "};\n",
    "    float gExposureTrimAnchorExposure7;\n"
    "    float gExposureTrimAnchorTrim7;\n"
    "    uint  gAutoExposureSimpleAverageFallback;\n"
    "};\n",
    "HLSL automatic exposure fallback constant",
)

hlsl_range_count = s.count("0.25, 10.0")
if hlsl_range_count != 11:
    raise RuntimeError(f"HLSL Trim range: expected 11 occurrences, got {hlsl_range_count}")
s = s.replace("0.25, 10.0", "0.25, 50.0")

auto_start = s.find("    if (gMode == 5)\n    {\n")
auto_end = s.find("    if (gMode == 4)\n", auto_start)
if auto_start < 0 or auto_end < 0 or auto_end <= auto_start:
    raise RuntimeError("automatic exposure HLSL block was not found")
if s.find("    if (gMode == 5)\n    {\n", auto_start + 1) >= 0:
    raise RuntimeError("automatic exposure HLSL block appears more than once")

new_auto = r'''    // Automatic exposure. The default meter is highlight-protected: the existing 64x64
    // tile means are converted to scene log-luminance, the distribution is trimmed, and a small
    // population several stops above the median increases the amount removed from the bright tail.
    // This lets a small HDR sky/window/specular region coexist with a mostly dark frame without
    // making the whole frame meter as bright. The emergency flag restores the old arithmetic mean.
    if (gMode == 5)
    {
        if (id.x != 0 || id.y != 0)
            return;

        const uint srcW = max(gExposureSourceWidth, 1u);
        const uint srcH = max(gExposureSourceHeight, 1u);
        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;

        float weightedBufferLuma = 0.0;
        float totalPixels = 0.0;
        float histogram[64];

        [loop] for (uint i = 0u; i < 64u; ++i)
            histogram[i] = 0.0;

        // First pass: preserve the exact old arithmetic-average accumulator for the fallback,
        // and simultaneously build a pixel-area-weighted 0.5-stop log-luminance histogram.
        [loop] for (uint ty = 0u; ty < 64u; ++ty)
        {
            const uint y0 = (ty * srcH) / 64u;
            const uint y1 = ((ty + 1u) * srcH) / 64u;
            const uint tileH = max(y1 - y0, 1u);

            [loop] for (uint tx = 0u; tx < 64u; ++tx)
            {
                const uint x0 = (tx * srcW) / 64u;
                const uint x1 = ((tx + 1u) * srcW) / 64u;
                const uint tileW = max(x1 - x0, 1u);
                const float pixels = (float) tileW * (float) tileH;
                const float tileMean = max(SanitizeFinite(gSource.Load(int3(tx, ty, 0)).r, 0.0), 0.0);

                weightedBufferLuma += tileMean * pixels;
                totalPixels += pixels;

                if (gAutoExposureSimpleAverageFallback == 0u)
                {
                    const float sceneLuma = max(tileMean / preExposure, 1e-8);
                    const float logLuma = clamp(log2(sceneLuma), -16.0, 16.0);
                    const uint bin = min((uint) ((logLuma + 16.0) * 2.0), 63u);
                    histogram[bin] += pixels;
                }
            }
        }

        const float averageBufferLuma = totalPixels > 0.0 ? weightedBufferLuma / totalPixels : 0.0;
        const float simpleAverageSceneLuma = averageBufferLuma / preExposure;
        float meteredSceneLuma = simpleAverageSceneLuma;

        if (gAutoExposureSimpleAverageFallback == 0u && totalPixels > 0.0)
        {
            // Median of the tile distribution. "Extreme highlight" means 3 stops (8x) above it.
            const float medianTarget = totalPixels * 0.5;
            float cumulative = 0.0;
            uint medianBin = 0u;
            [loop] for (uint i = 0u; i < 64u; ++i)
            {
                cumulative += histogram[i];
                if (cumulative >= medianTarget)
                {
                    medianBin = i;
                    break;
                }
            }

            const float medianLogLuma = -16.0 + ((float) medianBin + 0.5) * 0.5;
            const float highlightThreshold = medianLogLuma + 3.0;
            float highlightPixels = 0.0;
            [loop] for (uint i = 0u; i < 64u; ++i)
            {
                const float binCenter = -16.0 + ((float) i + 0.5) * 0.5;
                if (binCenter > highlightThreshold)
                    highlightPixels += histogram[i];
            }

            const float highlightCoverage = saturate(highlightPixels / totalPixels);

            // Always drop the hottest 5%. If a small part of the picture is >3 stops above the
            // median, smoothly trim approximately that whole bright population. Once such regions
            // occupy ~30% of the screen they are treated as scene content rather than an outlier.
            const float smallHighlightProtection = 1.0 - smoothstep(0.15, 0.30, highlightCoverage);
            const float upperTrimFraction =
                min(max(0.05, highlightCoverage * smallHighlightProtection), 0.20);
            const float lowTarget = totalPixels * 0.01;
            const float highTarget = totalPixels * (1.0 - upperTrimFraction);

            uint lowBin = 0u;
            uint highBin = 63u;
            cumulative = 0.0;
            bool lowFound = false;
            [loop] for (uint i = 0u; i < 64u; ++i)
            {
                cumulative += histogram[i];
                if (!lowFound && cumulative >= lowTarget)
                {
                    lowBin = i;
                    lowFound = true;
                }
                if (cumulative >= highTarget)
                {
                    highBin = i;
                    break;
                }
            }

            const float lowLogCut = -16.0 + (float) lowBin * 0.5;
            const float highLogCut = -16.0 + (float) (highBin + 1u) * 0.5;
            float trimmedLogSum = 0.0;
            float trimmedPixels = 0.0;

            // Second pass: exact log values inside the selected percentile window. This avoids
            // quantising the final mean to histogram-bin centres while keeping the histogram tiny.
            [loop] for (uint ty = 0u; ty < 64u; ++ty)
            {
                const uint y0 = (ty * srcH) / 64u;
                const uint y1 = ((ty + 1u) * srcH) / 64u;
                const uint tileH = max(y1 - y0, 1u);

                [loop] for (uint tx = 0u; tx < 64u; ++tx)
                {
                    const uint x0 = (tx * srcW) / 64u;
                    const uint x1 = ((tx + 1u) * srcW) / 64u;
                    const uint tileW = max(x1 - x0, 1u);
                    const float pixels = (float) tileW * (float) tileH;
                    const float tileMean = max(SanitizeFinite(gSource.Load(int3(tx, ty, 0)).r, 0.0), 0.0);
                    const float sceneLuma = max(tileMean / preExposure, 1e-8);
                    const float logLuma = clamp(log2(sceneLuma), -16.0, 16.0);

                    if (logLuma >= lowLogCut && logLuma <= highLogCut)
                    {
                        trimmedLogSum += logLuma * pixels;
                        trimmedPixels += pixels;
                    }
                }
            }

            if (trimmedPixels > 0.0)
            {
                const float trimmedMeanLogLuma = trimmedLogSum / trimmedPixels;
                const float protectedSceneLuma = exp2(trimmedMeanLogLuma);
                if (isfinite(protectedSceneLuma) && protectedSceneLuma > 1e-8)
                    meteredSceneLuma = protectedSceneLuma;
            }
        }

        float exposure = meteredSceneLuma > 1e-8
            ? 0.18 / (meteredSceneLuma * 0.82)
            : 1.0;

        if (!isfinite(exposure) || exposure <= 0.0)
            exposure = 1.0;

        gTarget[uint2(0, 0)] = float4(exposure, 0.0, 0.0, 1.0);
        return;
    }

'''
s = s[:auto_start] + new_auto + s[auto_end:]
write(rel, s)

print("DLSS-NR highlight-protected Automatic exposure + 50x Trim patch applied")
