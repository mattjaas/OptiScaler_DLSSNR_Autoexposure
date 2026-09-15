#!/usr/bin/env python3
# DLSS-NR GPU auto-exposure patch for:
#   mattjaas/OptiScaler_DLSSNR_Autoexposure
#   branch: dlss-neural-rendering
#
# The patcher is deliberately strict: every edit must match exactly once.
# If the fork changes underneath it, the build fails instead of producing
# a half-patched binary.

from pathlib import Path
import re

HERE = Path(__file__).resolve()
CANDIDATES = [Path.cwd(), HERE.parent, HERE.parent.parent]
ROOT = next((p for p in CANDIDATES if (p / "OptiScaler").is_dir()), None)

if ROOT is None:
    raise RuntimeError("Run from the repository root, or keep this file under repo/tools/.")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 regex match, found {count}")
    return out


changed = []

# -----------------------------------------------------------------------------
# DlssNr_Common.h
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/DlssNr_Common.h"
s = read(rel)

if "DlssNrMode_AutoExposure" not in s:
    s = replace_once(
        s,
        '''    DlssNrMode_Meter = 3,      // the exposure texture -> tile (0,0), for the white point
    DlssNrMode_Calibrate = 4   // the untouched frame -> a grid of tile peak luminances
''',
        '''    DlssNrMode_Meter = 3,      // exposure copy, or frame -> 64x64 tile luminance means
    DlssNrMode_Calibrate = 4,  // the untouched frame -> a grid of tile peak luminances
    DlssNrMode_AutoExposure = 5 // 64x64 tile means -> NVIDIA-style 1x1 exposure
''',
        "DlssNrMode enum",
    )

    s = replace_once(
        s,
        '''    float DebugScale;
};
''',
        '''    float DebugScale;

    // D3D12 GPU auto exposure. Appended so all existing offsets remain unchanged.
    float PreExposure;
    float ExposureTrim;
    uint32_t ExposureSourceWidth;
    uint32_t ExposureSourceHeight;
    uint32_t UseExposureTexture;
    uint32_t MeterCopiesExposure;
};
''',
        "DlssNrConstants tail",
    )

    write(rel, s)
    changed.append(rel)

# -----------------------------------------------------------------------------
# DlssNr_Dx12.h: fallback adds another compute dispatch, keep ring headroom.
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.h"
s = read(rel)

if "#define DLSSNR_NUM_OF_HEAPS 64" not in s:
    s = replace_once(
        s,
        '''// restores eight frames at five dispatches. If a sixth is ever added, raise this with it rather than
// spending the margin again.
#define DLSSNR_NUM_OF_HEAPS 48
''',
        '''// restores eight frames at five dispatches. Auto exposure adds a sixth dispatch on fallback frames,
// so keep the safety margin instead of consuming it.
#define DLSSNR_NUM_OF_HEAPS 64
''',
        "D3D12 descriptor ring size",
    )
    write(rel, s)
    changed.append(rel)

# -----------------------------------------------------------------------------
# dlssnr.hlsl
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/precompile/dlssnr.hlsl"
s = read(rel)

