#!/usr/bin/env python3
"""Keep the colour render area: drop a wrongly-sized depth attachment instead of clipping the colour target.

THE DEFECT.  The news screen's panel flicker had, for one of its two signatures, a target rendered into only a
fifth of its area.  On the affected frames the composite `6a00ffea80` (1570x921) holds correct scene content
in a perfect 512x512 origin-anchored square with pure black outside — 262,144 pixels, zero remainder, both
edges exact — and those pixels match a full bright frame's same corner at 99.87% (chance 14.86%) while a
scaled-down reading matches at only 27.05%.  So the image is a 1:1 CROP of the right scene: not a scaled
copy, and not missing draws.

THE CAUSE.  `begin_rendering` folds the render area by minimum over the colour attachments and THEN over the
depth:

    extent = min(extent, colour0 >> level)          (the colour loop)
    extent = min(extent, depth   >> level)          (the depth branch)   <- this one

On the affected frames the depth handle `6a00fff968` had resolved to a 512x512 incarnation while colour0 was
1570x921, so the fold produced 512x512 and every draw into the composite was clipped.  Measured directly with
the NX_CLEAR_AREA instrument (see patch-clear-area.py), run ca2, one line per anomalous pass:

    CLEARAREA f=6489 tgt=6a00ffea80 img=1570x921 lvl=0 extent=512x512 AREA=1 SCISSOR=0 fresh=0 cleared=0
              loadop=0 layout=1 sc=0 0 1570 921 hs=1 vp=0 0 1570 921 hv=1 depth=6a00fff968 d=512x512 n=1

Colour target 1570x921, depth 512x512, resulting extent 512x512, and the guest's own viewport AND scissor
both full size (0 0 1570 921): the guest believed the target was 1570x921, and the clip came entirely from
the port's fold.  `AREA=1 SCISSOR=0` also rules out the scissor as the alternative explanation.

Effect, with the switch on: 0 rectangles in 40 composites in two fix runs (ca3, ca4) against 2 of 40 in each
control run (ca1, ca2), plus 1 each in the earlier runs ab_a and keep8.

WHY DROP RATHER THAN CLAMP.  Vulkan requires renderArea to lie within EVERY attachment, so a 1570x921 area
with a 512x512 depth view is invalid: no area satisfies both.  Dropping the wrongly-sized depth view renders
the colour image whole, which is what the guest asked for.  It is safe for the composite specifically because
its draw has the depth test disabled (`depth func 4 write 0 ... test 0` in the draw trace), so no pixel test
depends on that attachment.

THE GUARD THAT MATTERS.  `extent == UINT32_MAX` means no colour attachment was folded at all — a depth-only
pass, where the depth IS the render area.  Without the `have_colour_area` test the first version of this
patch logged `colour0 is 4294967295x4294967295` and dropped a legitimate depth attachment on every depth-only
pass (40 lines in run ca3).  Do not remove that test.

WHAT THIS IS NOT.  It stops the clipping; it does not explain why one guest handle — `6a00fff968`, declared
at 23 different sizes across a run (960x540, 977x550, 1024x1024, 3000x3000, 1920x1080, 512x512, 1x1, 1x0, ...)
— resolves to 512x512 on some frames and 1570x921 on others.  That is the resolution / incarnation path
(nvn_incarnation.cpp), and it is where the real fix belongs.  This patch establishes only that the fold is
what clipped the colour target, with a control to prove it.

Env: NX_KEEP_COLOUR_AREA=1 turns it on.  Off by default: the shipped path is byte-for-byte unchanged.

runtime/src/nvn/nvn_draw.cpp; idempotent (--restore removes the block by its markers).

Usage: python3 tools/patches/patch-keep-colour-area.py [--restore]   (SP2PORT override)
"""
import os
import sys

ROOT = os.environ.get("SP2PORT", "/home/hexa/sp2port")
F = os.path.join(ROOT, "runtime/src/nvn/nvn_draw.cpp")

MARK = "PATCH-KEEP-COLOUR-AREA"
# The block ends at the depth branch's closing brace; restore uses these bounds rather than matching the whole
# inserted text, so a differently-worded build of the block still restores.
OPEN_ANCHOR = "        depth.storeOp = VK_ATTACHMENT_STORE_OP_STORE;\n"
CLOSE_ANCHOR = "    } else {\n"
# A unique line from the END of the inserted block, used to locate where the block's own closing brace is
# before looking for the depth branch's closing brace (the block contains a nested `} else {`).
BLOCK_END_ANCHOR = "            extent = {std::min(extent.width, std::max(1u, de.width)), std::min(extent.height, std::max(1u, de.height))};\n        }\n"

