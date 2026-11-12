#!/usr/bin/env python3
"""Instrument a render target for passes whose render area or scissor is smaller than the image: NX_CLEAR_AREA.

WHY IT EXISTS.  The news screen's panel flicker has a signature that is invisible to every frame-windowed trace:
on rare frames the composite `6a00ffea80` (1570x921) holds correct scene content in a perfect 512x512
origin-anchored square with pure black outside — 262,144 pixels, zero remainder, both edges exact.  Those pixels
match a full bright frame's same corner at 99.87% (chance 14.86%) while a scaled-down reading matches at only
27.05%, so the image is a 1:1 CROP of the right scene and exactly two mechanisms can produce that: a small
render area, or a small scissor.  They are pixel-identical, so one line has to carry both.

WHY IT MUST BE CONDITIONAL.  Three designs failed before this one:
  * a frame window cannot work — `trace_pass()` has a hard `n++ >= 8000` budget (~727 records/frame, so 11
    frames) and the composite renders at in-pass index ~690, i.e. last.  A log aimed at the news truncated
    178 records into the frame that actually had the defect: zero composite records captured.
  * a trigger on "a 512x512 attachment or viewport exists" fires ~6x/frame on good frames, because 512x512
    appears in every frame as a colour-less depth-only pass, and all 297 recorded 512x512 viewports belong to
    depth-only passes or to `6a00fff368`.
  * firing only on passes that CLEAR fired 0 times in 45,000 watched passes and was confidently WRONG: the
    composite is a pass PAIR (a full-size CLEAR pass, then a LOAD pass that does the drawing), so the clip is
    in the LOAD pass and the CLEAR-only predicate skipped it.
So: fire for ANY pass on the watched handle whose render area OR scissor is smaller than the image, and report
both flags plus the loadOp so the two passes stay distinguishable.  Silent on healthy frames, no frame window,
and a periodic summary so a zero-fire run is provably alive rather than silently broken.

WHAT IT FOUND.  One line named the cause (run ca2):
    CLEARAREA f=6489 tgt=6a00ffea80 img=1570x921 lvl=0 extent=512x512 AREA=1 SCISSOR=0 fresh=0 cleared=0
              loadop=0 layout=1 sc=0 0 1570 921 hs=1 vp=0 0 1570 921 hv=1 depth=6a00fff968 d=512x512 n=1
The depth attachment was 512x512 while colour0 was 1570x921, so the extent fold produced 512x512.  The guest's
viewport and scissor were both full size, and AREA=1 SCISSOR=0 rules the scissor out.  See
patch-keep-colour-area.py for the fix.

Env: NX_CLEAR_AREA=<hex guest handle>  (e.g. 6a00ffea80).  Unset: nothing runs and the shipped path is unchanged.

runtime/src/nvn/nvn_draw.cpp; idempotent (--restore removes the block by its markers).

Usage: python3 tools/patches/patch-clear-area.py [--restore]   (SP2PORT override)
"""
import os
import sys

ROOT = os.environ.get("SP2PORT", "/home/hexa/sp2port")
F = os.path.join(ROOT, "runtime/src/nvn/nvn_draw.cpp")

MARK = "PATCH-CLEAR-AREA"
ANCHOR = "    ri.renderArea = {{0, 0}, extent};\n"
END_ANCHOR = "    ri.layerCount = 1;\n"

OLD = ANCHOR + END_ANCHOR

