# Splatoon 2 / TotK-runtime handoff

State at the end of the 2026-11-15 session. Read this first, then the documents it links.

## Repositories and branches

| What | Where |
|---|---|
| Port repo (this one) | `azlekayn/Splat2-ReTotK` (GitHub) / `wingrepo/Splat2-ReTotK` (Forgejo) |
| Active branch | `retotk-baseline` (pushed to both remotes) |
| Runtime baseline | `Muhammad1259-sigma/totk-recomp` @ `a32f709`, MIT, vendored at `baseline/totk-recomp/` |
| Other Splatoon 2 port | `bangmcpe3321/sp2decomp` (Windows/Vulkan). Our cross-port findings are **PR #7**; its open PRs #3–#6 are not ours to touch |

## Persistent data (outside the repo, never commit)

`/mnt/SSD Storage/Games/Ports/Switch/Splat2/`

| Path | What |
|---|---|
| `prod.keys` | keys (path only; values never printed or committed) |
| `work/base-nsp/exefs/` | `main`, `sdk`, `rtld`, `subsdk0..3`, `main.npdm`, `*.decompressed` |
| `work/base-nsp/romfs/` | 3.1 GB extracted RomFS |
| `work/img/` | `tools/nso.py` images: `main.bin/json`, `sdk`, `subsdk*`, `funcs_*.json` |
| `work/gen-totk/{main,sdk,subsdk0..3}` | **canonical** generated C (main 0 unhandled) |
| `work/gen-totk/{main-trace,main-before-jt,main-jt1,sdk-before-jt,sdk-jt1,sdk-nobase}` | older/diagnostic variants, keep only for A/B |
| `work/totk-linux/deps` | SDL3 shim dirs, static Opus, Vulkan-Headers 1.4.357, **`libshaderc/`** (built here) |
| `work/totk-linux/syslib` | linker inputs: `libvpx.a` (SteamRT/sniper copy) + `libshaderc_combined.a` (relative symlink) |
| `work/totk-linux/build-null`, `build-vk`, `build-trace` | null (headless), Vulkan, and traced builds |
| `work/totk-linux/obj-null`, `obj-trace` | generated-TU objects (shared by --obj across build dirs) |
| `work/logs/` | run logs (`boot-null-NN`, `vk-01`) |

## Lift coverage (vendored generator, measured on the retail base NSP)

| Module | Functions | Instructions | Unhandled | Disposition |
|---|---:|---:|---:|---|
| `main` | 114,173 (114,172 + 1 cold fragment) | 5,261,347 | **0** | lift |
| `sdk` | 14,429 (14,426 + 3 cold fragments) | 714,539 | 1,657 | HLE first (AES + halfword atomics) |
| `subsdk0` (`nv`/`nvn`) | 4,299 | 185,120 | 43 | HLE first |
| `subsdk1` (`nn::vi`) | 385 | 13,656 | 6 | HLE first |
| `subsdk2` | 76 | 10,643 | **0** | lift later |
| `subsdk3` | 496 | 41,514 | **0** | lift later |

Bases: `main 0x7100000000`, `sdk 0x7180000000`, `subsdk0 0x7200000000`, `subsdk1 0x7280000000`,
`subsdk2 0x7300000000`, `subsdk3 0x7380000000`.

## Generator: three local fixes (do not lose them)

In `baseline/totk-recomp/tools/recomp/gen.py`:

1. scalar `FADDP Sd, Vn.2S` (without it `main` has 15 unhandled instructions);
2. PIC jump tables in the `add d, d, base` form — the anchor is the *third* operand and is an
   `adrp`+`add` table base, not an `adr` label (`sdk 0x3ccd8`). `sdk` 0 → 270 tables, `main`
   0 → 1,108; `br` left to a runtime dispatch 648 → 378 (`sdk`), 7,468 → 6,360 (`main`);
3. functions synthesised at non-FDE `BL` targets — a function's cold half (`main 0x13a6f2c`,
   `sdk 0x871c8/0x87454/0x87468`).

