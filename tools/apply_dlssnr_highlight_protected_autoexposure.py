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
# Automatic exposure keeps the original arithmetic-average exposure formula, but by default
# measures the dominant majority of the frame instead of allowing a small HDR-bright region to
# dominate the mean. A log-luminance histogram is used only to select the majority interval;
# the luminance average itself remains linear/arithmetic. A persisted emergency checkbox restores
# the exact full-frame arithmetic-average meter used previously.

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
    "            HelpMarker(\"Normally Automatic exposure uses a majority-selected arithmetic average.\"\n"
    "                       \"\\nA log-luminance histogram is used only to find the narrowest continuous\"\n"
    "                       \"\\nbrightness range covering 70% of the frame. The exposure luminance is then\"\n"
    "                       \"\\ncomputed as the ordinary linear arithmetic mean of tiles in that range.\"\n"
    "                       \"\\nThis prevents a small very-bright sky/window/specular region from dominating\"\n"
    "                       \"\\na mostly dark frame while keeping the original exposure formula.\"\n"
    "                       \"\\n\\nEnable this only as an emergency compatibility fallback. It restores the\"\n"
    "                       \"\\nprevious arithmetic mean of the entire frame.\");\n\n"
    "            ImGui::TextDisabled(simpleAverageFallback\n"
    "                                    ? \"Metering: full-frame arithmetic average (emergency fallback).\"\n"
    "                                    : \"Metering: majority-selected 70% arithmetic average.\");\n\n"
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
# HLSL: majority-selected arithmetic meter. The log histogram only chooses the
# dominant 70% brightness interval; the final luminance is an ordinary linear
# arithmetic mean, and the original NVIDIA-style exposure formula is unchanged.
# The fallback branch preserves the previous full-frame arithmetic average exactly.
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

new_auto = r'''    // Automatic exposure. Keep the original arithmetic-average exposure math, but prevent
    // a small, extremely bright HDR region from controlling a mostly dark frame. The 64x64 tile
    // means are placed into a log-luminance histogram only to locate the narrowest continuous
    // brightness interval containing 70% of the frame. The final metered luminance is then the
    // ordinary LINEAR arithmetic mean of the tiles inside that majority interval.
    // The emergency flag restores the old full-frame arithmetic mean exactly.
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

        [loop] for (uint histogramInitIndex = 0u; histogramInitIndex < 64u; ++histogramInitIndex)
            histogram[histogramInitIndex] = 0.0;

        // First pass: preserve the exact old full-frame arithmetic accumulator for the fallback,
        // while the default path builds a pixel-area-weighted 0.5-stop histogram used only for
        // selecting which brightness population should contribute to that same arithmetic mean.
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
            // Find the median bin only as a stable tie-breaker. The selected interval itself is the
            // narrowest contiguous set of histogram bins containing at least 70% of the image.
            const float medianTarget = totalPixels * 0.5;
            float cumulativeForMedian = 0.0;
            uint medianBin = 0u;
            [loop] for (uint medianIndex = 0u; medianIndex < 64u; ++medianIndex)
            {
                cumulativeForMedian += histogram[medianIndex];
                if (cumulativeForMedian >= medianTarget)
                {
                    medianBin = medianIndex;
                    break;
                }
            }

            const float majorityTarget = totalPixels * 0.70;
            uint majorityLowBin = 0u;
            uint majorityHighBin = 63u;
            uint bestBinWidth = 64u;
            float bestCenterDistance = 1e9;

            [loop] for (uint lowBin = 0u; lowBin < 64u; ++lowBin)
            {
                float intervalPixels = 0.0;
                [loop] for (uint highBin = lowBin; highBin < 64u; ++highBin)
                {
                    intervalPixels += histogram[highBin];
                    if (intervalPixels >= majorityTarget)
                    {
                        const uint binWidth = highBin - lowBin;
                        const float intervalCenter = ((float) lowBin + (float) highBin) * 0.5;
                        const float centerDistance = abs(intervalCenter - (float) medianBin);

                        if (binWidth < bestBinWidth ||
                            (binWidth == bestBinWidth && centerDistance < bestCenterDistance))
                        {
                            bestBinWidth = binWidth;
                            bestCenterDistance = centerDistance;
                            majorityLowBin = lowBin;
                            majorityHighBin = highBin;
                        }
                        break;
                    }
                }
            }

            const float majorityLowLog = -16.0 + (float) majorityLowBin * 0.5;
            const float majorityHighLog = -16.0 + (float) (majorityHighBin + 1u) * 0.5;
            float majorityLinearSum = 0.0;
            float majorityPixels = 0.0;

            // Second pass: membership is decided in log space, but the quantity being averaged is
            // the original LINEAR scene luminance. This deliberately keeps the old exposure math.
            [loop] for (uint majorityTy = 0u; majorityTy < 64u; ++majorityTy)
            {
                const uint y0 = (majorityTy * srcH) / 64u;
                const uint y1 = ((majorityTy + 1u) * srcH) / 64u;
                const uint tileH = max(y1 - y0, 1u);

                [loop] for (uint majorityTx = 0u; majorityTx < 64u; ++majorityTx)
                {
                    const uint x0 = (majorityTx * srcW) / 64u;
                    const uint x1 = ((majorityTx + 1u) * srcW) / 64u;
                    const uint tileW = max(x1 - x0, 1u);
                    const float pixels = (float) tileW * (float) tileH;
                    const float tileMean = max(
                        SanitizeFinite(gSource.Load(int3(majorityTx, majorityTy, 0)).r, 0.0), 0.0);
                    const float sceneLuma = max(tileMean / preExposure, 1e-8);
                    const float logLuma = clamp(log2(sceneLuma), -16.0, 16.0);

                    if (logLuma >= majorityLowLog && logLuma <= majorityHighLog)
                    {
                        majorityLinearSum += sceneLuma * pixels;
                        majorityPixels += pixels;
                    }
                }
            }

            if (majorityPixels > 0.0)
            {
                const float majorityAverageSceneLuma = majorityLinearSum / majorityPixels;
                if (isfinite(majorityAverageSceneLuma) && majorityAverageSceneLuma > 1e-8)
                    meteredSceneLuma = majorityAverageSceneLuma;
            }
        }

        // Keep the original exposure formula unchanged. Only the population used to obtain the
        // arithmetic average above differs from the full-frame fallback.
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

print("DLSS-NR majority-selected arithmetic Automatic exposure + 50x Trim patch applied")
