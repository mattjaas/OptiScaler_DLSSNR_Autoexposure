from pathlib import Path
import re

HERE = Path(__file__).resolve()
CANDIDATES = [Path.cwd(), HERE.parent, HERE.parent.parent]
ROOT = next((p for p in CANDIDATES if (p / "OptiScaler").is_dir()), None)

if ROOT is None:
    raise RuntimeError("Run from the repository root, or keep this file under repo/tools/.")

REL = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp"
PATH = ROOT / REL
src = PATH.read_text(encoding="utf-8-sig")
original = src

if "PFN_NrSetExposure" not in src or "DlssNrMode_AutoExposure" not in (ROOT / "OptiScaler/shaders/dlssnr/DlssNr_Common.h").read_text(encoding="utf-8-sig"):
    raise RuntimeError(
        "Base GPU auto-exposure patch is not present. Run the earlier Auto Exposure patch first."
    )

if "AUTO FALLBACK ACTIVE" in src and "autoExposureStatsValid" in src:
    print("DLSS-NR auto-exposure diagnostics are already present.")
    raise SystemExit(0)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


# 1) Diagnostic state. Rendering does NOT consume these values.
src = replace_once(
    src,
    '''    // Same-frame GPU fallback. First channel is the standard NGX exposure value.
    ID3D12Resource* autoExposure = nullptr;
    bool autoExposureReadable = false;
    bool autoExposureAllocationTried = false;
''',
    '''    // Same-frame GPU fallback. First channel is the standard NGX exposure value.
    ID3D12Resource* autoExposure = nullptr;
    bool autoExposureReadable = false;
    bool autoExposureAllocationTried = false;

    // Delayed CPU-visible diagnostics only. Rendering continues to use the same-frame GPU value.
    float meterPreExposure[4] = { 1.0f, 1.0f, 1.0f, 1.0f };
    unsigned int meterSourceWidth[4] = {};
    unsigned int meterSourceHeight[4] = {};
    float autoExposureValue = 0.0f;
    float autoExposurePreExposure = 1.0f;
    float autoExposureAverageLuma = 0.0f;
    float autoExposureWhitePoint = 0.0f;
    bool autoExposureStatsValid = false;
''',
    "NrState diagnostics",
)

# 2) Carry PreExposure and source dimensions with each delayed readback slot.
src = replace_once(
    src,
    '''void CopyMeterToReadback(ID3D12GraphicsCommandList* cmdList, ID3D12Device* device,
                         bool exposureBound)
{
    const unsigned int slot = (unsigned int) (g_nr.meterFrames % 4);

    if (g_nr.meterReadback[slot] == nullptr)
        return;

    // Travels with the grid: read back three frames from now, alongside the tiles it describes.
    g_nr.meterExposureValid[slot] = exposureBound;
''',
    '''void CopyMeterToReadback(ID3D12GraphicsCommandList* cmdList, ID3D12Device* device,
                         bool exposureBound, float preExposure,
                         unsigned int sourceWidth, unsigned int sourceHeight)
{
    const unsigned int slot = (unsigned int) (g_nr.meterFrames % 4);

    if (g_nr.meterReadback[slot] == nullptr)
        return;

    // Travels with the grid: read back three frames from now, alongside the tiles it describes.
    g_nr.meterExposureValid[slot] = exposureBound;
    g_nr.meterPreExposure[slot] =
        std::isfinite(preExposure) && preExposure > 1e-6f ? preExposure : 1.0f;
    g_nr.meterSourceWidth[slot] = sourceWidth;
    g_nr.meterSourceHeight[slot] = sourceHeight;
''',
    "CopyMeterToReadback diagnostics metadata",
)

# 3) Replace old tile-0-only consumer with a consumer that still reads game exposure,
#    and additionally reconstructs the same weighted AverageLuma used by the GPU AUTO reduction.
pattern = re.compile(
    r"void ConsumeMeterReadback\(\)\n\{.*?\n\}\n\n// Forget everything the meter knows,",
    re.S,
)
match = pattern.search(src)
if match is None:
    raise RuntimeError("ConsumeMeterReadback: function not found")