OLD = OPEN_ANCHOR + (
    "        extent = {std::min(extent.width, std::max(1u, dimg->width >> level)),\n"
    "                  std::min(extent.height, std::max(1u, dimg->height >> level))};\n"
    "    } else {\n"
)

NEW = OPEN_ANCHOR + """        // PATCH-KEEP-COLOUR-AREA (NX_KEEP_COLOUR_AREA=1, OFF by default: the shipped path is unchanged).
        //
        // A depth attachment SMALLER than the colour target shrinks the whole render area to the depth's size
        // (the min below), which clips the colour target at 1:1. Measured 2026-11-13: on the frames where the
        // news composite 6a00ffea80 (1570x921) holds correct content in only a 512x512 origin-anchored square,
        // the depth handle 6a00fff968 had resolved to a 512x512 incarnation, so extent became 512x512 and every
        // draw was clipped. The guest's own viewport and scissor were both FULL size (0 0 1570 921), so the
        // clip came entirely from this fold.
        //
        // Vulkan requires renderArea to lie within every attachment, so a 1570x921 area with a 512x512 depth
        // view is invalid and both cannot be kept. Under this switch the wrongly-sized depth attachment is
        // DROPPED for that pass, so the colour image renders whole instead of a fifth of its area, and it is
        // logged: a depth attachment of the wrong size is a resolution defect to fix at its source rather than
        // to paper over here. Safe for the composite specifically, whose draw has the depth test disabled
        // (`depth func 4 write 0 ... test 0`), so no pixel test depends on the attachment.
        static const bool keep_area = std::getenv("NX_KEEP_COLOUR_AREA") != nullptr;
        const VkExtent2D de{dimg->width >> level, dimg->height >> level};
        // extent == UINT32_MAX means NO colour attachment was folded (a depth-only pass): there the depth IS the
        // render area and must never be dropped. Without this guard the first version of this patch logged
        // "colour0 is 4294967295x4294967295" and dropped a legitimate depth attachment on depth-only passes.
        const bool have_colour_area = extent.width != UINT32_MAX && extent.height != UINT32_MAX;
        if (keep_area && have_colour_area && (de.width < extent.width || de.height < extent.height)) {
            static uint64_t drop_n = 0;
            if (drop_n++ < 40)
                log("KEEPCOLOUR f=%llu depth %llx is %ux%u but colour0 is %ux%u: dropping the depth attachment so "
                    "the colour area is not clipped (%llu so far)",
                    (unsigned long long)g_frame.load(), (unsigned long long)t.depth, de.width, de.height,
                    extent.width, extent.height, (unsigned long long)drop_n);
            dimg = nullptr;
            depth = VkRenderingAttachmentInfo{VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO};
            g_pass_images[8] = nullptr;
        } else {
            extent = {std::min(extent.width, std::max(1u, de.width)), std::min(extent.height, std::max(1u, de.height))};
        }
    } else {
"""


def restore(t):
    """Cut from the block's opening anchor to the depth branch's closing brace, and put OLD back.

    The end bound must be the FIRST `    } else {` at that exact indentation AFTER the inserted block's own
    `        } else {` line — the inserted block contains a nested `} else {` of its own, so searching for
    CLOSE_ANCHOR from the marker alone stops inside the block and leaves a fragment behind. Anchoring on
    BLOCK_END (the last unique line of the inserted text) avoids that.
    """
    i = t.find(MARK)
    if i < 0:
        return None
    start = t.rfind(OPEN_ANCHOR, 0, i)
    if start < 0:
        raise SystemExit("cannot find the block start (storeOp anchor) before the marker")
    # Find the end of the inserted block: the depth branch's closing `    } else {` that FOLLOWS the block's
    # own final `        }` line. Search forward from BLOCK_END_ANCHOR when present, else from the marker.
    anchor = t.find(BLOCK_END_ANCHOR, i)
    from_pos = anchor if anchor >= 0 else i
    end = t.find(CLOSE_ANCHOR, from_pos)
    if end < 0:
        raise SystemExit("cannot find the block end (depth branch close) after the marker")
    return t[:start] + OLD + t[end + len(CLOSE_ANCHOR):]


def main():
    t = open(F, encoding="utf-8", errors="replace", newline="").read()

    if "--restore" in sys.argv:
        r = restore(t)
        if r is None:
            print("nothing to restore")
            return
        open(F, "w", encoding="utf-8", newline="").write(r)
        print("restored", F)
        return

    if MARK in t:
        print("already applied", F)
        return
    if t.count(OLD) != 1:
        raise SystemExit("unpatched pattern found %d times (expected 1): %s" % (t.count(OLD), F))
    open(F, "w", encoding="utf-8", newline="").write(t.replace(OLD, NEW, 1))
    print("patched", F)


if __name__ == "__main__":
    main()