if "gUseExposureTexture" not in s:
    s = replace_once(
        s,
        '''    uint  gTransfer;     // 0 classic, 1 matched residual -- how a below-size model comes back
    float gDebugScale;   // what the debug views are scaled by, held still while the meter moves
};
''',
        '''    uint  gTransfer;     // 0 classic, 1 matched residual -- how a below-size model comes back
    float gDebugScale;   // what the debug views are scaled by, held still while the meter moves

    // GPU auto exposure. Appended so every existing constant keeps its offset.
    float gPreExposure;
    float gExposureTrim;
    uint  gExposureSourceWidth;
    uint  gExposureSourceHeight;
    uint  gUseExposureTexture;
    uint  gMeterCopiesExposure;
};
''',
        "HLSL constants tail",
    )

    s = replace_once(
        s,
        '''#ifdef VK_MODE
[[vk::binding(4, 0)]]
#endif
Texture2D<float4>   gMotion   : register(t3);  // resolve, accumulating: the game's motion vectors.
#ifdef VK_MODE
[[vk::binding(5, 0)]]
#endif
RWTexture2D<float4> gTarget   : register(u0);  // encode: the proxy. resolve: the frame.
''',
        '''#ifdef VK_MODE
[[vk::binding(4, 0)]]
#endif
Texture2D<float4>   gMotion   : register(t3);  // resolve: the game's motion vectors.

// D3D12 already allocates five SRVs; t4 was the vestigial accumulator-history slot.
// Keep Vulkan's descriptor layout unchanged.
#ifndef VK_MODE
Texture2D<float4>   gExposure : register(t4);  // game or GPU-generated 1x1 exposure.
#endif

#ifdef VK_MODE
[[vk::binding(5, 0)]]
#endif
RWTexture2D<float4> gTarget   : register(u0);  // encode: the proxy. resolve: the frame.
''',
        "D3D12 exposure SRV",
    )

    helper = r'''
// White point used by both Encode and Resolve.
//
// The CPU value remains the manual / scan fallback. On D3D12, when a real exposure
// resource is available, both passes derive the divisor from the SAME 1x1 value.
float CompositionWhitePoint()
{
    float whitePoint = max(gWhitePoint, 1e-4);

#ifndef VK_MODE
    if (gUseExposureTexture != 0 && gPassthrough == 0)
    {
        const float exposure = gExposure.Load(int3(0, 0, 0)).r;
        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;
        const float trim =
            (isfinite(gExposureTrim) && gExposureTrim > 0.0)
                ? clamp(gExposureTrim, 0.25, 4.0)
                : 1.0;

        if (isfinite(exposure) && exposure > 1e-8)
            whitePoint = clamp((preExposure / exposure) * trim, 0.01, 4096.0);
    }
#endif

    return max(whitePoint, 1e-4);
}

'''
    s = replace_once(
        s,
        '''[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
''',
        helper + '''[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
''',
        "CompositionWhitePoint helper",
    )

    auto_mode = r'''    // Reduce the 64x64 meter into NVIDIA's DLSS exposure formula.
    //
    // The meter stores one arithmetic mean per tile. Weighting by each tile's exact
    // source-pixel area reconstructs the arithmetic AverageLuma of the entire source.
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
            const uint tileH = y1 > y0 ? y1 - y0 : 0u;

            [loop] for (uint tx = 0; tx < 64u; ++tx)
            {
                const uint x0 = (tx * srcW) / 64u;
                const uint x1 = ((tx + 1u) * srcW) / 64u;
                const uint tileW = x1 > x0 ? x1 - x0 : 0u;

                if (tileW == 0u || tileH == 0u)
                    continue;

                const float pixels = (float) tileW * (float) tileH;
                const float tileMean =
                    max(SanitizeFinite(gSource.Load(int3(tx, ty, 0)).r, 0.0), 0.0);

                weightedLuma += tileMean * pixels;
                totalPixels += pixels;
            }
        }

        const float averageBufferLuma =
            totalPixels > 0.0 ? weightedLuma / totalPixels : 0.0;

        const float preExposure =
            (isfinite(gPreExposure) && gPreExposure > 1e-6) ? gPreExposure : 1.0;

        // buffer = scene * PreExposure
        const float averageSceneLuma = averageBufferLuma / preExposure;

        // NVIDIA DLSS Programming Guide:
        // Exposure = MidGray / (AverageLuma * (1 - MidGray)), MidGray = 0.18.
        float exposure =
            averageSceneLuma > 1e-8
                ? 0.18 / (averageSceneLuma * 0.82)
                : 1.0;

        if (!isfinite(exposure) || exposure <= 0.0)
            exposure = 1.0;

        exposure = clamp(exposure, 1e-6, 1e6);
        gTarget[uint2(0, 0)] = float4(exposure, 0.0, 0.0, 1.0);
        return;
    }

'''
    s = replace_once(
        s,
        '''    if (gMode == 4)
''',
        auto_mode + '''    if (gMode == 4)
''',
        "auto-exposure reduction mode",
    )

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
        // Preserve the old game-exposure courier. AUTO sets this flag to zero and
        // uses the same mode as a true 64x64 luminance grid, including tile (0,0).
        if (gMeterCopiesExposure != 0)
        {
            if (id.x == 0 && id.y == 0)
                gTarget[id.xy] = float4(gMotion.Load(int3(0, 0, 0)).r, 0.0, 0.0, 1.0);

            return;
        }

        uint fullW, fullH;
