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

# 0) Config + UI: Automatic Exposure is a separate WhitePointSource.
rel = "OptiScaler/Config.h"
s = read(rel)
s = replace_once(
    s,
    "    CustomOptional<uint32_t> DlssNrWhitePointSource { 1 };\n\n"
    "    CustomOptional<bool> DlssNrScanMeter { false };\n",
    "    CustomOptional<uint32_t> DlssNrWhitePointSource { 1 };\n\n"
    "    // Separate trim for OptiScaler's own GPU-calculated exposure (WhitePointSource == 2).\n"
    "    CustomOptional<float> DlssNrAutoExposureTrim { 1.0f };\n\n"
    "    CustomOptional<bool> DlssNrScanMeter { false };\n",
    "config auto-exposure fields",
)
s = replace_once(
    s,
    "    //   0  the paper white slider, and nothing else\n"
    "    //   1  the exposure the game hands the upscaler\n"
    "    //   2  a buffer the scan found, anchored to a white point the user chose once\n",
    "    //   0  the paper white slider, and nothing else\n"
    "    //   1  the exposure the game hands the upscaler (game only; no automatic fallback)\n"
    "    //   2  OptiScaler automatic exposure, calculated from the original linear-HDR frame\n"
    "    //   3  a buffer the scan found, anchored to a white point the user chose once\n",
    "config white-point source documentation",
)
write(rel, s)

rel = "OptiScaler/Config.cpp"
s = read(rel)
s = replace_once(
    s,
    "            DlssNrWhitePointSource.set_from_config(readUInt(\"DlssNr\", \"WhitePointSource\"));\n",
    "            DlssNrWhitePointSource.set_from_config(readUInt(\"DlssNr\", \"WhitePointSource\"));\n"
    "            DlssNrAutoExposureTrim.set_from_config(readFloat(\"DlssNr\", \"AutoExposureTrim\"));\n",
    "config read auto exposure",
)
s = replace_once(
    s,
    "    ini.SetValue(\"DlssNr\", \"WhitePointSource\", GetIntValue(Instance()->DlssNrWhitePointSource.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"WhitePointTrim\", GetFloatValue(Instance()->DlssNrWhitePointTrim.value_for_config()).c_str());\n",
    "    ini.SetValue(\"DlssNr\", \"WhitePointSource\", GetIntValue(Instance()->DlssNrWhitePointSource.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"AutoExposureTrim\",\n"
    "                 GetFloatValue(Instance()->DlssNrAutoExposureTrim.value_for_config()).c_str());\n"
    "    ini.SetValue(\"DlssNr\", \"WhitePointTrim\", GetFloatValue(Instance()->DlssNrWhitePointTrim.value_for_config()).c_str());\n",
    "config write auto exposure",
)
write(rel, s)

