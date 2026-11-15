# Null-backend boot: Splatoon 2 reaches nnMain and its own engine init

First headless smoke run of the baseline runtime against Splatoon 2's lifted `main`. Null GPU
backend (no window, no Vulkan), `TOTK_IMG=work/img`, `TOTK_ROMFS=work/base-nsp/romfs`.
Logs from these runs live outside the repository in `work/logs/` (they contain memory sizes and
file names from the user's own dump, not game data).

## Build

```bash
# deps: SDL3 (shared, from the build container) + static Opus; libvpx.a from the SteamRT/sniper sysroot
tools/linux/build_deps.sh <deps>                  # SDL3 step skipped, opus + Vulkan-Headers built/charged
export CC=clang CXX=clang++                       # the container's clang 22 (mkninja defaults to clang-19)
python3 tools/recomp/mkninja_linux.py --null \
    --gen <work>/gen-totk/main --syslib <sniper>/usr/lib/x86_64-linux-gnu \
    --out <work>/totk-linux/build-null --obj <work>/totk-linux/obj-null --deps <work>/totk-linux/deps \
    --gen-opt -O1 --gen-pool 5
ninja -C <work>/totk-linux/build-null -j10
```

Build paths must not contain spaces: ninja splits `-I<path>` on them. The container sees the work
tree as `/w`, which is why the commands above use that form.

Generated-TU cost at `-O1` on this host: ~11 s per TU, ~4.5 min for `main`'s 88 + `sdk`'s 12.

## Where it gets to

```
[ld] ftab 114173 functions, 784 imports (258 HLE, 63 lifted sdk, 192 lifted-unbound, 271 stubbed)
[boot] DT_INIT 7100000024
[boot] nninitStartup 710019a3dc
[boot] init_array 1604 entries
[boot] nnMain entered (710019a3e0)
###  Application Start Time [03:12:14] ###
<><><><><><><> dumpMemoryInfo [ Application Start ] <><><><><><><>
3328 MB: HBMなどのシステム以外のアプリ領域
3248 MB  アプリのRootHeap + SDK用のAllocateMemoryBlock
...
[nvn] window with 3 textures                     (3 buffers, present interval 1)
[os] CreateThread ... Presentation Thread
[audio] frame 32000: 0 voices ...                (audio renderer running)
[pl] no shared font available: giving the engine an empty one
[imp] nn::fontll::ScalableFontEngine::GetKerning  (the real font engine, lifted)
```

It reaches its own sound-bank and `ELink2`/`SLink2` database loading and then text layout inside
`nnMain`. Latest blocker: a null dereference at `main+0x1d9530` (+0x1f0) after the font path.

## What had to change (all in `baseline/totk-recomp/`, all game-agnostic)

| File | Change |
|---|---|
| `runtime/hle_vi.cpp` | TotK's frame-delta hook (`main+0x7a83e4`) is now a **weak** reference: another game's `main` has no such address and the TU must still link |
| `runtime/hle_os_mem.cpp` | `MemoryInfo` uses the real layout (`+0x10` heap size, `+0x18` heap used, `+0x20` free). Zero there made Splatoon 2 reserve a **0-byte** main heap |
| `runtime/hle_os_thread.cpp` | `TrySendMessageQueue`, 7-arg `CreateThread`, `SetThreadNamePointer`, `SdkAllocateTlsSlot` |
| `runtime/hle_audio.cpp` | SDK 3.x `AudioRendererParameter` init/validate (real layout) and the pre-5.x device names; `GetMemoryPoolState` = attached |
| `runtime/hle_fs.cpp` | `nn::pl` shared fonts: state 1 = ready, never a null address (zeroed block → the engine falls back to romfs fonts) |
| `runtime/hle_svc.cpp` | **new**: the `svc::aarch64::lp64` layer a lifted sdk reaches, `svcConnectToNamedPort` returns "no such service", `svcOutputDebugString` surfaces the game's own log/asserts |
| `runtime/rt_main.cpp` | `TOTK_LIFT_ALL=1`: bind main's unimplemented imports to the sdk's real bodies (192 here), with a service-namespace exclusion list; `TOTK_IND_LOG=1` rings the last 32 indirect calls for crash reports |
| `runtime/rt.h` | `call_ind` feeds that ring |
| `tools/recomp/gen.py` | PIC jump tables in the `add d, d, base` form (anchor is the third operand and an `adrp` table base); functions synthesised at non-FDE BL targets (`main 0x13a6f2c`) |

## Generator impact

| | before | after |
|---|---:|---:|
| `sdk` jump tables resolved | 0 | 270 |
| `sdk` `br` left to runtime dispatch | 648 | 378 |
| `main` jump tables resolved | 0 | 1108 |
| `main` `br` left to runtime dispatch | 7468 | 6360 |
| `main` functions | 114172 | 114173 (+1 cold fragment) |
| `sdk` functions | 14426 | 14429 (+3 cold fragments) |

## Run recipe

```bash
TOTK_LIFT_ALL=1 TOTK_NVN_INT="0=53" \
TOTK_ROMFS=<work>/base-nsp/romfs TOTK_IMG=<work>/img TOTK_HEADLESS=1 \
    timeout -k 5 240 ./totk
```

`TOTK_NVN_INT="0=53"` is a stopgap: `nvnDeviceGetInteger(dev, 0)` is the NVN API **major**, and
Splatoon 2 requires 53 where TotK requires 55. It belongs in the game definition, not an env var.

## Next

1. Game definition: title/build ids, six modules, heap/alias/pool, 1280x720/60, NVN API 53, and
   `TOTK_LIFT_ALL` on by default for this title.
2. Vulkan build for the first visible frame (needs static `libshaderc_combined.a`; the sniper
   sysroot has glslang + SPIRV-Tools but no shaderc).
3. Clear the `main+0x1d9530` null dereference and keep walking the boot.