consumer = r'''void ConsumeMeterReadback()
{
    if (g_nr.meterFrames < 4)
        return;

    const unsigned int slot = (unsigned int) (g_nr.meterFrames % 4);
    ID3D12Resource* buffer = g_nr.meterReadback[slot];

    if (buffer == nullptr)
        return;

    void* mapped = nullptr;
    D3D12_RANGE range { 0, kMeterBytes };

    if (FAILED(buffer->Map(0, &range, &mapped)) || mapped == nullptr)
        return;

    const float* values = (const float*) mapped;
    const bool carriesGameExposure = g_nr.meterExposureValid[slot];

    if (carriesGameExposure && std::isfinite(values[0]) && values[0] > 0.0f)
    {
        g_nr.gameExposure = values[0];
        g_nr.gamePreExposure = g_nr.meterPreExposure[slot];
    }
    else if (!carriesGameExposure)
    {
        const unsigned int sourceWidth = std::max(g_nr.meterSourceWidth[slot], 1u);
        const unsigned int sourceHeight = std::max(g_nr.meterSourceHeight[slot], 1u);

        double weightedLuma = 0.0;
        double totalPixels = 0.0;

        // Match mode 5 on the GPU: every 64x64 tile mean is weighted by the exact number
        // of source pixels represented by that tile. This makes the displayed diagnostic
        // AverageLuma correspond to the actual exposure formula used for rendering, only delayed.
        for (unsigned int ty = 0; ty < kDlssNrMeterGrid; ++ty)
        {
            const unsigned int y0 = (ty * sourceHeight) / kDlssNrMeterGrid;
            const unsigned int y1 = ((ty + 1) * sourceHeight) / kDlssNrMeterGrid;
            const unsigned int tileH = y1 > y0 ? y1 - y0 : 0;

            for (unsigned int tx = 0; tx < kDlssNrMeterGrid; ++tx)
            {
                const unsigned int x0 = (tx * sourceWidth) / kDlssNrMeterGrid;
                const unsigned int x1 = ((tx + 1) * sourceWidth) / kDlssNrMeterGrid;
                const unsigned int tileW = x1 > x0 ? x1 - x0 : 0;

                if (tileW == 0 || tileH == 0)
                    continue;

                const float tileMean = values[ty * kDlssNrMeterGrid + tx];

                if (!std::isfinite(tileMean) || tileMean < 0.0f)
                    continue;

                const double pixels = (double) tileW * (double) tileH;
                weightedLuma += (double) tileMean * pixels;
                totalPixels += pixels;
            }
        }

        const float preExposure =
            std::isfinite(g_nr.meterPreExposure[slot]) && g_nr.meterPreExposure[slot] > 1e-6f
                ? g_nr.meterPreExposure[slot]
                : 1.0f;

        if (totalPixels > 0.0)
        {
            const float averageBufferLuma = (float) (weightedLuma / totalPixels);
            const float averageSceneLuma = averageBufferLuma / preExposure;

            if (std::isfinite(averageSceneLuma) && averageSceneLuma > 1e-8f)
            {
                const float exposure = 0.18f / std::max(averageSceneLuma * 0.82f, 1e-8f);

                if (std::isfinite(exposure) && exposure > 1e-8f)
                {
                    const float trim = std::clamp(
                        Config::Instance()->DlssNrWhitePointTrim.value_or_default(), 0.25f, 4.0f);

                    g_nr.autoExposureAverageLuma = averageSceneLuma;
                    g_nr.autoExposureValue = exposure;
                    g_nr.autoExposurePreExposure = preExposure;
                    g_nr.autoExposureWhitePoint = std::clamp(
                        (preExposure / exposure) * trim, 0.01f, 4096.0f);
                    g_nr.autoExposureStatsValid = true;
                }
            }
        }
    }

    D3D12_RANGE nothingWritten { 0, 0 };
    buffer->Unmap(0, &nothingWritten);
}

// Forget everything the meter knows,'''

src = src[: match.start()] + consumer + src[match.end() :]

# 4) Clear diagnostic slots when the exposure source is toggled.
src = replace_once(
    src,
    '''void InvalidateExposureMeter()
{
    g_nr.gameExposure = 0.0f;

    for (bool& valid : g_nr.meterExposureValid)
        valid = false;

    // Re-arms the `< 4` guard in ConsumeMeterReadback, so nothing is read back until four frames
''',
    '''void InvalidateExposureMeter()
{
    g_nr.gameExposure = 0.0f;
    g_nr.gamePreExposure = 1.0f;
    g_nr.autoExposureValue = 0.0f;
    g_nr.autoExposurePreExposure = 1.0f;
    g_nr.autoExposureAverageLuma = 0.0f;
    g_nr.autoExposureWhitePoint = 0.0f;
    g_nr.autoExposureStatsValid = false;

    for (unsigned int i = 0; i < 4; ++i)
    {
        g_nr.meterExposureValid[i] = false;
        g_nr.meterPreExposure[i] = 1.0f;
        g_nr.meterSourceWidth[i] = 0;
        g_nr.meterSourceHeight[i] = 0;
    }

    // Re-arms the `< 4` guard in ConsumeMeterReadback, so nothing is read back until four frames
''',
    "InvalidateExposureMeter diagnostics",
)