rel = "OptiScaler/dlssnr/DlssNr_Menu.cpp"
s = read(rel)
s = replace_once(
    s,
    r'''            static const char* sourceNames[] = { "Paper white only", "The game's own exposure",
                                                 "A buffer the scan found" };''',
    r'''            static const char* sourceNames[] = { "Paper white only", "The game's own exposure",
                                                 "Automatic exposure", "A buffer the scan found" };''',
    "menu four source names",
)
s = replace_once(
    s,
    r'''            if (source < 0 || source > 2)
                source = 0;''',
    r'''            if (source < 0 || source > 3)
                source = 0;''',
    "menu source range",
)
s = replace_once(
    s,
    r'''            HelpMarker("Where the number that divides the frame comes from."
                           "\n\nPaper white only -- the slider below and nothing else. Right for a"
                           "\ngame whose exposure never moves, wrong the moment it does: one"
                           "\nconstant cannot serve a cave and a field."
                           "\n\nThe game's own exposure -- read from the texture the game hands"
                           "\nthe upscaler. The best source there is, because it is decided"
                           "\nupstream and nothing this pass does can move it. Not every game"
                           "\nsupplies one."
                           "\n\nA buffer the scan found -- for games that compute an exposure and"
                           "\nnever pass it on. A GUESS: candidates are matched by shape, and in"
                           "\nGTA V the best one tracks the real exposure but at its own scale,"
                           "\nwhich the anchor's ratio cancels. Needs anchoring once, and checking"
                           "\nafterwards.");''',
    r'''            HelpMarker("Where the number that divides the frame comes from."
                           "\n\nPaper white only -- the slider below and nothing else."
                           "\n\nThe game's own exposure -- uses ONLY the ExposureTexture supplied"
                           "\nby the game. If the game does not provide it, this source is unavailable;"
                           "\nOptiScaler does not switch to automatic exposure."
                           "\n\nAutomatic exposure -- OptiScaler ALWAYS calculates exposure itself"
                           "\nfrom the original linear-HDR frame before Neural Rendering. The game's"
                           "\nExposureTexture is ignored even when the game provides one."
                           "\n\nA buffer the scan found -- the existing manually calibrated scan path."
                           "\nIt is now the fourth source.");''',
    "menu source help",
)
s = replace_once(
    s,
    r'''            else if (source == 2)
            {
                // "Nothing found" and "found several, none of them moving" are different states,''',
    r'''            else if (source == 2)
            {
                if (vk)
                    ImGui::TextColored(ImVec4(0.9f, 0.6f, 0.25f, 1.0f),
                                       "Automatic exposure is currently available on D3D12 only.");
                else
                    ImGui::TextColored(ImVec4(0.45f, 0.8f, 0.45f, 1.0f),
                                       "OptiScaler automatic exposure is active; game ExposureTexture is ignored.");
            }
            else if (source == 3)
            {
                // "Nothing found" and "found several, none of them moving" are different states,''',
    "menu automatic source status and scan shift",
)
s = replace_once(
    s,
    "        if (wpSource == 2)\n",
    "        if (wpSource == 3)\n",
    "menu scan controls shift to source 3",
)
s = replace_once(
    s,
    "                else if (!haveExposure)\n"
    "                    ImGui::TextColored(ImVec4(0.9f, 0.6f, 0.25f, 1.0f),\n"
    "                                       \"This game supplies no exposure -- paper white is in use. Try \"\n"
    "                                       \"the scan instead.\");\n",
    "                else if (!haveExposure)\n"
    "                    ImGui::TextColored(ImVec4(0.9f, 0.6f, 0.25f, 1.0f),\n"
    "                                       \"This game supplies no ExposureTexture -- this source is unavailable.\");\n",
    "menu no-exposure status",
)
s = replace_once(
    s,
    "                        std::clamp(config->DlssNrWhitePointTrim.value_or_default(), 0.25f, 4.0f);\n",
    "                        std::clamp(config->DlssNrWhitePointTrim.value_or_default(), 0.25f, 10.0f);\n",
    "menu game trim status clamp",
)
old = r'''        else if (wpSource == 1)
        {
            const bool ofScan = false;

            float trim = ofScan ? config->DlssNrScanTrim.value_or_default()
                                : config->DlssNrWhitePointTrim.value_or_default();

            if (ImGui::SliderFloat(ofScan ? "Trim (x the scan)" : "Trim (x the game's exposure)", &trim,
                                   0.25f, 4.0f, "%.2fx", ImGuiSliderFlags_Logarithmic))
            {
                if (ofScan)
                    config->DlssNrScanTrim = std::clamp(trim, 0.25f, 4.0f);
                else
                    config->DlssNrWhitePointTrim = std::clamp(trim, 0.25f, 4.0f);
            }

            ImGui::SameLine();

            // Deliberately always present rather than greyed at 1. The point of it is that the safe
            // value is one click away without having to know what the safe value is.
            if (ImGui::SmallButton("Reset##wptrim"))
            {
                if (ofScan)
                    config->DlssNrScanTrim = 1.0f;
                else
                    config->DlssNrWhitePointTrim = 1.0f;
            }

            HelpMarker("A multiplier on the exposure the game supplied. 1.00x takes its number"
                           "\nexactly, and that is the right answer here."
                           "\n\nThis is not a fudge factor. If a game needs the trim far from 1 to look"
                           "\nright, that is evidence the exposure being read is wrong for that game,"
                           "\nnot that the game wants trimming. Somewhere around 0.8 to 1.25 is honest"
                           "\ntuning; reaching for 4 means something upstream is broken and the trim is"
                           "\nhiding it."
                           "\n\nYour manual paper white is kept separately and comes back untouched if"
                           "\nyou switch the option above off.");
        }
'''
new = r'''        else if (wpSource == 1)
        {
            float gameTrim = config->DlssNrWhitePointTrim.value_or_default();

            if (ImGui::SliderFloat("Trim (x the game's exposure)", &gameTrim, 0.25f, 10.0f, "%.2fx",
                                   ImGuiSliderFlags_Logarithmic))
                config->DlssNrWhitePointTrim = std::clamp(gameTrim, 0.25f, 10.0f);

            ImGui::SameLine();
            if (ImGui::SmallButton("Reset##wptrim"))
                config->DlssNrWhitePointTrim = 1.0f;

            HelpMarker("Multiplier on the white point derived from the game's own ExposureTexture."
                       "\n\n1.00x uses the game's value unchanged. Range: 0.25x to 10.00x."
                       "\n\nThis source never switches to OptiScaler automatic exposure. If the game"
                       "\ndoes not supply ExposureTexture, the status above reports that this source"
                       "\nis unavailable.");
        }
        else if (wpSource == 2)
        {
            float autoTrim = config->DlssNrAutoExposureTrim.value_or_default();

            if (ImGui::SliderFloat("Trim (x automatic exposure)", &autoTrim, 0.25f, 4.0f, "%.2fx",
                                   ImGuiSliderFlags_Logarithmic))
                config->DlssNrAutoExposureTrim = std::clamp(autoTrim, 0.25f, 4.0f);

            ImGui::SameLine();
            if (ImGui::SmallButton("Reset##autoexposuretrim"))
                config->DlssNrAutoExposureTrim = 1.0f;

            HelpMarker("OptiScaler calculates exposure itself from the ORIGINAL linear-HDR frame"
                       "\nbefore Neural Rendering changes it."
                       "\n\nThis source always uses OptiScaler's calculation: the game's ExposureTexture"
                       "\nis ignored even when present. One 1x1 exposure value is calculated on the GPU"
                       "\nand reused by Encode, every Neural Rendering pass, and Resolve."
                       "\n\n1.00x uses the calculated value unchanged. Range: 0.25x to 4.00x."
                       "\nAutomatic exposure is currently D3D12 only.");
        }
'''
s = replace_once(s, old, new, "menu separate game/automatic exposure controls")
write(rel, s)