'''
    s = replace_once(s, old_meter_head, new_meter_head, "meter mode split")

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
    new_sampling = r'''        // Exact arithmetic tile mean. Across 4096 threads every source pixel is
        // read exactly once; mode 5 weights the tile means by exact tile area.
        float sum = 0.0;
        uint taken = 0;

        [loop] for (uint ty = ty0; ty < max(ty1, ty0 + 1u); ++ty)
        {
            [loop] for (uint tx = tx0; tx < max(tx1, tx0 + 1u); ++tx)
            {
                const float3 c =
                    max(gSource.Load(int3(min(tx, fullW - 1u), min(ty, fullH - 1u), 0)).rgb, 0.0);
                const float luma = dot(c, kLuma);

                sum += isfinite(luma) ? max(luma, 0.0) : 0.0;
                ++taken;
            }
        }

        gTarget[id.xy] = float4(taken > 0u ? sum / (float) taken : 0.0, 0.0, 0.0, 1.0);
'''
    s = replace_once(s, old_sampling, new_sampling, "exact AverageLuma tile means")

    s = replace_once(
        s,
        '''        float3 display = SoftKnee(frame / max(gWhitePoint, 1e-4));
''',
        '''        const float compositionWhitePoint = CompositionWhitePoint();
        float3 display = SoftKnee(frame / compositionWhitePoint);
''',
        "encode white point",
    )

    s = replace_once(
        s,
        '''    const float normScale = gPassthrough != 0 ? 1.0 : max(gWhitePoint, 1e-4);
''',
        '''    const float normScale = gPassthrough != 0 ? 1.0 : CompositionWhitePoint();
''',
        "resolve white point",
    )

    write(rel, s)
    changed.append(rel)

# -----------------------------------------------------------------------------
# Forwarder: standard NGX ExposureTexture + DLSS.Pre.Exposure.
# -----------------------------------------------------------------------------
rel = "OptiScaler/dlssnr/forwarder/dlssnr_forwarder.cpp"
s = read(rel)

if "dlssnr_call_set_exposure" not in s:
    marker = '''// Inputs NVIDIA's own Streamline plugin sets that the positional exports predate: the model's global
'''
    setter = r'''// Standard NGX exposure inputs.
//
// Separate optional export so the evaluate ABI does not change. The parameter block
// persists, therefore null is written too so a generated texture cannot go stale.
__declspec(dllexport) void dlssnr_call_set_exposure(void *capabilityParams,
                                                    ID3D12Resource *exposure,
                                                    float preExposure) {
    if (!capabilityParams) {
        return;
    }

    setResource(capabilityParams, "ExposureTexture", exposure);
    setFloat(capabilityParams, "DLSS.Pre.Exposure",
             (preExposure > 1e-6f) ? preExposure : 1.0f);
}

'''
    s = replace_once(s, marker, setter + marker, "forwarder exposure export")
    write(rel, s)
    changed.append(rel)

# -----------------------------------------------------------------------------
# D3D12 host.
# -----------------------------------------------------------------------------
rel = "OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp"
s = read(rel)

if "PFN_NrSetExposure" not in s:
    s = replace_once(
        s,
        '''using PFN_NrSetExtras = void(__cdecl*) (void*, float, ID3D12Resource*, ID3D12Resource*, ID3D12Resource*,
                                        unsigned int, unsigned int, unsigned int, unsigned int);
using PFN_NrSetFloatSlot = void(__cdecl*) (int);
''',
        '''using PFN_NrSetExtras = void(__cdecl*) (void*, float, ID3D12Resource*, ID3D12Resource*, ID3D12Resource*,
                                        unsigned int, unsigned int, unsigned int, unsigned int);
using PFN_NrSetExposure = void(__cdecl*) (void*, ID3D12Resource*, float);
using PFN_NrSetFloatSlot = void(__cdecl*) (int);
''',
        "PFN_NrSetExposure typedef",
    )

    s = replace_once(
        s,
        '''    PFN_NrSetExtras setExtras = nullptr;
    PFN_NrSetFloatSlot setFloatSlot = nullptr;
''',
        '''    PFN_NrSetExtras setExtras = nullptr;
    PFN_NrSetExposure setExposure = nullptr;
    PFN_NrSetFloatSlot setFloatSlot = nullptr;
