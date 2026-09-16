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
# Automatic exposure keeps the original linear arithmetic-average exposure formula. By default,
# every tile remains in the meter, but very bright outliers are smoothly compressed relative to a
# stable full-frame log-luminance reference before the linear arithmetic mean is taken. There are
# no histogram buckets and no hard include/exclude decisions, avoiding exposure jumps when the
# camera moves slightly. A persisted emergency checkbox restores the exact old full-frame mean.

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
    "            HelpMarker(\"Normally Automatic exposure uses a stable highlight-compressed arithmetic average.\"\n"
    "                       \"\\nEvery 64x64 tile remains part of the meter. A full-frame log-luminance mean\"\n"
    "                       \"\\nis used only as a smooth brightness reference. Values up to 3 stops above\"\n"
    "                       \"\\nthat reference pass unchanged; brighter values are smoothly compressed,\"\n"
    "                       \"\\nnot removed. The final luminance is still a linear arithmetic mean and the\"\n"
    "                       \"\\noriginal exposure formula is unchanged. This avoids hard histogram-boundary\"\n"
    "                       \"\\njumps while limiting small extreme HDR highlights.\"\n"
    "                       \"\\n\\nEnable this only as an emergency compatibility fallback. It restores the\"\n"
    "                       \"\\nprevious arithmetic mean of the entire frame.\");\n\n"
    "            ImGui::TextDisabled(simpleAverageFallback\n"
    "                                    ? \"Metering: full-frame arithmetic average (emergency fallback).\"\n"
    "                                    : \"Metering: stable highlight-compressed arithmetic average.\");\n\n"
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
# HLSL: stable soft highlight compression. All tiles remain in the final LINEAR
# arithmetic mean. A full-frame mean in log2 luminance is used only as a smooth
# reference. Above +3 EV from that reference, additional brightness grows at 35%
# of its original rate in EV. No histogram or hard membership boundaries remain.
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

new_auto = r'''    // Automatic exposure. Keep the original linear arithmetic-average exposure math, but make
    // small extreme HDR highlights less dominant without ever dropping tiles from the meter.
    // A full-frame log2-luminance mean is used only as a continuous reference. Up to +3 EV above
    // that reference luminance passes unchanged. Beyond the knee, extra brightness grows at 35%
    // of its original rate in EV. This is continuous in camera motion and has no histogram-bin or
    // percentile-boundary switches. The emergency flag restores the old full-frame mean exactly.
    if (gMode == 5)
    {
        if (id.x != 0 || id.y != 0)
            return;

        const uint srcW = max(gExposureSourceWidth, 1u);
        const uint srcH = max(gExposureSourceHeight, 1u);
        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;

        float weightedBufferLuma = 0.0;
        float weightedSceneLogLuma = 0.0;
        float totalPixels = 0.0;

        // First pass: preserve the exact old full-frame arithmetic accumulator for fallback and,
        // for the protected path, obtain a smooth full-frame log-luminance reference.
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
                    const float logLuma = clamp(log2(sceneLuma), -24.0, 24.0);
                    weightedSceneLogLuma += logLuma * pixels;
                }
            }
        }

        const float averageBufferLuma = totalPixels > 0.0 ? weightedBufferLuma / totalPixels : 0.0;
        const float simpleAverageSceneLuma = averageBufferLuma / preExposure;
        float meteredSceneLuma = simpleAverageSceneLuma;

        if (gAutoExposureSimpleAverageFallback == 0u && totalPixels > 0.0)
        {
            const float referenceLogLuma = weightedSceneLogLuma / totalPixels;
            const float highlightKneeEv = 3.0;
            const float highlightCompressionSlope = 0.35;
            float protectedLinearSum = 0.0;

            // Second pass: every tile contributes by its real pixel area. Only the luminance value
            // of strong bright outliers is softly compressed; there is no hard selection step.
            [loop] for (uint protectedTy = 0u; protectedTy < 64u; ++protectedTy)
            {
                const uint y0 = (protectedTy * srcH) / 64u;
                const uint y1 = ((protectedTy + 1u) * srcH) / 64u;
                const uint tileH = max(y1 - y0, 1u);

                [loop] for (uint protectedTx = 0u; protectedTx < 64u; ++protectedTx)
                {
                    const uint x0 = (protectedTx * srcW) / 64u;
                    const uint x1 = ((protectedTx + 1u) * srcW) / 64u;
                    const uint tileW = max(x1 - x0, 1u);
                    const float pixels = (float) tileW * (float) tileH;
                    const float tileMean = max(
                        SanitizeFinite(gSource.Load(int3(protectedTx, protectedTy, 0)).r, 0.0), 0.0);
                    const float sceneLuma = max(tileMean / preExposure, 1e-8);
                    const float logLuma = clamp(log2(sceneLuma), -24.0, 24.0);
                    const float deltaEv = logLuma - referenceLogLuma;

                    float compressedLogLuma = logLuma;
                    if (deltaEv > highlightKneeEv)
                    {
                        compressedLogLuma = referenceLogLuma + highlightKneeEv +
                            (deltaEv - highlightKneeEv) * highlightCompressionSlope;
                    }

                    const float compressedSceneLuma = exp2(clamp(compressedLogLuma, -24.0, 24.0));
                    protectedLinearSum += compressedSceneLuma * pixels;
                }
            }

            const float protectedAverageSceneLuma = protectedLinearSum / totalPixels;
            if (isfinite(protectedAverageSceneLuma) && protectedAverageSceneLuma > 1e-8)
                meteredSceneLuma = protectedAverageSceneLuma;
        }

        // Keep the original NVIDIA-style exposure formula unchanged. Only extreme bright outlier
        // contributions to the arithmetic mean above are compressed in the default meter.
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

print("DLSS-NR stable highlight-compressed Automatic exposure + 50x Trim patch applied")