# 1) Shared constants/modes.
rel = "OptiScaler/shaders/dlssnr/DlssNr_Common.h"
s = read(rel)
s = replace_once(
    s,
    "    DlssNrMode_Meter = 3,      // the exposure texture -> tile (0,0), for the white point\n"
    "    DlssNrMode_Calibrate = 4   // the untouched frame -> a grid of tile peak luminances\n",
    "    DlssNrMode_Meter = 3,      // exposure copy, or frame -> 64x64 tile luminance means\n"
    "    DlssNrMode_Calibrate = 4,  // the untouched frame -> a grid of tile peak luminances\n"
    "    DlssNrMode_AutoExposure = 5 // 64x64 tile means -> NVIDIA-style 1x1 exposure texture\n",
    "mode enum",
)
s = replace_once(
    s,
    "    float DebugScale;\n"
    "};\n",
    "    float DebugScale;\n"
    "\n"
    "    // Auto-exposure only. Appended so every existing field keeps its byte offset for Vulkan.\n"
    "    float PreExposure;\n"
    "    uint32_t ExposureSourceWidth;\n"
    "    uint32_t ExposureSourceHeight;\n"
    "    uint32_t MeterCopiesExposure;\n"
    "};\n",
    "constant tail",
)
write(rel, s)

# 2) D3D composition shader.
rel = "OptiScaler/shaders/dlssnr/precompile/dlssnr.hlsl"
s = read(rel)
s = replace_once(
    s,
    "    uint  gTransfer;     // 0 classic, 1 matched residual -- how a below-size model comes back\n"
    "    float gDebugScale;   // what the debug views are scaled by, held still while the meter moves\n"
    "};\n",
    "    uint  gTransfer;     // 0 classic, 1 matched residual -- how a below-size model comes back\n"
    "    float gDebugScale;   // what the debug views are scaled by, held still while the meter moves\n"
    "\n"
    "    // Auto exposure. Appended so the layout of every existing field is unchanged.\n"
    "    float gPreExposure;\n"
    "    uint  gExposureSourceWidth;\n"
    "    uint  gExposureSourceHeight;\n"
    "    uint  gMeterCopiesExposure;\n"
    "};\n",
    "HLSL cbuffer tail",
)

anchor = "    if (gMode == 4)\n"
auto_mode = r'''    // NVIDIA DLSS auto-exposure fallback. gSource is the 64x64 grid of exact tile
    // means produced by mode 3 from the ORIGINAL linear-HDR frame, before NR touches it.
    // Weighting by the source tile areas makes this the arithmetic mean of all source pixels even
    // when width/height are not divisible by 64.
    if (gMode == 5)
    {
        if (id.x != 0 || id.y != 0)
            return;

        const uint srcW = max(gExposureSourceWidth, 1u);
        const uint srcH = max(gExposureSourceHeight, 1u);

        float weightedLuma = 0.0;
        float totalPixels = 0.0;

        [loop] for (uint ty = 0; ty < 64u; ++ty)
        {
            const uint y0 = (ty * srcH) / 64u;
            const uint y1 = ((ty + 1u) * srcH) / 64u;
            const uint tileH = max(y1 - y0, 1u);

            [loop] for (uint tx = 0; tx < 64u; ++tx)
            {
                const uint x0 = (tx * srcW) / 64u;
                const uint x1 = ((tx + 1u) * srcW) / 64u;
                const uint tileW = max(x1 - x0, 1u);
                const float pixels = (float) tileW * (float) tileH;
                const float tileMean = max(SanitizeFinite(gSource.Load(int3(tx, ty, 0)).r, 0.0), 0.0);

                weightedLuma += tileMean * pixels;
                totalPixels += pixels;
            }
        }

        const float averageBufferLuma =
            totalPixels > 0.0 ? weightedLuma / totalPixels : 0.0;
        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;
        const float averageSceneLuma = averageBufferLuma / preExposure;

        // DLSS Programming Guide:
        // ExposureValue = MidGray / (AverageLuma * (1 - MidGray)), MidGray = 0.18.
        float exposure = averageSceneLuma > 1e-8
            ? 0.18 / (averageSceneLuma * 0.82)
            : 1.0;

        if (!isfinite(exposure) || exposure <= 0.0)
            exposure = 1.0;

        gTarget[uint2(0, 0)] = float4(exposure, 0.0, 0.0, 1.0);
        return;
    }

'''
s = replace_once(s, anchor, auto_mode + anchor, "auto exposure mode insertion")