# 5) Update the game's exposure courier readback call.
src = replace_once(
    src,
    '''        CopyMeterToReadback(cmdList, device, true);
        ConsumeMeterReadback();
''',
    '''        const D3D12_RESOURCE_DESC gameExposureSourceDesc = source->GetDesc();
        CopyMeterToReadback(
            cmdList, device, true,
            std::isfinite(frame.PreExposure) && frame.PreExposure > 1e-6f ? frame.PreExposure : 1.0f,
            (unsigned int) gameExposureSourceDesc.Width, gameExposureSourceDesc.Height);
        ConsumeMeterReadback();
''',
    "game exposure readback call",
)

# 6) On AUTO fallback frames copy the 64x64 grid to the delayed diagnostic ring BEFORE reducing
#    it to 1x1. This copy does not feed the render path.
src = replace_once(
    src,
    '''        DispatchPass(cmdList, meterParams, source, nullptr, nullptr, nullptr, nullptr,
                     g_nr.meter, nullptr);
        Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);

        // 2) 64x64 tile means -> one exposure value.
''',
    '''        DispatchPass(cmdList, meterParams, source, nullptr, nullptr, nullptr, nullptr,
                     g_nr.meter, nullptr);
        Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);

        const D3D12_RESOURCE_DESC autoExposureSourceDesc = source->GetDesc();
        CopyMeterToReadback(cmdList, device, false, framePreExposure,
                            (unsigned int) autoExposureSourceDesc.Width,
                            autoExposureSourceDesc.Height);
        ConsumeMeterReadback();

        // 2) 64x64 tile means -> one exposure value.
''',
    "auto exposure diagnostic readback",
)

# 7) Unambiguous log signal plus delayed numeric diagnostics.
src = replace_once(
    src,
    '''    // CPU WhitePoint stays the manual / scan fallback. When an exposure resource is active,
    // Encode and Resolve override this value from t4 on the GPU.
    const float whitePoint = ResolveWhitePoint(cfg, isHdrBuffer);

    DlssNrConstants encodeParams {};
''',
    '''    // CPU WhitePoint stays the manual / scan fallback. When an exposure resource is active,
    // Encode and Resolve override this value from t4 on the GPU.
    const float whitePoint = ResolveWhitePoint(cfg, isHdrBuffer);

    if (isHdrBuffer)
    {
        enum class ExposureSource : unsigned int { None, Game, Auto };
        const ExposureSource sourceNow =
            activeExposure != nullptr
                ? (activeExposureIsGame ? ExposureSource::Game : ExposureSource::Auto)
                : ExposureSource::None;

        static ExposureSource lastSource = ExposureSource::None;
        static unsigned long long lastAutoDiagFrame = 0;

        const bool periodicAutoDiagnostic =
            sourceNow == ExposureSource::Auto && g_nr.autoExposureStatsValid &&
            g_nr.meterFrames >= lastAutoDiagFrame + 120ull;

        if (sourceNow != lastSource || periodicAutoDiagnostic)
        {
            lastSource = sourceNow;

            if (sourceNow == ExposureSource::Game)
            {
                LOG_INFO("DLSS-NR exposure source: GAME (game ExposureTexture active)");
            }
            else if (sourceNow == ExposureSource::Auto)
            {
                if (g_nr.autoExposureStatsValid)
                {
                    LOG_INFO(
                        "DLSS-NR exposure source: AUTO FALLBACK ACTIVE | AverageLuma {:.6f} | Exposure {:.6f} | PreExposure {:.6f} | effective WhitePoint {:.6f} | diagnostics delayed 4 frames",
                        g_nr.autoExposureAverageLuma, g_nr.autoExposureValue,
                        g_nr.autoExposurePreExposure, g_nr.autoExposureWhitePoint);
                    lastAutoDiagFrame = g_nr.meterFrames;
                }
                else
                {
                    LOG_INFO("DLSS-NR exposure source: AUTO FALLBACK ACTIVE | diagnostic readback warming up");
                }
            }
            else if (exposureSettingOn)
            {
                LOG_INFO("DLSS-NR exposure source: NONE | manual/scan fallback");
            }
        }
    }

    DlssNrConstants encodeParams {};
''',
    "AUTO fallback log diagnostics",
)

if src == original:
    print("No changes required.")
else:
    PATH.write_text(src, encoding="utf-8", newline="\n")
    print("Added DLSS-NR Auto Exposure diagnostics to:")
    print(f"  {REL}")