Details and symptoms: `BOOT_SMOKE_NULL.md`; also written up for the other port in PR #7
(`RECOMP_GENERATOR_AND_SDK_CONTRACTS.md` there).

## Build (Podman only; nothing installed on the host)

`CC=clang CXX=clang++` must be set explicitly (default is `clang-19`). Paths must not contain
spaces; the work tree is mounted at `/w` inside the container.

```bash
# null (headless, no GPU)
python3 tools/recomp/mkninja_linux.py --null --gen /w/gen-totk/main \
    --syslib /w/totk-linux/syslib --out /w/totk-linux/build-null \
    --obj /w/totk-linux/obj-null --deps /w/totk-linux/deps --gen-opt -O1 --gen-pool 5
ninja -C /w/totk-linux/build-null -j10

# Vulkan (window)
python3 tools/recomp/mkninja_linux.py --gen /w/gen-totk/main \
    --syslib /w/totk-linux/syslib --sysinc /w/totk-linux/deps/libshaderc/include \
    --out /w/totk-linux/build-vk --obj /w/totk-linux/obj-null \
    --deps /w/totk-linux/deps --gen-opt -O1 --gen-pool 5
ninja -C /w/totk-linux/build-vk -j10
```

`--sysinc` is a local addition: the baseline assumed a distro shaderc whose headers are on the
default include path. `libshaderc_combined.a` (shaderc v2025.4, glslang + SPIRV-Tools merged,
19 MB) is built from source in the container; build notes are next to it.

Generated-TU cost at `-O1` on this host: ~11 s each, ~4.5 min for all 104.

## Run

```bash
# headless
TOTK_LIFT_ALL=1 TOTK_NVN_INT="0=53" TOTK_ROMFS=/w/base-nsp/romfs TOTK_IMG=/w/img \
    TOTK_HEADLESS=1 timeout -k 5 240 ./totk

# with a window (needs --device /dev/dri; wayland/X sockets; tell the user first)
podman run --rm -v "$PWD:/w:z" --device /dev/dri \
    --mount type=bind,source=/run/user/1000,destination=/run/user/1000 \
    -e XDG_RUNTIME_DIR=/run/user/1000 -e WAYLAND_DISPLAY=wayland-1 -e DISPLAY=:0 \
    -e XAUTHORITY=/run/user/1000/xauth_* -w /w/totk-linux/build-vk <image> bash -lc '… ./totk'
```

Debug env: `TOTK_TRACE_FS=1` (every file open), `TOTK_TRACE_STR=1` + `--trace <offs>`
(string-aware call trace), `TOTK_IND_LOG=1` (last 32 indirect calls on crash), `TOTK_TRACE_ALL=1`
(every import with `lr`).

## Where the boot gets to

Both builds boot and stay up:

```
DT_INIT → nninitStartup → init_array (1604) → nnMain
  game's own memory report (3328 MB non-system / 3248 MB root heap)
  NVN device (API 53 accepted) + window, swapchain 1280x720  [Vulkan build: Intel Arc MTL]
  presentation thread, audio renderer (32000 frames), romfs sound banks, ELink2/SLink2
  lifted nn::fontll text engine, layouts, nvn textures/pools
```

`[ld] ftab 114173 functions, 784 imports (258 HLE, 63 lifted sdk, 192 lifted-unbound, 271 stubbed)`
with `TOTK_LIFT_ALL=1`.

## Current blocker (first frame)

**The customize-page null is fixed (2026-11-15); the boot now advances well past it.** The root
cause was not a layout at all: our `nn::os::CreateThread` HLE never wrote the stack base into the
guest `nn::os::ThreadType` (offset `+0x50`), so `sead::MemUtil::isStack` (`main 0x13a1f30`) saw
every thread's region as `[0, size)` and returned 0 for *every* pointer. `Lp::UI::Impl::Name::init`
(`main 0x124351c`) uses that to decide copy-vs-share for control names; it therefore shared a
caller stack pointer as the control name, which dangled, and `findPartsControl` returned null for
every lookup (`/L_ItemBtn_00` was just the first). Fix (runtime only) in
`baseline/totk-recomp/runtime/hle_os_thread.cpp`:

```c
if (c->x[0]) *(u64*)(c->x[0] + 0x50) = c->x[3];   // CreateThread: ThreadType stack base
*(u64*)(tt + 0x50) = stack_lo;                     // main thread
```

Effect: `isStack` returns 1 for stack sources, the customize page constructs, and the fs trace goes
from 23 to ~93 unique layouts (`work/logs/boot-null-61.*`). Full write-up: `UI_BLOCKER_NOTES.md`
("SOLVED 2026-11-15"). The two earlier hypotheses (operation mode; the absent
`Cst_CustomizeDetail_00`) were both refuted with assets/traces there.

**The boot now runs a stable main loop with no crash.** After the `isStack` fix it reached
`nn::friends::Initialize` (its lifted body calls `ConnectToNamedPort("sm:")` and aborts) and then
`nn::time::GetDeviceLocationName`; those are services whose real bodies need kernel IPC no Linux
host has. Two follow-ups (runtime only):

- `runtime/hle_os_thread.cpp`: implement the missing auto-clear `nn::os::WaitEvent` /
  `TimedWaitEvent` / `TryWaitEvent` (the plain `EventType`, distinct from the System/Light/Timer
  events already HLE'd). They were `UNIMPL` and left the Pia scheduler spinning.
- `runtime/rt_main.cpp`: add `_ZN2nn7friends`, `_ZN2nn3pia`, `_ZN2nn3nex`, `_ZN2nn4time`,
  `_ZN2nn3err`, `_ZN2nn4diag` to the `TOTK_LIFT_ALL` service-exclusion list, so their bodies are not
  lifted (and abort on `sm:`).

- one more kernel gap kept the main thread parked at `nn::os::WaitThread`: `nn::os::JamMessageQueue`
  was `UNIMPL`, so a worker never got its stop message. `runtime/hle_os_thread.cpp` now implements
  `JamMessageQueue`/`TryJamMessageQueue` (push-front, mirroring the Light variant).

Result: the engine reaches `RootTask` init and its `SceneLoad` thread, starts the presentation
loop, and runs **without crashing**. With the `JamMessageQueue` fix the scene framework comes up
(`SceneLoadInCalc`, `SceneGeneralMain/Sub1/Sub2` threads) and the game issues its **first frame** —
`work/logs/boot-null-67.log`: `[nvn] first present (texture 0)` plus 69 recorded `nvnDraw*/nvnClear`
calls (headless/null backend records draws but has no visible output). Next: the Vulkan build for a
rendered frame (`build-vk`, Intel Arc, 1280x720 swapchain).

## Runtime work already done (all game-agnostic; TotK behaviour preserved)

`MemoryInfo` real layout (`+0x10` heap size, `+0x18` used, `+0x20` free); new
`runtime/hle_svc.cpp` (`svc::aarch64::lp64` layer; `ConnectToNamedPort` fails cleanly,
`OutputDebugString` surfaces the game's log and asserts); `TOTK_LIFT_ALL` with a service/IPC
namespace exclusion list; `nn::os` (`TrySendMessageQueue`, `TryReceiveMessageQueue`,
`TimedWaitSystemEvent`, 7-arg `CreateThread`, `SetThreadNamePointer`, `SdkAllocateTlsSlot`,
`FlushDataCache`); `nn::audio` SDK 3.x parameter layout + pre-5.x device names + pool state;
`nn::pl` shared-font state (1 = ready, never a null address); `nn::settings::eq`.

## Boundaries

- No game data, keys, saves, generated C or built binaries in the repository.
- Baseline is MIT; keep attribution. LAS is not used.
- Container builds only; tell the user before a game window opens.
- Do not disturb the other project's open PRs #3–#6.