old_meter_head = r'''    if (gMode == 3)
    {
        // Tile (0,0) carries the game's own exposure rather than a tile mean.
        //
        // The exposure is a 1x1 texture the game owns, in a resource state this pass did not set and
        // must not assume. Copying it would mean transitioning someone else's resource on a guess,
        // which is how a device is lost. Reading it as an SRV in a pass that is already running costs
        // nothing and touches no state -- and it rides back on the readback that already exists.
        //
        // The motion slot is free here: the meter has no use for motion vectors.
        if (id.x == 0 && id.y == 0)
        {
            gTarget[id.xy] = float4(gMotion.Load(int3(0, 0, 0)).r, 0.0, 0.0, 1.0);
            return;
        }

        uint fullW, fullH;
'''
new_meter_head = r'''    if (gMode == 3)
    {
        // Existing white-point path: copy the game's own 1x1 exposure into tile (0,0).
        // Auto exposure sets this flag to zero and uses the same mode for a real luminance grid.
        if (gMeterCopiesExposure != 0)
        {
            if (id.x == 0 && id.y == 0)
                gTarget[id.xy] = float4(gMotion.Load(int3(0, 0, 0)).r, 0.0, 0.0, 1.0);
            return;
        }

        uint fullW, fullH;
'''
s = replace_once(s, old_meter_head, new_meter_head, "meter head")

old_sampling = r'''        // A tile of a 4K frame is 60x34 pixels. Sampling a bounded number of them is within a percent
        // of the true mean and keeps the pass flat regardless of resolution.
        const uint stepX = max((tx1 - tx0) / 8u, 1u);
        const uint stepY = max((ty1 - ty0) / 8u, 1u);

        float sum = 0.0;
        uint taken = 0;

        for (uint ty = ty0; ty < max(ty1, ty0 + 1u); ty += stepY)
        {
            for (uint tx = tx0; tx < max(tx1, tx0 + 1u); tx += stepX)
            {
                float3 c = max(gSource.Load(int3(min(tx, fullW - 1u), min(ty, fullH - 1u), 0)).rgb, 0.0);
                sum += dot(c, kLuma);
                taken++;
            }
        }

        gTarget[id.xy] = float4(taken > 0u ? sum / (float) taken : 0.0, 0.0, 0.0, 1.0);
'''
new_sampling = r'''        // Exact arithmetic mean for this tile. The second pass weights these means by the exact
        // tile areas, so the final value is AverageLuma over the whole source frame, not a sample or
        // percentile approximation.
        float sum = 0.0;
        uint taken = 0;

        [loop] for (uint ty = ty0; ty < max(ty1, ty0 + 1u); ++ty)
        {
            [loop] for (uint tx = tx0; tx < max(tx1, tx0 + 1u); ++tx)
            {
                float3 c = max(gSource.Load(int3(min(tx, fullW - 1u), min(ty, fullH - 1u), 0)).rgb, 0.0);
                float luma = dot(c, kLuma);
                sum += isfinite(luma) ? max(luma, 0.0) : 0.0;
                taken++;
            }
        }

        gTarget[id.xy] = float4(taken > 0u ? sum / (float) taken : 0.0, 0.0, 0.0, 1.0);
'''
s = replace_once(s, old_sampling, new_sampling, "meter exact mean")
write(rel, s)

# 3) Forwarder: optional setter instead of changing the evaluate ABI.
rel = "OptiScaler/dlssnr/forwarder/dlssnr_forwarder.cpp"
s = read(rel)
marker = '''// Inputs NVIDIA's own Streamline plugin sets that the positional exports predate: the model's global
'''
setter = r'''// Standard NGX exposure input. Kept as a separate optional export so an older forwarder remains
// binary-compatible with the host; the host simply cannot provide exposure through it.
__declspec(dllexport) void dlssnr_call_set_exposure(void *capabilityParams,
                                                    ID3D12Resource *exposure) {
    if (!capabilityParams) {
        return;
    }

    // NVIDIA's public NGX name is NVSDK_NGX_Parameter_ExposureTexture == "ExposureTexture".
    // Write null as well: capabilityParams is shared with the game's DLSS and outlives a frame, so a
    // missing exposure must clear the previous pointer rather than leave a stale resource behind.
    setResource(capabilityParams, "ExposureTexture", exposure);
}

'''
s = replace_once(s, marker, setter + marker, "forwarder exposure setter")
write(rel, s)