NEW = ANCHOR + """    // PATCH-CLEAR-AREA (NX_CLEAR_AREA=<hex handle>): log any pass whose colour0 is the watched target and whose
    // render area OR scissor is smaller than that image. Two distinct ways to clip a target at 1:1, and they are
    // pixel-identical in output, so one line must carry both.
    //
    // Measured 2026-11-13: the news composite 6a00ffea80 holds correct scene content in a perfect 512x512
    // origin-anchored square with pure black outside, on ~1 frame in 20 (ab_a/06499, keep8/06488, ca1/6479+6481).
    // Those pixels match a full bright frame's corner at 99.87% (chance 14.86%) while a SCALED reading matches at
    // only 27.05% - so it is a crop at 1:1, which excludes the viewport (a small viewport would scale) and leaves
    // exactly two candidates: a small renderArea, or a small scissor.
    //
    // FIRST VERSION OF THIS INSTRUMENT WAS WRONG and its 45,000-pass clean run proved it: it fired only on passes
    // that CLEAR, on the theory that a small clear area leaves the outside uninitialised. But the composite is a
    // pass PAIR - a full-size CLEAR pass, then a LOAD pass that does the drawing - so a small area on the CLEAR
    // pass would have been caught while the LOAD pass, the one that actually clips the draws, was skipped.
    //
    // So: fire for ANY pass on the watched target whose renderArea or scissor is smaller than the image, and
    // report the loadOp so the two passes are distinguishable. Silent on healthy frames, no frame window (the
    // composite renders at in-pass index ~690 of ~727 and trace_pass()'s 8000-line budget truncates first), and a
    // periodic count so a zero-fire run is provably alive.
    if (const char* ca_env = std::getenv("NX_CLEAR_AREA"); ca_env && *ca_env && t.color_count &&
                                                     t.colors[0] == std::strtoull(ca_env, nullptr, 16) &&
                                                     g_pass_images[0]) {
        static uint64_t ca_passes = 0, ca_fired = 0;
        const GpuImage& ci = *g_pass_images[0];
        const bool area_small = extent.width < ci.width || extent.height < ci.height;
        const bool sc_small = g_state.has_scissor &&
                              (uint32_t(std::max(0, g_state.scissor[2])) < extent.width ||
                               uint32_t(std::max(0, g_state.scissor[3])) < extent.height);
        if (area_small || sc_small) {
            if (ca_fired++ < 400) {
                const uint32_t clv = std::min<uint32_t>(t.views.level[0], ci.levels - 1);
                log("CLEARAREA f=%llu tgt=%llx img=%ux%u lvl=%u extent=%ux%u AREA=%d SCISSOR=%d fresh=%d cleared=%d "
                    "loadop=%d layout=%d sc=%d %d %d %d hs=%d vp=%d %d %d %d hv=%d depth=%llx d=%ux%u n=%u",
                    (unsigned long long)g_frame.load(), (unsigned long long)t.colors[0], ci.width, ci.height, clv,
                    extent.width, extent.height, int(area_small), int(sc_small), int(fresh >> 0 & 1),
                    int(cleared >> 0 & 1), int(colors[0].loadOp), int(ci.layout), int(g_state.scissor[0]),
                    int(g_state.scissor[1]), int(g_state.scissor[2]), int(g_state.scissor[3]),
                    int(g_state.has_scissor), int(g_state.viewport[0]), int(g_state.viewport[1]),
                    int(g_state.viewport[2]), int(g_state.viewport[3]), int(g_state.has_viewport),
                    (unsigned long long)t.depth, dimg ? dimg->width : 0u, dimg ? dimg->height : 0u, t.color_count);
            }
        }
        if (++ca_passes % 5000 == 0)
            log("CLEARAREA summary: %llu watched passes, %llu fired", (unsigned long long)ca_passes,
                (unsigned long long)ca_fired);
    }
""" + END_ANCHOR


def main():
    t = open(F, encoding="utf-8", errors="replace", newline="").read()

    if "--restore" in sys.argv:
        i = t.find(MARK)
        if i < 0:
            print("nothing to restore")
            return
        start = t.rfind(ANCHOR, 0, i)
        if start < 0:
            raise SystemExit("cannot find the block start before the marker")
        end = t.find(END_ANCHOR, i)
        if end < 0:
            raise SystemExit("cannot find the block end after the marker")
        t = t[:start] + OLD + t[end + len(END_ANCHOR):]
        open(F, "w", encoding="utf-8", newline="").write(t)
        print("restored", F)
        return

    if MARK in t:
        print("already applied", F)
        return
    if t.count(OLD) != 1:
        raise SystemExit("anchor found %d times (expected 1): %s" % (t.count(OLD), F))
    open(F, "w", encoding="utf-8", newline="").write(t.replace(OLD, NEW, 1))
    print("patched", F)


if __name__ == "__main__":
    main()