''',
        "NrState exposure setter",
    )

    s = replace_once(
        s,
        '''    ID3D12Resource* meter = nullptr;
    ID3D12Resource* meterReadback[4] = {};
''',
        '''    ID3D12Resource* meter = nullptr;
    ID3D12Resource* meterReadback[4] = {};

    // Same-frame GPU fallback. First channel is the standard NGX exposure value.
    ID3D12Resource* autoExposure = nullptr;
    bool autoExposureReadable = false;
    bool autoExposureAllocationTried = false;
''',
        "NrState auto exposure resource",
    )

    s = replace_once(
        s,
        '''    g_nr.setExtras = (PFN_NrSetExtras) GetProcAddress(g_nr.forwarder, "dlssnr_call_set_extras");
    g_nr.setFloatSlot = (PFN_NrSetFloatSlot) GetProcAddress(g_nr.forwarder, "dlssnr_call_set_float_slot");
''',
        '''    g_nr.setExtras = (PFN_NrSetExtras) GetProcAddress(g_nr.forwarder, "dlssnr_call_set_extras");
    g_nr.setExposure =
        (PFN_NrSetExposure) GetProcAddress(g_nr.forwarder, "dlssnr_call_set_exposure");
    g_nr.setFloatSlot = (PFN_NrSetFloatSlot) GetProcAddress(g_nr.forwarder, "dlssnr_call_set_float_slot");