# 4) D3D12 host.
rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp"
s = read(rel)

s = replace_once(
    s,
    "using PFN_NrSetExtras = void(__cdecl*) (void*, float, ID3D12Resource*, ID3D12Resource*, ID3D12Resource*,\n"
    "                                        unsigned int, unsigned int, unsigned int, unsigned int);\n"
    "using PFN_NrSetFloatSlot = void(__cdecl*) (int);\n",
    "using PFN_NrSetExtras = void(__cdecl*) (void*, float, ID3D12Resource*, ID3D12Resource*, ID3D12Resource*,\n"
    "                                        unsigned int, unsigned int, unsigned int, unsigned int);\n"
    "using PFN_NrSetExposure = void(__cdecl*) (void*, ID3D12Resource*);\n"
    "using PFN_NrSetFloatSlot = void(__cdecl*) (int);\n",
    "PFN exposure typedef",
)

s = replace_once(
    s,
    "    PFN_NrSetExtras setExtras = nullptr;\n"
    "    PFN_NrSetFloatSlot setFloatSlot = nullptr;\n",
    "    PFN_NrSetExtras setExtras = nullptr;\n"
    "    PFN_NrSetExposure setExposure = nullptr;\n"
    "    PFN_NrSetFloatSlot setFloatSlot = nullptr;\n",
    "state setter pointer",
)

s = replace_once(
    s,
    "    ID3D12Resource* meter = nullptr;\n"
    "    ID3D12Resource* meterReadback[4] = {};\n",
    "    ID3D12Resource* meter = nullptr;\n"
    "    ID3D12Resource* meterReadback[4] = {};\n"
    "\n"
    "    // GPU-generated fallback for games that do not supply NGX ExposureTexture. R32_FLOAT is used\n"
    "    // because this pass already has a proven typed-UAV path for it; NGX reads the first channel.\n"
    "    ID3D12Resource* autoExposure = nullptr;\n"
    "    bool autoExposureReadable = false;\n",
    "auto exposure state",
)

s = replace_once(
    s,
    "    g_nr.setExtras = (PFN_NrSetExtras) GetProcAddress(g_nr.forwarder, \"dlssnr_call_set_extras\");\n"
    "    g_nr.setFloatSlot = (PFN_NrSetFloatSlot) GetProcAddress(g_nr.forwarder, \"dlssnr_call_set_float_slot\");\n",
    "    g_nr.setExtras = (PFN_NrSetExtras) GetProcAddress(g_nr.forwarder, \"dlssnr_call_set_extras\");\n"
    "    g_nr.setExposure =\n"
    "        (PFN_NrSetExposure) GetProcAddress(g_nr.forwarder, \"dlssnr_call_set_exposure\");\n"
    "    g_nr.setFloatSlot = (PFN_NrSetFloatSlot) GetProcAddress(g_nr.forwarder, \"dlssnr_call_set_float_slot\");\n",
    "resolve exposure export",
)

needle = '''        if (g_nr.meter != nullptr)
            LOG_INFO("DLSS-NR: white point meter up, {}x{} tiles", kDlssNrMeterGrid, kDlssNrMeterGrid);
    }

    // On an engine that needs its compute state put back'''
replacement = '''        if (g_nr.meter != nullptr)
            LOG_INFO("DLSS-NR: white point meter up, {}x{} tiles", kDlssNrMeterGrid, kDlssNrMeterGrid);
    }

    if (g_nr.autoExposure == nullptr)
    {
        g_nr.autoExposure = CreateScratch(device, DXGI_FORMAT_R32_FLOAT, 1, 1);
        g_nr.autoExposureReadable = false;

        if (g_nr.autoExposure == nullptr)
            LOG_WARN("DLSS-NR: could not allocate the 1x1 auto-exposure texture");
        else
            LOG_INFO("DLSS-NR: GPU auto-exposure fallback is available");
    }

    // On an engine that needs its compute state put back'''
s = replace_once(s, needle, replacement, "auto exposure allocation")

s = replace_once(
    s,
    "        meterParams.Width = 1;\n"
    "        meterParams.Height = 1;\n"
    "\n"
    "        // The game's exposure texture is read here as an SRV.",
    "        meterParams.Width = 1;\n"
    "        meterParams.Height = 1;\n"
    "        meterParams.MeterCopiesExposure = 1;\n"
    "\n"
    "        // The game's exposure texture is read here as an SRV.",
    "meter copy flag",
)

needle = '''    g_nr.gamePreExposure = frame.PreExposure;

    const float whitePoint = ResolveWhitePoint(cfg, isHdrBuffer);
'''
replacement = '''    g_nr.gamePreExposure = frame.PreExposure;

    // What Neural Rendering receives as NGX ExposureTexture. Prefer the game's own value. If it did
    // not supply one, calculate the documented DLSS exposure entirely on the GPU from the original
    // linear-HDR input, before encode/NR can alter it. One value is produced here and reused by every
    // feature in the multi-pass chain below.
    ID3D12Resource* nrExposure = (ID3D12Resource*) frame.ExposureTexture;
    const bool nrExposureIsGame = nrExposure != nullptr;
    const D3D12_RESOURCE_STATES exposureArrival =
        cfg.ExposureResourceBarrier.has_value()
            ? (D3D12_RESOURCE_STATES) cfg.ExposureResourceBarrier.value()
            : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

    if (g_nr.setExposure != nullptr && nrExposure == nullptr && isHdrBuffer &&
        g_nr.meter != nullptr && g_nr.autoExposure != nullptr)
    {
        DlssNrConstants meterParams {};
        meterParams.Mode = DlssNrMode_Meter;
        meterParams.Width = kDlssNrMeterGrid;
        meterParams.Height = kDlssNrMeterGrid;
        meterParams.MeterCopiesExposure = 0;

        Barrier(cmdList, source, sourceIdle, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        DispatchPass(cmdList, meterParams, source, nullptr, nullptr, nullptr, nullptr, g_nr.meter, nullptr);
        Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);

        // The meter's UAV -> SRV transition is both the state change and the ordering point between
        // the tile pass and the 1x1 reduction.
        Barrier(cmdList, g_nr.meter, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        if (g_nr.autoExposureReadable)
            Barrier(cmdList, g_nr.autoExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

        DlssNrConstants exposureParams {};
        exposureParams.Mode = DlssNrMode_AutoExposure;
        exposureParams.Width = 1;
        exposureParams.Height = 1;
        exposureParams.PreExposure = frame.PreExposure;
        const D3D12_RESOURCE_DESC exposureSourceDesc = source->GetDesc();
        exposureParams.ExposureSourceWidth = (uint32_t) exposureSourceDesc.Width;
        exposureParams.ExposureSourceHeight = exposureSourceDesc.Height;

        DispatchPass(cmdList, exposureParams, g_nr.meter, nullptr, nullptr, nullptr, nullptr,
                     g_nr.autoExposure, nullptr);

        Barrier(cmdList, g_nr.meter, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Barrier(cmdList, g_nr.autoExposure, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        g_nr.autoExposureReadable = true;
        nrExposure = g_nr.autoExposure;
    }

    // Optional export: old forwarders continue to work unchanged; a new one writes the standard NGX
    // "ExposureTexture" key. Writing null is important because capabilityParams persists across frames.
    if (g_nr.setExposure != nullptr)
        g_nr.setExposure(g_nr.capabilityParams, nrExposure);

    const float whitePoint = ResolveWhitePoint(cfg, isHdrBuffer);
'''
s = replace_once(s, needle, replacement, "auto exposure dispatch")

needle = '''    if (g_ngxTime != nullptr)
        g_ngxTime->Start(cmdList);

    int result = NVSDK_NGX_Result_Success;
'''
replacement = '''    if (g_nr.setExposure != nullptr && nrExposureIsGame)
        Barrier(cmdList, nrExposure, exposureArrival,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    if (g_ngxTime != nullptr)
        g_ngxTime->Start(cmdList);

    int result = NVSDK_NGX_Result_Success;
'''
s = replace_once(s, needle, replacement, "game exposure transition")

needle = '''    if (g_ngxTime != nullptr)
        g_ngxTime->End(cmdList);

    g_nr.reset = false;
'''
replacement = '''    if (g_ngxTime != nullptr)
        g_ngxTime->End(cmdList);

    if (g_nr.setExposure != nullptr && nrExposureIsGame)
        Barrier(cmdList, nrExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                exposureArrival);

    g_nr.reset = false;
'''
s = replace_once(s, needle, replacement, "game exposure restore")

needle = '''    if (g_nr.meter != nullptr)
    {
        g_nr.meter->Release();
        g_nr.meter = nullptr;
    }

    if (g_nr.calib != nullptr)
'''
replacement = '''    if (g_nr.meter != nullptr)
    {
        g_nr.meter->Release();
        g_nr.meter = nullptr;
    }

    if (g_nr.autoExposure != nullptr)
    {
        g_nr.autoExposure->Release();
        g_nr.autoExposure = nullptr;
    }

    g_nr.autoExposureReadable = false;

    if (g_nr.calib != nullptr)
'''
s = replace_once(s, needle, replacement, "auto exposure shutdown")
write(rel, s)

print("DLSS-NR auto-exposure source patch applied")

# 5) V4 refinements: Automatic Exposure is an independent source and always uses our GPU calculation.
# Game Exposure is game-only. The generated 1x1 texture drives composition without CPU readback.

# Extend the shared constant tail. Existing offsets stay unchanged because these fields are appended.
rel = "OptiScaler/shaders/dlssnr/DlssNr_Common.h"
s = read(rel)
s = replace_once(
    s,
    "    uint32_t MeterCopiesExposure;\n};\n",
    "    uint32_t MeterCopiesExposure;\n"
    "    float ExposureTrim;\n"
    "    uint32_t UseExposureWhitePoint;\n"
    "};\n",
    "v2 constant tail",
)
write(rel, s)