''',
        "resolve forwarder exposure export",
    )

    allocation_anchor = '''        if (g_nr.meter != nullptr)
            LOG_INFO("DLSS-NR: white point meter up, {}x{} tiles", kDlssNrMeterGrid, kDlssNrMeterGrid);
    }

    // On an engine that needs its compute state put back'''
    allocation_replacement = '''        if (g_nr.meter != nullptr)
            LOG_INFO("DLSS-NR: white point meter up, {}x{} tiles", kDlssNrMeterGrid, kDlssNrMeterGrid);
    }

    if (!g_nr.autoExposureAllocationTried)
    {
        g_nr.autoExposureAllocationTried = true;

        // R32_FLOAT keeps the reduction precise and is valid as a typed UAV. NGX uses
        // the first channel of ExposureTexture.
        g_nr.autoExposure = CreateScratch(device, DXGI_FORMAT_R32_FLOAT, 1, 1);
        g_nr.autoExposureReadable = false;

        if (g_nr.autoExposure != nullptr)
            LOG_INFO("DLSS-NR: same-frame GPU auto-exposure fallback is available");
        else
            LOG_WARN("DLSS-NR: could not allocate the 1x1 GPU auto-exposure texture");
    }

    // On an engine that needs its compute state put back'''
    s = replace_once(s, allocation_anchor, allocation_replacement, "auto exposure allocation")

    pattern = (
        r'    const bool wantExposure = exposureSettingOn && frame\.ExposureTexture != nullptr;\n'
        r'.*?'
        r'    g_nr\.gamePreExposure = frame\.PreExposure;\n\n'
        r'    const float whitePoint = ResolveWhitePoint\(cfg, isHdrBuffer\);\n'
    )

    replacement = r'''    auto* gameExposureTexture = (ID3D12Resource*) frame.ExposureTexture;
    const bool wantGameExposure = exposureSettingOn && gameExposureTexture != nullptr;

    const D3D12_RESOURCE_STATES exposureArrival =
        cfg.ExposureResourceBarrier.has_value()
            ? (D3D12_RESOURCE_STATES) cfg.ExposureResourceBarrier.value()
            : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

    // Keep the old CPU-visible game-exposure courier for diagnostics/menu. Composition itself
    // no longer waits for the readback: when present, the same frame's 1x1 texture is read directly.
    if (g_nr.meter != nullptr && wantGameExposure)
    {
        DlssNrConstants meterParams {};
        meterParams.Mode = DlssNrMode_Meter;
        meterParams.Width = 1;
        meterParams.Height = 1;
        meterParams.MeterCopiesExposure = 1;

        Barrier(cmdList, source, sourceIdle, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        Barrier(cmdList, gameExposureTexture, exposureArrival,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        DispatchPass(cmdList, meterParams, source, nullptr, nullptr, gameExposureTexture, nullptr,
                     g_nr.meter, nullptr);

        Barrier(cmdList, gameExposureTexture, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                exposureArrival);
        Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);

        CopyMeterToReadback(cmdList, device, true);
        ConsumeMeterReadback();
    }

    const float framePreExposure =
        std::isfinite(frame.PreExposure) && frame.PreExposure > 1e-6f
            ? frame.PreExposure
            : 1.0f;

    g_nr.gamePreExposure = framePreExposure;

    // Select one exposure BEFORE Encode. That same 1x1 value is used by Encode, all NR
    // passes (through NGX), and Resolve. It is never recalculated between Multipass passes.
    ID3D12Resource* activeExposure = isHdrBuffer ? gameExposureTexture : nullptr;
    bool activeExposureIsGame = activeExposure != nullptr;

    // The generated value is useful to the composition and may also be consumed by NGX
    // itself through the standard ExposureTexture parameter.
    const bool needAutoExposure =
        isHdrBuffer && activeExposure == nullptr && g_nr.meter != nullptr &&
        g_nr.autoExposure != nullptr && (exposureSettingOn || g_nr.setExposure != nullptr);

    if (needAutoExposure)
    {
        // 1) Original linear HDR -> exact 64x64 tile arithmetic means.
        DlssNrConstants meterParams {};
        meterParams.Mode = DlssNrMode_Meter;
        meterParams.Width = kDlssNrMeterGrid;
        meterParams.Height = kDlssNrMeterGrid;
        meterParams.MeterCopiesExposure = 0;

        Barrier(cmdList, source, sourceIdle, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        DispatchPass(cmdList, meterParams, source, nullptr, nullptr, nullptr, nullptr,
                     g_nr.meter, nullptr);
        Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);

        // 2) 64x64 tile means -> one exposure value.
        Barrier(cmdList, g_nr.meter, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        if (g_nr.autoExposureReadable)
            Barrier(cmdList, g_nr.autoExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

        const D3D12_RESOURCE_DESC exposureSourceDesc = source->GetDesc();

        DlssNrConstants exposureParams {};
        exposureParams.Mode = DlssNrMode_AutoExposure;
        exposureParams.Width = 1;
        exposureParams.Height = 1;
        exposureParams.PreExposure = framePreExposure;
        exposureParams.ExposureSourceWidth = (unsigned int) exposureSourceDesc.Width;
        exposureParams.ExposureSourceHeight = exposureSourceDesc.Height;

        DispatchPass(cmdList, exposureParams, g_nr.meter, nullptr, nullptr, nullptr, nullptr,
                     g_nr.autoExposure, nullptr);

        Barrier(cmdList, g_nr.meter, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Barrier(cmdList, g_nr.autoExposure, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        g_nr.autoExposureReadable = true;
        activeExposure = g_nr.autoExposure;
        activeExposureIsGame = false;
    }

    const bool useExposureForComposition =
        exposureSettingOn && isHdrBuffer && activeExposure != nullptr;

    const float exposureTrim =
        std::clamp(cfg.DlssNrWhitePointTrim.value_or_default(), 0.25f, 4.0f);

    // CPU WhitePoint stays the manual / scan fallback. When an exposure resource is active,
    // Encode and Resolve override this value from t4 on the GPU.
    const float whitePoint = ResolveWhitePoint(cfg, isHdrBuffer);
'''

    s = regex_once(s, pattern, replacement, "game/auto exposure block")

    s = replace_once(
        s,
        '''    encodeParams.WhitePoint = whitePoint;
    // Match only takes effect once a fit exists; until then the table is empty and the shader would
''',
        '''    encodeParams.WhitePoint = whitePoint;
    encodeParams.PreExposure = framePreExposure;
    encodeParams.ExposureTrim = exposureTrim;
    encodeParams.UseExposureTexture = useExposureForComposition ? 1u : 0u;
    // Match only takes effect once a fit exists; until then the table is empty and the shader would
''',
        "encode exposure constants",
    )

    s = replace_once(
        s,
        '''    Barrier(cmdList, source, sourceIdle, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    DispatchPass(cmdList, encodeParams, source, nullptr, nullptr, nullptr, nullptr, g_nr.colorCopy, g_nr.hdrCopy);

    Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);
''',
        '''    Barrier(cmdList, source, sourceIdle, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    if (useExposureForComposition && activeExposureIsGame)
        Barrier(cmdList, activeExposure, exposureArrival,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    // The fifth D3D12 SRV slot is the removed accumulator-history slot; it now carries exposure.
    DispatchPass(cmdList, encodeParams, source, nullptr, nullptr, nullptr,
                 useExposureForComposition ? activeExposure : nullptr,
                 g_nr.colorCopy, g_nr.hdrCopy);

    if (useExposureForComposition && activeExposureIsGame)
        Barrier(cmdList, activeExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                exposureArrival);

    Barrier(cmdList, source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, sourceIdle);
''',
        "encode exposure binding",
    )

    s = replace_once(
        s,
        '''    if (g_ngxTime != nullptr)
        g_ngxTime->Start(cmdList);

    int result = NVSDK_NGX_Result_Success;
''',
        '''    // Standard NGX exposure for Neural Rendering itself. One value is left in the
    // capability block for the whole Multipass chain.
    if (g_nr.setExposure != nullptr)
        g_nr.setExposure(g_nr.capabilityParams, isHdrBuffer ? activeExposure : nullptr,
                         framePreExposure);

    const bool modelExposureNeedsBarrier =
        g_nr.setExposure != nullptr && isHdrBuffer && activeExposureIsGame &&
        activeExposure != nullptr;

    if (modelExposureNeedsBarrier)
        Barrier(cmdList, activeExposure, exposureArrival,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    if (g_ngxTime != nullptr)
        g_ngxTime->Start(cmdList);

    int result = NVSDK_NGX_Result_Success;
''',
        "NGX exposure setup",
    )

    s = replace_once(
        s,
        '''    if (g_ngxTime != nullptr)
        g_ngxTime->End(cmdList);

    g_nr.reset = false;
''',
        '''    if (g_ngxTime != nullptr)
        g_ngxTime->End(cmdList);

    if (modelExposureNeedsBarrier)
        Barrier(cmdList, activeExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                exposureArrival);

    // The capability block is shared with the game's own NGX. Do not leave our generated
    // resource behind after the NR chain.
    if (g_nr.setExposure != nullptr)
        g_nr.setExposure(g_nr.capabilityParams, gameExposureTexture, framePreExposure);

    g_nr.reset = false;
''',
        "NGX exposure restore",
    )

    s = replace_once(
        s,
        '''        resolveParams.WhitePoint = whitePoint;
        resolveParams.Width = width;
''',
        '''        resolveParams.WhitePoint = whitePoint;
        resolveParams.PreExposure = framePreExposure;
        resolveParams.ExposureTrim = exposureTrim;
        resolveParams.UseExposureTexture = useExposureForComposition ? 1u : 0u;
        resolveParams.Width = width;
''',
        "resolve exposure constants",
    )

    s = replace_once(
        s,
        '''        setWork(answer, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        DispatchPass(cmdList, resolveParams, modelInput, work[answer], g_nr.hdrCopy, motionIn,
                            nullptr, target, nullptr);
        setWork(answer, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
''',
        '''        setWork(answer, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        if (useExposureForComposition && activeExposureIsGame)
            Barrier(cmdList, activeExposure, exposureArrival,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        DispatchPass(cmdList, resolveParams, modelInput, work[answer], g_nr.hdrCopy, motionIn,
                     useExposureForComposition ? activeExposure : nullptr, target, nullptr);

        if (useExposureForComposition && activeExposureIsGame)
            Barrier(cmdList, activeExposure, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    exposureArrival);

        setWork(answer, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
''',
        "resolve exposure binding",
    )

    s = replace_once(
        s,
        '''    if (g_nr.meter != nullptr)
    {
        g_nr.meter->Release();
        g_nr.meter = nullptr;
    }

    if (g_nr.calib != nullptr)
''',
        '''    if (g_nr.meter != nullptr)
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
    g_nr.autoExposureAllocationTried = false;

    if (g_nr.calib != nullptr)
''',
        "auto exposure shutdown",
    )

    write(rel, s)
    changed.append(rel)

if not changed:
    print("DLSS-NR auto exposure: source already appears patched.")
else:
    print("DLSS-NR auto exposure patch applied:")
    for path in changed:
        print("  " + path)