# D3D shader: fifth SRV was already present in the D3D root signature but unused by this shader.
# Keep it D3D-only so the native Vulkan descriptor layout does not move.
rel = "OptiScaler/shaders/dlssnr/precompile/dlssnr.hlsl"
s = read(rel)
s = replace_once(
    s,
    "    uint  gMeterCopiesExposure;\n};\n",
    "    uint  gMeterCopiesExposure;\n"
    "    float gExposureTrim;\n"
    "    uint  gUseExposureWhitePoint;\n"
    "};\n",
    "v2 HLSL constant tail",
)

motion_decl = "Texture2D<float4>   gMotion   : register(t3);  // resolve, accumulating: the game's motion vectors.\n"
s = replace_once(
    s,
    motion_decl,
    motion_decl
    + "#ifndef VK_MODE\n"
      "Texture2D<float4>   gExposure : register(t4);  // generated 1x1 exposure for encode/resolve\n"
      "#endif\n",
    "v2 exposure SRV",
)

luma_decl = "static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);\n"
effective_wp = r'''

float EffectiveWhitePoint()
{
    const float fallback = max(gWhitePoint, 1e-4);

#ifndef VK_MODE
    if (gUseExposureWhitePoint != 0)
    {
        const float exposure = gExposure.Load(int3(0, 0, 0)).r;
        if (!isfinite(exposure) || exposure <= 1e-8)
            return fallback;

        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;
        const float trim = clamp(gExposureTrim, 0.25, 4.0);
        const float whitePoint = preExposure / exposure * trim;

        if (isfinite(whitePoint) && whitePoint > 0.0)
            return clamp(whitePoint, 0.01, 4096.0);
    }
#endif

    return fallback;
}
'''
s = replace_once(s, luma_decl, luma_decl + effective_wp, "v2 effective white point")

s = replace_once(
    s,
    "        float3 display = SoftKnee(frame / max(gWhitePoint, 1e-4));\n",
    "        const float whitePoint = EffectiveWhitePoint();\n"
    "        float3 display = SoftKnee(frame / whitePoint);\n",
    "v2 encode white point",
)
s = replace_once(
    s,
    "    const float normScale = gPassthrough != 0 ? 1.0 : max(gWhitePoint, 1e-4);\n",
    "    const float whitePoint = EffectiveWhitePoint();\n"
    "    const float normScale = gPassthrough != 0 ? 1.0 : whitePoint;\n",
    "v2 resolve white point",
)
s = replace_once(
    s,
    "        result = float3(gWhitePoint, gWhitePoint, gWhitePoint);\n",
    "        result = float3(whitePoint, whitePoint, whitePoint);\n",
    "v2 comparison divider white point",
)

# The base patch uses an explicit flag. A 1x1 dispatch remains a copy as a compatibility safety net
# if this source is ever regenerated for Vulkan before its callers learn the new flag.
s = replace_once(
    s,
    "        if (gMeterCopiesExposure != 0)\n",
    "        if (gMeterCopiesExposure != 0 || (gWidth == 1 && gHeight == 1))\n",
    "v2 meter copy compatibility",
)
write(rel, s)

# The fifth D3D SRV argument was explicitly vestigial. Rename it without changing the signature shape.
rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.h"
s = read(rel)
s = replace_once(
    s,
    "                  // Vestigial. Fed to the slot the removed edit accumulator read its history from;\n"
    "                  // nothing reads it now and every caller passes nullptr. Kept only so the binding\n"
    "                  // table keeps its shape -- not evidence that temporal accumulation exists.\n"
    "                  ID3D12Resource* InPrevEdit, ID3D12Resource* OutTarget,\n",
    "                  // Fifth SRV. Normally null; GPU auto exposure binds its 1x1 texture here for\n"
    "                  // encode and resolve. The descriptor-table shape is unchanged.\n"
    "                  ID3D12Resource* InExposure, ID3D12Resource* OutTarget,\n",
    "v2 D3D12 header exposure SRV",
)
write(rel, s)

rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp"
s = read(rel)

# WhitePointSource: 0 manual, 1 game only, 2 automatic, 3 calibrated scan.
s = replace_once(
    s,
    "    if (cfg.DlssNrWhitePointSource.value_or_default() == 2)\n",
    "    if (cfg.DlssNrWhitePointSource.value_or_default() == 3)\n",
    "v4 shift scan source to index 3",
)

# Keep backend enforcement in sync with the UI: game exposure trim now reaches 10x.
s = replace_once(
    s,
    "std::clamp(cfg.DlssNrWhitePointTrim.value_or_default(), 0.25f, 4.0f)",
    "std::clamp(cfg.DlssNrWhitePointTrim.value_or_default(), 0.25f, 10.0f)",
    "v2 backend game trim max",
)

# Reuse the old fifth descriptor slot as t4 exposure.
s = replace_once(
    s,
    "ID3D12Resource* InPrevEdit, ID3D12Resource* OutTarget,",
    "ID3D12Resource* InExposure, ID3D12Resource* OutTarget,",
    "v2 D3D12 cpp exposure parameter",
)
s = replace_once(
    s,
    "InPrevEdit != nullptr ? InPrevEdit : InSource,",
    "InExposure != nullptr ? InExposure : InSource,",
    "v2 D3D12 cpp exposure binding",
)

# Parent semantics: selecting another white-point source disables both game exposure and our fallback.
s = replace_once(
    s,
    "    ID3D12Resource* nrExposure = (ID3D12Resource*) frame.ExposureTexture;\n"
    "    const bool nrExposureIsGame = nrExposure != nullptr;\n",
    "    const uint32_t whitePointSource = cfg.DlssNrWhitePointSource.value_or_default();\n"
    "    const bool gameExposureSelected = whitePointSource == 1;\n"
    "    const bool automaticExposureSelected = whitePointSource == 2;\n\n"
    "    // Sources are mutually exclusive: auto ignores game ExposureTexture; game source never falls back.\n"
    "    ID3D12Resource* nrExposure =\n"
    "        gameExposureSelected ? (ID3D12Resource*) frame.ExposureTexture : nullptr;\n"
    "    const bool nrExposureIsGame = nrExposure != nullptr;\n"
    "    bool usingAutoExposure = false;\n",
    "v2 exposure parent semantics",
)

# Calculate even with an older forwarder: composition itself can consume the 1x1 t4 texture.
s = replace_once(
    s,
    "    if (g_nr.setExposure != nullptr && nrExposure == nullptr && isHdrBuffer &&\n"
    "        g_nr.meter != nullptr && g_nr.autoExposure != nullptr)\n",
    "    if (automaticExposureSelected && isHdrBuffer &&\n"
    "        g_nr.meter != nullptr && g_nr.autoExposure != nullptr)\n",
    "v2 auto exposure gate",
)
s = replace_once(
    s,
    "        g_nr.autoExposureReadable = true;\n"
    "        nrExposure = g_nr.autoExposure;\n",
    "        g_nr.autoExposureReadable = true;\n"
    "        nrExposure = g_nr.autoExposure;\n"
    "        usingAutoExposure = true;\n",
    "v2 auto exposure active flag",
)

# Feed the same GPU-generated 1x1 value to encode and resolve so the trim affects the composition
# immediately, without a delayed CPU readback.
s = replace_once(
    s,
    "    encodeParams.WhitePoint = whitePoint;\n"
    "    encodeParams.Width = width;\n",
    "    encodeParams.WhitePoint = whitePoint;\n"
    "    encodeParams.PreExposure = frame.PreExposure;\n"
    "    encodeParams.ExposureTrim =\n"
    "        std::clamp(cfg.DlssNrAutoExposureTrim.value_or_default(), 0.25f, 4.0f);\n"
    "    encodeParams.UseExposureWhitePoint = usingAutoExposure ? 1u : 0u;\n"
    "    encodeParams.Width = width;\n",
    "v2 encode exposure constants",
)
s = replace_once(
    s,
    "    DispatchPass(cmdList, encodeParams, source, nullptr, nullptr, nullptr, nullptr, g_nr.colorCopy, g_nr.hdrCopy);\n",
    "    DispatchPass(cmdList, encodeParams, source, nullptr, nullptr, nullptr,\n"
    "                 usingAutoExposure ? g_nr.autoExposure : nullptr, g_nr.colorCopy, g_nr.hdrCopy);\n",
    "v2 encode exposure SRV",
)
s = replace_once(
    s,
    "    resolveParams.WhitePoint = whitePoint;\n",
    "    resolveParams.WhitePoint = whitePoint;\n"
    "    resolveParams.PreExposure = frame.PreExposure;\n"
    "    resolveParams.ExposureTrim =\n"
    "        std::clamp(cfg.DlssNrAutoExposureTrim.value_or_default(), 0.25f, 4.0f);\n"
    "    resolveParams.UseExposureWhitePoint = usingAutoExposure ? 1u : 0u;\n",
    "v2 resolve exposure constants",
)
s = replace_once(
    s,
    "    DispatchPass(cmdList, resolveParams, modelInput, work[answer], g_nr.hdrCopy, motionIn,\n"
    "                            nullptr, target, nullptr);\n",
    "    DispatchPass(cmdList, resolveParams, modelInput, work[answer], g_nr.hdrCopy, motionIn,\n"
    "                 usingAutoExposure ? g_nr.autoExposure : nullptr, target, nullptr);\n",
    "v2 resolve exposure SRV",
)
write(rel, s)

print("DLSS-NR UI + separate Automatic Exposure source v4 applied")
